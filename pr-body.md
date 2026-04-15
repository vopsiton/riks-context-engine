## Summary

Implemented two core features for Rik's Context Engine:

### Self-Reflection Analyzer (reflection/analyzer.py)
- **Category detection**: Automatically categorizes errors into tool-use, context-management, task-planning, communication, and security patterns
- **Severity levels**: info/warning/critical classification
- **Lesson extraction**: Analyzes conversation history to extract actionable lessons
- **Mistake tracking**: `track_mistake_frequency()` shows which error categories occur most
- **Pre-task consultation**: `consult_before_task()` warns about related past mistakes before starting new tasks

### Task Decomposition (tasks/decomposer.py)
- **Goal decomposition**: Splits natural language goals into executable task graphs
- **Dependency inference**: Automatically infers sequential dependencies based on task type
- **Execution planning**: `plan_execution()` respects dependency order
- **Graph validation**: `validate_graph()` checks for cycles and missing dependencies
- **Success criteria**: Each task gets inferred success criteria based on type

## Testing

```bash
source .venv/bin/activate
pytest tests/ -v
```

**Result: 68 tests passing**

## Files Changed
- `src/riks_context_engine/reflection/analyzer.py` - Enhanced with pattern-based analysis
- `src/riks_context_engine/tasks/decomposer.py` - Complete rewrite with dependency inference
- `tests/test_reflection.py` - 19 tests for reflection analyzer
- `tests/test_decomposer.py` - 13 tests for task decomposition

## Security
No security vulnerabilities introduced. Code follows existing patterns and includes input validation.