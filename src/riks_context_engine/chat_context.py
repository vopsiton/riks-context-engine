"""Chat context wiring — the glue between /api/chat and the context engine.

Replaces ECHO MODE (#158): the user message + assistant reply are written to
the tenant-scoped ContextWindowManager, and the LLM prompt is assembled from
the last N messages + semantic memory recall BEFORE the LLM call.

Design:
- ``build_context_block`` is pure (no I/O) so it is trivially unit-testable.
- ``remember_exchange`` writes user + assistant to the tenant context window
  and extracts a simple fact (name) into semantic memory for recall.
- Token budget: if the context block exceeds ``max_context_tokens``, older
  messages are truncated (newest kept) — no error is raised.
"""

from __future__ import annotations

import os
import re
from typing import Any

from riks_context_engine.context.manager import ContextWindowManager
from riks_context_engine.memory.semantic import SemanticMemory

# ── Config (env-overridable) ──────────────────────────────────────────────────

#: How many recent context-window messages to include in the prompt.
CHAT_CONTEXT_MAX_MESSAGES: int = int(os.environ.get("CHAT_CONTEXT_MAX_MESSAGES", "15"))

#: Rough token budget for the context block (≈4 chars/token heuristic).
CHAT_CONTEXT_MAX_TOKENS: int = int(os.environ.get("CHAT_CONTEXT_MAX_TOKENS", "1500"))

#: How many semantic-memory recall entries to include (max).
CHAT_SEMANTIC_RECALL_MAX: int = int(os.environ.get("CHAT_SEMANTIC_RECALL_MAX", "5"))


