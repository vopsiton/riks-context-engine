# Rik Context Engine — Quick Start

> **Goal:** Get Rik Context Engine running in 5 minutes.

---

## 1. Install

```bash
pip install riks-context-engine

# Or from source:
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine
pip install -e ".[dev]"
```

---

## 2. Try the Memory System

```python
from riks_context_engine.memory import EpisodicMemory, SemanticMemory, ProceduralMemory

# ── Episodic (session memory) ────────────────────────
em = EpisodicMemory()
em.add("Vahit prefers technical discussions in English", importance=0.9, tags=["preference"])
em.add("Auth service timeout issue traced to JWT validation", importance=0.8)

results = em.query("JWT")
print(results[0].content)
# "Auth service timeout issue traced to JWT validation"

# ── Semantic (long-term knowledge) ──────────────────
sm = SemanticMemory()
sm.add("auth_service", "uses", "JWT RS256", confidence=1.0)
sm.add("auth_service", "token_expiry", "1 hour")

facts = sm.query(subject="auth_service")
print([f"{f.subject} {f.predicate} {f.object}" for f in facts])
# ["auth_service uses JWT RS256", "auth_service token_expiry 1 hour"]

# ── Procedural (skills) ─────────────────────────────
pm = ProceduralMemory()
pm.store(
    name="Deploy to Production",
    description="Blue-green deployment via SSH",
    steps=["ssh prod-server", "cd /app", "docker-compose pull", "./scripts/switch.sh"],
    tags=["devops", "deployment"],
)

proc = pm.recall("Deploy to Production")
print(proc.steps)
```

---

## 3. Use the Context Window Manager

```python
from riks_context_engine.context import ContextWindowManager

ctx = ContextWindowManager(max_tokens=50_000)

# Add messages with auto-importance scoring
ctx.auto_score_and_add("user", "I always use blue-green deployment, never rolling", is_grounding=True)
ctx.auto_score_and_add("assistant", "Understood. Will use blue-green strategy.")
ctx.auto_score_and_add("tool", "Deployed to prod-1. Health check: 200 OK")

# Check status
print(ctx.get_summary())
# {
#   'current_tokens': 89,
#   'usage_percent': 0.18,
#   'active_messages': 3,
#   'pruned_messages': 0,
#   'needs_pruning': False,
#   'coherence_score': 1.0,
# }

# Check pruning recommendation
print(ctx.get_pruning_recommendation())
# {'level': 'none', 'usage_percent': 0.18, 'tokens_to_free': 0, ...}
```

---

## 4. Build a Knowledge Graph

```python
from riks_context_engine.graph import KnowledgeGraph, EntityType, RelationshipType

kg = KnowledgeGraph(db_path="data/kg_demo.db")
kg._load_from_db()  # Load existing data if any

# Add entities
user = kg.add_entity("Vahit", EntityType.PERSON, {"role": "Team Lead", "team": "DevSecOps"})
project = kg.add_entity("Auth Service", EntityType.PROJECT, {"status": "production"})
api = kg.add_entity("REST API", EntityType.SERVICE, {"port": 8443})

# Relate them
kg.relate(user, project, RelationshipType.WORKS_WITH)
kg.relate(project, api, RelationshipType.DEPENDS_ON)
kg.relate(api, api, RelationshipType.USES)  # self-loop example

# Expand: what does the Auth Service connect to?
connections = kg.expand("project_auth_service", depth=1)
for entity, rel in connections:
    print(f"{entity.name} --[{rel.relationship_type.value}]-->")

# Output:
# REST API --[depends_on]-->
```

---

## 5. Decompose a Task

```python
from riks_context_engine.tasks import TaskDecomposer

decomposer = TaskDecomposer()
graph = decomposer.decompose(
    "Setup auth service, build Docker image, run tests, deploy to production"
)

print(f"Goal: {graph.goal}")
for task in graph.tasks:
    deps = ", ".join(task.dependencies) or "none"
    print(f"  [{task.id}] {task.name}")
    print(f"          dependencies: {deps}")

# Validate for cycles
valid, error = decomposer.validate_graph(graph)
print(f"Graph valid: {valid}, error: {error}")

# Get execution plan
plan = decomposer.plan_execution(graph)
for i, batch in enumerate(plan):
    print(f"Step {i+1}: {[t.name for t in batch]}")
```

---

## 6. Run the Reflection Loop

```python
from riks_context_engine.reflection import ReflectionAnalyzer

analyzer = ReflectionAnalyzer()

conversation = [
    {"role": "user", "content": "Deploy auth service to prod"},
    {"role": "assistant", "content": "Running kubectl apply..."},
    {"role": "tool", "content": "Error: Insufficient permissions on namespace prod"},
    {"role": "assistant", "content": "Failed. Let me check RBAC."},
]

report = analyzer.analyze("session_42", conversation)
print(f"Went wrong: {report.went_wrong}")
print(f"Lessons: {[l.lesson_text for l in report.lessons]}")

# Before next deployment — consult past failures
warnings = analyzer.consult_before_task("Deploy auth service")
if warnings:
    print(f"⚠️  Past failure: {warnings[0].lesson_text}")
```

---

## 7. Use the CLI

```bash
# Show version
riks --version

# Memory operations
riks memory add --type episodic "Vahit prefers concise responses"
riks memory query --type semantic "auth"

# Context stats
riks context stats

# Task decomposition
riks task "Setup database, build app, run tests, deploy" --execute
```

---

## 8. Docker Setup

```bash
# Build
docker build -t riks-context-engine:dev .

# Run dev environment
docker-compose up dev

# Test inside container
docker-compose exec dev python -c "
from riks_context_engine import *
ctx = ContextWindowManager(max_tokens=10_000)
ctx.add('user', 'Hello', importance=0.5)
print('Memory engine works!')
"
```

---

## Next Steps

- 📖 [Full API Documentation](./API.md)
- 🏗️ [Architecture Overview](./ARCHITECTURE.md)
- ✨ [Feature Highlights](./FEATURE-HIGHLIGHTS.md)
- 🚀 [Deployment Guide](./DEPLOYMENT.md)
