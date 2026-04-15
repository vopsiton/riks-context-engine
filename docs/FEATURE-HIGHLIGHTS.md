# Rik Context Engine — Feature Highlights

> In-depth looks at the features that make Rik Context Engine different.

---

## Feature 1: 3-Tier Memory That Actually Thinks Like You Do

Most AI tools store everything in one flat layer — like dumping your entire life into one unorganized folder.

Rik Context Engine mirrors how humans actually remember:

```
TIER 1: EPISODIC MEMORY (Session)
─────────────────────────────────
What just happened? Recent conversations, session-specific facts,
temporary context that won't matter next week.

Real example:
  "In today's session Vahit mentioned the auth service was timing out"
  "He prefers pull requests to be under 500 lines"
  "We were debugging the JWT validation logic"

TIER 2: SEMANTIC MEMORY (Long-Term)
────────────────────────────────────
What do I know permanently? Facts, concepts, relationships
that persist across sessions.

Real example:
  "auth_service → uses → JWT RS256"
  "Vahit's production server → runs_on → port 8443"
  "deploy_pipeline → type → blue_green (not rolling)"

TIER 3: PROCEDURAL MEMORY (Skills)
────────────────────────────────────
How do I do this? Captured workflows, step-by-step processes,
success rates for different approaches.

Real example:
  Procedure: "Deploy to Production"
  Steps: ["ssh prod-server", "cd /app", "docker-compose pull",
          "./scripts/blue-green-switch.sh", "verify health endpoint"]
  Success rate: 94% (last 50 deploys)
```

**Why it matters:** The system automatically moves information between tiers based on access patterns. Frequently referenced episodic facts get promoted to Semantic. Procedures you use often get tracked for success rate. It gets smarter without you doing anything.

---

## Feature 2: Importance-Scored Context Window

When a 128K context window fills up, most systems just truncate from the beginning — losing potentially important context along with noise.

Rik Context Engine scores every message across 4 weighted dimensions:

```python
# Each message gets this treatment:
score, dims = ImportanceScorer.score(content, role)

# dims = {
#   "user_mentions": 0.0-1.0,    # Weight: 35%
#   "decisions": 0.0-1.0,         # Weight: 25%
#   "new_information": 0.0-1.0,   # Weight: 25%
#   "tool_result": 0.0-1.0,       # Weight: 15%
# }
# overall = weighted average
```

**Real-world impact:**

| Message | Auto-Score | Why |
|---------|-----------|-----|
| "I never want you to suggest Docker Compose in prod" | 0.92 | user_preference + decision |
| "Confirmed: API returns 200 at /health" | 0.65 | tool_result + new_info |
| "sure" | 0.05 | basically noise |
| "Error: connection refused on port 5432" | 0.88 | error pattern + tool_result |

When pruning happens, **low score = first to go**. That "sure" gets nuked. That "never suggest Docker Compose" is immortal.

---

## Feature 3: Coherence-Aware Pruning

Naive pruning breaks conversations. Rik Context Engine validates coherence after every prune:

```python
coherence_valid, score = ctx.validate_coherence()

# Checks:
# ✅ No orphaned assistant responses (assistant message without preceding user)
# ✅ At least one message from each conversation turn preserved
# ✅ All grounding messages (preferences, active projects) intact
# ✅ No excessive consecutive same-role messages (except system/tool)
```

If coherence breaks, the prune is still applied (performance over perfection), but `coherence_valid = False` and you get a `coherence_score < 1.0` so you know something might need manual review.

---

## Feature 4: Knowledge Graph with Semantic Search

Flat vector stores answer "what's similar to X?" but not "who is connected to Y through Z?"

Rik Context Engine's Knowledge Graph answers both:

```python
# Build the graph
user = kg.add_entity("Vahit", EntityType.PERSON, {"role": "Team Lead"})
project = kg.add_entity("Auth Service", EntityType.PROJECT, {"status": "production"})
jwt = kg.add_entity("JWT RS256", EntityType.CONCEPT, {"expires": "1h"})

kg.relate(user, project, RelationshipType.WORKS_WITH)
kg.relate(project, jwt, RelationshipType.USES)

# Query: "What does the Auth Service depend on?"
rels = kg.expand("project_auth_service", depth=2)
# → [(jwt_entity, uses_relationship), ...]

# Query: "Find entities related to deployment"
results = kg.semantic_search("deployment pipeline continuous delivery")
# → [(Entity("deploy_script"), 0.94), (Entity("ci_cd"), 0.89), ...]
```

