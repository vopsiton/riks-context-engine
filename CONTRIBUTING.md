# Contributing to Rik's Context Engine

Thank you for your interest in contributing! This project is in early stages, so there's plenty to do.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Running Tests

```bash
pytest
```

With coverage:
```bash
pytest --cov=src/ --cov-report=html
```

## Code Quality

We use:
- **ruff** for linting and formatting
- **mypy** for type checking
- **pre-commit** for automated checks

Run locally:
```bash
ruff check src/
mypy src/
pre-commit run --all-files
```

## Branching Strategy

- `main` - stable, always deployable
- `feature/*` - new features
- `fix/*` - bug fixes
- `sprint/*` - sprint work

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat: add new memory tier`
- `fix: resolve context pruning edge case`
- `docs: update architecture diagram`
- `test: add coverage for semantic memory`

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes with passing tests
3. Open a PR with a clear description
4. Reference the relevant issue (e.g., "Fixes #6")

## Issues

Check the [issue tracker](https://github.com/vopsiton/riks-context-engine/issues) for open work. Sprint 1 issues are highest priority.

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 license.
