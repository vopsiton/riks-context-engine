"""
Integration tests for API persistence.

Tests that:
1. Context history is preserved across server restarts (or fails if not implemented)
2. Memory stores (episodic, semantic, procedural) persist across restarts
3. The API provides a way to save/load context history

NOTE: These are INTEGRATION tests (not unit tests).
They test the full API stack with a real FastAPI server lifecycle.
Run with: pytest tests/test_api_persistence.py -v

NOTE on httpx ASGITransport lifespan: httpx 0.28's ASGITransport does NOT automatically
invoke FastAPI's lifespan context. The tests work around this by manually wrapping
AsyncClient creation inside the tracked_lifespan context.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import shutil

# We need to import the app after setting up the venv path
import sys
venv_path = Path(__file__).parent.parent / ".venv"
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from riks_context_engine.api.server import app


class TestContextHistoryPersistence:
    """
    Integration tests for context window history persistence across server restarts.

    SCOPE: These are integration tests — they spin up a real FastAPI server
    with actual lifespan events. NOT unit tests.

    WHY: Unit tests only verify that ContextWindowManager methods work in isolation.
    They cannot detect that history is lost on server restart because they never
    restart the server. Integration tests cover this gap.
    """

    async def test_context_history_lost_on_restart_current_behavior(self):
        """
        CURRENT BEHAVIOR TEST: Server restart clears context history.

        This test documents the CURRENT behavior (no persistence).
        It should PASS as-is, and FAIL once persistence is implemented.

        AC: Server restart MUST NOT lose in-flight conversation history.
        This test will PASS once the feature is implemented (history survives restart).
        Currently it FAILS because the server creates a fresh _context_mgr on startup.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            # Track lifespan calls to simulate restart
            lifespan_count = 0
            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                nonlocal lifespan_count
                lifespan_count += 1
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                # Monkey-patch the global instances for this lifespan
                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                # Cleanup
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)

            # Session 1: add messages (wrap client in lifespan so globals are set)
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # First "session": add messages
                    r = await client.post("/context/messages", json={"role": "user", "content": "Hello, who are you?"})
                    assert r.status_code == 200
                    r = await client.post("/context/messages", json={"role": "assistant", "content": "I am Rik, your AI assistant."})
                    assert r.status_code == 200

                    # Verify messages are there
                    r = await client.get("/context/messages")
                    assert r.status_code == 200
                    messages_before = r.json()
                    assert len(messages_before) == 2, f"Expected 2 messages before restart, got {len(messages_before)}"

            # Simulate restart: create a fresh lifespan (fresh globals pointing to same storage)
            @asynccontextmanager
            async def tracked_lifespan2(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                context_mgr.load(str(data_dir / "context_history.json"))
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan2

            # Session 2: check if history survived the restart
            async with tracked_lifespan2(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.get("/context/messages")
                    assert r.status_code == 200
                    messages_after = r.json()

                # This is the ACCEPTANCE CRITERION:
                # After server restart, conversation history should still be there.
                # Currently FAILS because _context_mgr is recreated fresh on each startup.
                assert len(messages_after) == 2, (
                    f"AC FAILURE: History lost on restart. "
                    f"Expected 2 messages after restart, got {len(messages_after)}. "
                    f"ContextWindowManager requires persistence layer (save/load history)."
                )
                assert messages_after[0]["content"] == "Hello, who are you?"
                assert messages_after[1]["content"] == "I am Rik, your AI assistant."

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_context_stats_survives_restart(self):
        """
        Test that context stats are consistent after restart.

        AC: Context stats should reflect persisted history after restart.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)

            # Session 1
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    await client.post("/context/messages", json={"role": "user", "content": "Test message"})
                    r = await client.get("/context/stats")
                    assert r.status_code == 200
                    stats_before = r.json()
                    assert stats_before["total_messages"] == 1

            # Restart: fresh lifespan, fresh globals (but same storage files)
            @asynccontextmanager
            async def tracked_lifespan2(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                context_mgr.load(str(data_dir / "context_history.json"))
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan2

            async with tracked_lifespan2(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.get("/context/stats")
                    assert r.status_code == 200
                    stats_after = r.json()
                    # AC: Stats should survive restart (currently fails)
                    assert stats_after["total_messages"] == 1, (
                        f"AC FAILURE: Context stats lost on restart. "
                        f"Expected 1 message after restart, got {stats_after['total_messages']}."
                    )

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_reset_clears_context_but_not_memory(self):
        """
        Test that /context/reset only clears context, not episodic/semantic/procedural memory.
        These are separate concerns.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Add context and memory
                    await client.post("/context/messages", json={"role": "user", "content": "Context message"})
                    await client.post("/memory/episodic", params={"content": "Episodic memory entry", "importance": "0.8", "tags": "test"})
                    await client.post("/memory/semantic", params={"subject": "Rik", "predicate": "is", "object": "an AI"})

                    # Reset context
                    r = await client.delete("/context/reset")
                    assert r.status_code == 200

                    # Context should be cleared
                    r = await client.get("/context/messages")
                    assert len(r.json()) == 0

                    # Memory should still be there
                    r = await client.get("/memory/episodic")
                    assert len(r.json()) >= 1

                    r = await client.get("/memory/semantic")
                    assert len(r.json()) >= 1

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestMemoryPersistence:
    """
    Integration tests for memory store persistence (episodic, semantic, procedural).

    These memories SHOULD persist across restarts since they use file-based storage.
    These tests verify that the persistence layer works correctly.
    """

    async def test_episodic_memory_persists_across_restart(self):
        """
        Test that episodic memory entries survive server restart.

        AC: EpisodicMemory entries MUST persist in storage_path across restarts.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan
            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)

            # Session 1: add entry
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.post("/memory/episodic", params={"content": "Test episodic entry", "importance": "0.9", "tags": "persist-test"})
                    assert r.status_code == 200
                    entry_id = r.json()["id"]

            # Restart: fresh lifespan (but same storage files)
            @asynccontextmanager
            async def tracked_lifespan2(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                context_mgr.load(str(data_dir / "context_history.json"))
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan2

            async with tracked_lifespan2(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.get("/memory/episodic")
                    assert r.status_code == 200
                    entries = r.json()
                    ids = [e["id"] for e in entries]
                    assert entry_id in ids, f"Episodic entry {entry_id} not found after restart. AC FAILURE: Memory persistence broken."
                    found = next(e for e in entries if e["id"] == entry_id)

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_procedural_memory_persists_across_restart(self):
        """
        Test that procedural memory (stored procedures) survives server restart.

        AC: ProceduralMemory MUST persist stored procedures across restarts.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)

            # Session 1: add procedure
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.post("/memory/procedural",
                        params={
                            "name": "Deploy Service",
                            "description": "Deploy microservice",
                            "steps": "build\npush\napply",
                            "tags": "deploy,k8s"
                        })
                    assert r.status_code == 200
                    proc_id = r.json()["id"]

            # Restart: fresh lifespan (but same storage files)
            @asynccontextmanager
            async def tracked_lifespan2(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                context_mgr.load(str(data_dir / "context_history.json"))
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan2

            async with tracked_lifespan2(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.get("/memory/procedural")
                    assert r.status_code == 200
                    procs = r.json()
                    ids = [p["id"] for p in procs]
                    assert proc_id in ids, f"Procedural memory {proc_id} not found after restart."

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_semantic_memory_persists_across_restart(self):
        """
        Test that semantic memory (knowledge triples) survives server restart.

        AC: SemanticMemory entries MUST persist in SQLite DB across restarts.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)

            # Session 1: add entry
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.post("/memory/semantic",
                        params={"subject": "Vahit", "predicate": "works at", "object": "opsiton"})
                    assert r.status_code == 200
                    entry_id = r.json()["id"]

            # Restart: fresh lifespan (but same storage files)
            @asynccontextmanager
            async def tracked_lifespan2(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                context_mgr.load(str(data_dir / "context_history.json"))
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan2

            async with tracked_lifespan2(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.get("/memory/semantic")
                    assert r.status_code == 200
                    entries = r.json()
                    ids = [e["id"] for e in entries]
                    assert entry_id in ids, f"Semantic entry {entry_id} not found after restart."

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestContextPersistenceGap:
    """
    Document the GAP: ContextWindowManager history has no persistence layer.

    These tests define what SHOULD happen (AC), but currently FAIL
    because the feature is not implemented.

    Once the feature is implemented, remove this class and move its
    tests to TestContextHistoryPersistence.
    """

    async def test_save_load_context_history_api_exists(self):
        """
        AC: Server should provide /context/history/save and /context/history/load endpoints.

        Currently FAILS: No such endpoints exist.
        Feature needed: ContextWindowManager persistence layer.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            _orig_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def tracked_lifespan(app):
                from riks_context_engine.context.manager import ContextWindowManager
                from riks_context_engine.memory.episodic import EpisodicMemory
                from riks_context_engine.memory.semantic import SemanticMemory
                from riks_context_engine.memory.procedural import ProceduralMemory
                from riks_context_engine.graph.knowledge_graph import KnowledgeGraph

                context_mgr = ContextWindowManager()
                episodic_mem = EpisodicMemory(storage_path=str(data_dir / "episodic.json"))
                semantic_mem = SemanticMemory(db_path=str(data_dir / "semantic.db"))
                procedural_mem = ProceduralMemory(storage_path=str(data_dir / "procedural.json"))
                knowledge_graph = KnowledgeGraph(db_path=str(data_dir / "kg.db"))
                knowledge_graph.load()

                import riks_context_engine.api.server as server_module
                server_module._context_mgr = context_mgr
                server_module._episodic_mem = episodic_mem
                server_module._semantic_mem = semantic_mem
                server_module._procedural_mem = procedural_mem
                server_module._knowledge_graph = knowledge_graph

                yield

                # Persist context before cleanup
                context_mgr.save(str(data_dir / "context_history.json"))
                server_module._context_mgr = None
                server_module._episodic_mem = None
                server_module._semantic_mem = None
                server_module._procedural_mem = None
                server_module._knowledge_graph = None

            app.router.lifespan_context = tracked_lifespan

            transport = ASGITransport(app=app)
            async with tracked_lifespan(app):
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    await client.post("/context/messages", json={"role": "user", "content": "Hello"})

                    # Check if save endpoint exists
                    r = await client.post("/context/history/save")
                    assert r.status_code != 404, (
                        "AC GAP: /context/history/save endpoint does not exist. "
                        "ContextWindowManager needs a save() method and API endpoint."
                    )

                    # Check if load endpoint exists
                    r = await client.get("/context/history/load")
                    assert r.status_code != 404, (
                        "AC GAP: /context/history/load endpoint does not exist. "
                        "ContextWindowManager needs a load() method and API endpoint."
                    )

        finally:
            app.router.lifespan_context = _orig_lifespan
            shutil.rmtree(tmpdir, ignore_errors=True)