**Key difference:** The knowledge graph understands *relationships*, not just content similarity.

---

## Feature 5: Self-Improvement Through Reflection

Most AI systems make the same mistakes forever. Rik Context Engine has a reflection loop:

```python
# After interaction
report = analyzer.analyze(
    "session_42",
    conversation=[
        {"role": "user", "content": "Deploy the auth service"},
        {"role": "assistant", "content": "Running kubectl apply..."},
        {"role": "tool", "content": "Error: insufficient permissions on namespace prod"},
    ]
)

# report.went_wrong = ["Error: insufficient permissions on namespace prod"]
# report.lessons = [
#   Lesson(category="tool-use", severity="warning",
#          lesson_text="Check namespace permissions before kubectl apply")
# ]

# Before next deployment
warnings = analyzer.consult_before_task("Deploy auth service to prod")
# → [Lesson(severity="warning", "Check namespace permissions...")]
```

The analyzer tracks mistake frequency by category:

```python
analyzer.track_mistake_frequency()
# {'tool-use': 7, 'context-management': 3, 'security': 1, 'task-planning': 2}
```

If `security` mistakes spike, you know to add more validation checks. If `tool-use` keeps failing on the same pattern, you fix the root cause.

---

## Feature 6: TierManager — Automatic Memory Tiering

You don't have to manually decide what goes where. TierManager does it automatically:

```python
tm = TierManager(
    episodic=ep_mem,
    semantic=sem_mem,
    procedural=proc_mem,
    config=TierConfig(
        promote_threshold=5,       # Access 5+ times → promote to Semantic
        demote_threshold=0,         # 0 = never demote (Semantic is sticky)
        check_interval_accesses=10, # Run auto_tier every 10 accesses
    )
)

# Every 10 times you query an episodic entry, it gets re-evaluated:
result = tm.auto_tier()
# {"promoted": 2, "demoted": 0}
```

**Real example:**
1. First session: "Vahit's cat is named Lumos" → Episodic
2. You mention Lumos 6 times over 3 sessions → TierManager promotes → Semantic (permanent fact)
3. Later you say "I actually hate cats, Lumos is the neighbor's cat" → Semantic gets updated, Episodic records the correction

The memory system **self-organizes** based on usage patterns.

---

## Feature 7: Task Decomposition with Dependency Graphs

"Build it, test it, deploy it" sounds simple. But what if tests need the build artifact? What if deployment depends on tests passing?

Rik Context Engine builds dependency graphs:

```python
decomposer = TaskDecomposer()
graph = decomposer.decompose(
    "Setup auth service, build Docker image, run tests, deploy to production"
)

# graph.tasks = [
#   Task(id="task_1", name="Setup: Auth Service", dependencies=[]),
#   Task(id="task_2", name="Build: Docker Image", dependencies=["task_1"]),
#   Task(id="task_3", name="Test: Run Suite", dependencies=["task_2"]),
#   Task(id="task_4", name="Deploy: Production", dependencies=["task_3"]),
# ]

plan = decomposer.plan_execution(graph)
# [[task_1], [task_2], [task_3], [task_4]]  — sequential
```

Validation catches problems before execution:

```python
valid, error = decomposer.validate_graph(graph)
# error = None if valid
# error = "Cycle detected" or "Task X depends on non-existent Y"
```

---

## Feature 8: Priority Tiers (Don't Prune My Preferences)

Not all context is equal. Rik Context Engine has 4 priority tiers:

| Tier | Name | What goes here | Pruning |
|------|------|---------------|---------|
| 0 | PROTECTED | System instructions, critical config | **Never** |
| 1 | HIGH | User preferences, active projects, tool results | Rarely |
| 2 | MEDIUM | Regular conversation | Yes |
| 3 | LOW | Old, low-importance messages | **First** |

```python
# Mark user preferences as grounding (= TIER_1 implicitly)
ctx.add("user", "I always use blue-green deployment, never rolling",
        importance=0.95, is_grounding=True)
# → priority_tier=1, is_grounding=True → almost never pruned

# Explicit tier control
ctx.add("user", "Background context note", priority_tier=3)
# → First to go when space is needed
```

**Result:** The AI's most critical knowledge — who you are, what you prefer, what you're working on right now — survives the context crunch.