def estimate_tokens(text: str) -> int:
    """Rough token estimate (≈4 chars/token). Good enough for budgeting."""
    return max(1, len(text) // 4)


def _extract_name(content: str) -> str | None:
    """Extract a person's name from a self-introduction pattern.

    Handles "Benim adım Vahit", "Adım Vahit", "My name is Vahit", etc.
    Returns the name or None.
    """
    # Turkish patterns
    m = re.search(r"(?:benim\s+adım|adım)\s+([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)", content, re.IGNORECASE)
    if m:
        return m.group(1)
    # English patterns
    m = re.search(r"my\s+name\s+is\s+([A-Z][a-z]+)", content, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def remember_exchange(
    ctx_mgr: ContextWindowManager,
    sem_mem: SemanticMemory,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Write the exchange to the tenant context window + semantic memory.

    (a) Context window: user message (importance 0.6, grounding) + assistant
    reply (importance 0.5).
    (b) Semantic memory: extract a name fact if present in the user message
    ("Benim adım Vahit" → subject="user", predicate="name", object="Vahit").
    """
    ctx_mgr.add(role="user", content=user_message, importance=0.6, is_grounding=True)
    ctx_mgr.add(role="assistant", content=assistant_reply, importance=0.5)

    # Semantic memory: extract simple facts for future recall.
    name = _extract_name(user_message)
    if name:
        sem_mem.add(subject="user", predicate="name", object=name, confidence=0.9)


def build_context_block(
    ctx_mgr: ContextWindowManager,
    sem_mem: SemanticMemory,
    query: str,
    max_messages: int | None = None,
    max_tokens: int | None = None,
    max_recall: int | None = None,
) -> str:
    """Assemble the prompt context block from the context window + semantic memory.

    (b) Read path: last N context-window messages (newest last) + semantic
    memory recall for ``query``. Token budget: if the block exceeds
    ``max_tokens``, older messages are truncated (newest kept) — no error.

    Returns an empty string if there is nothing to include.
    """
    max_messages = max_messages or CHAT_CONTEXT_MAX_MESSAGES
    max_tokens = max_tokens or CHAT_CONTEXT_MAX_TOKENS
    max_recall = max_recall or CHAT_SEMANTIC_RECALL_MAX

    parts: list[str] = []

    # Context window: last N messages.
    messages = ctx_mgr.get_messages(include_pruned=False)
    if messages:
        recent = messages[-max_messages:]
        lines: list[str] = []
        for msg in recent:
            lines.append(f"{msg.role}: {msg.content}")
        block = "\n".join(lines)
        # Truncate from the OLDEST end if over budget (newest kept).
        while estimate_tokens(block) > max_tokens and len(recent) > 1:
            recent = recent[1:]
            block = "\n".join(f"{m.role}: {m.content}" for m in recent)
        if block:
            parts.append(f"## Recent conversation\n{block}")

    # Semantic memory recall.
    if query:
        entries = sem_mem.recall(query)[:max_recall]
        if entries:
            facts = [f"- {e.subject} {e.predicate} {e.object or ''}" for e in entries]
            parts.append("## Relevant facts\n" + "\n".join(facts))

    if not parts:
        return ""

    return (
        "You have access to the user's context. Use it to answer the question. "
        "If the context contains the answer, use it directly.\n\n" + "\n\n".join(parts)
    )


def build_llm_prompt(base_prompt: str, context_block: str) -> str:
    """Combine a base system prompt with the context block."""
    if not context_block:
        return base_prompt
    return f"{base_prompt}\n\n{context_block}"


def chat_response_with_context(
    ctx_mgr: ContextWindowManager,
    sem_mem: SemanticMemory,
    user_message: str,
    model: str,
    llm_call: Any | None = None,
) -> tuple[str, str]:
    """Full chat flow: read context → build prompt → LLM call → write exchange.

    Args:
        ctx_mgr: Tenant-scoped context window manager.
        sem_mem: Tenant-scoped semantic memory.
        user_message: The user's message.
        model: Model name (passed through to the LLM call).
        llm_call: Optional callable(prompt, model) -> str. If None, a
            deterministic stub is used (reads the context block and echoes
            back the answer it finds — for CI/testing).

    Returns:
        (assistant_reply, context_block_used) — the reply and the context
        block that was injected into the prompt (for observability/testing).
    """
    context_block = build_context_block(ctx_mgr, sem_mem, user_message)
    prompt = build_llm_prompt(f"Model: {model}", context_block)

    if llm_call is not None:
        reply = llm_call(prompt, model)
    else:
        # Deterministic stub: if the context block contains the answer to a
        # name question, return it. This proves the wiring (message →
        # context → prompt → LLM) without a real LLM.
        reply = _stub_llm(prompt, model, user_message)

    # (a) Write: persist the exchange for future turns.
    remember_exchange(ctx_mgr, sem_mem, user_message, reply)

    return reply, context_block


def _stub_llm(prompt: str, model: str, user_message: str) -> str:
    """Deterministic stub LLM for CI/testing.

    Reads the context block in the prompt and answers name questions from it.
    Proves the wiring: the user's earlier "Benim adım Vahit" is in the
    context window, the context block is in the prompt, and the stub reads
    it back.
    """
    # Name question patterns (Turkish + English).
    name_patterns = [
        r"adım\s+ne",
        r"isim\s+ne",
        r"what's\s+my\s+name",
        r"what\s+is\s+my\s+name",
        r"benim\s+adım",
    ]
    is_name_question = any(re.search(p, user_message, re.IGNORECASE) for p in name_patterns)

    if is_name_question:
        # Look for "user name X" in the context block (semantic memory fact)
        # or "My name is X" / "adım X" in the context window messages.
        m = re.search(r"user name (\S+)", prompt, re.IGNORECASE)
        if m:
            return f"[{model}] Adın {m.group(1)}."
        m = re.search(r"My name is ([A-Z][a-z]+)", prompt)
        if m:
            return f"[{model}] Your name is {m.group(1)}."
        m = re.search(
            r"user:.*?(?:adım|benim\s+adım)\s+([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)",
            prompt,
            re.IGNORECASE,
        )
        if m:
            return f"[{model}] Adın {m.group(1)}."

    # Fallback: echo with model tag (like the old echo mode, but now
    # context-aware when the context has the answer).
    return f"[{model}] Mesajını aldım: {user_message!r}. Context: {'var' if 'Recent conversation' in prompt else 'yok'}."
