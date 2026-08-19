"""Tests for the PR Triage workflow fix (#140).

Validates that the ``Check PR template`` step in
``.github/workflows/issues.yml`` survives a PR body containing single
quotes (``Rik's``, ``don't``), double quotes, newlines, ``$`` and backticks.

The previous implementation inlined the PR body expression directly into
the ``run: |`` block. GitHub Actions inlines the expression on a single
line; any single quote in the PR body broke the shell quoting and produced
``unexpected EOF while looking for matching `'``. The fix passes the body
via ``env: PR_BODY`` and uses ``printf '%s'`` (literal transfer, no shell
interpretation).

CRITICAL (discovered while testing the first attempt, PR #142): GitHub
Actions substitutes EVERY ``github.event.*`` expression in the whole step
— ``run``, ``env`` AND **comments** alike. So the body expression must
appear ONLY in the ``env:`` block, never in a ``run: |`` comment. These
tests enforce that invariant.

The tests simulate the workflow step locally (GitHub Actions is not
available in the test environment) by extracting the step, setting the env
var with a hostile PR body, and executing the ``run: |`` block in ``bash
-e``. They assert the step runs without a shell error and the WARNING echo
fires when the body is short.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "issues.yml"


def _load_workflow() -> dict:
    with WORKFLOW_PATH.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


def _find_step(job: dict, step_name: str) -> dict:
    """Return the step dict for a named step in a job."""
    for step in job.get("steps", []):
        assert isinstance(step, dict)
        if step.get("name") == step_name:
            assert step.get("run"), f"step {step_name!r} has no run block"
            return step
    pytest.fail(f"step {step_name!r} not found in job")


def _simulate_step(step: dict, pr_body: str) -> subprocess.CompletedProcess:
    """Execute the step's run block with the PR body set in the env.

    Mirrors what GitHub Actions does: the ``env:`` block's
    ``PR_BODY`` variable is set to the (literal) PR body, and the
    ``run: |`` block is executed with that env. The run block must NOT
    contain the body expression (it is only in ``env:``); the simulation
    only sets the env var and runs the block.
    """
    run_block = step.get("run", "")
    env = dict(step.get("env") or {})
    env["PR_BODY"] = pr_body
    env_str = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    return subprocess.run(
        ["bash", "-e", "-c", f"env {env_str} bash -e -c " + shlex.quote(run_block)],
        capture_output=True,
        text=True,
        timeout=10,
    )


HOSTILE_BODIES = [
    # Single quotes (the #140 regression).
    "Rik's Context Engine PR — don't merge this",
    "It's a test: 'single' and \"double\" quotes",
    # Newlines + backticks + $.
    "line one\nline two\n`backtick` $HOME ${PATH}",
    # Very short body (triggers the WARNING branch).
    "x" * 10,
    # Realistic PR body with apostrophes.
    "## Summary\nRik's API works now. Don't break it.\n\n" + "details " * 10,
]


class TestCheckPRTemplate:
    def test_body_expression_only_in_env(self):
        """#140 regression guard: the body expression must appear ONLY in
        the env block, never in the run block (not even in a comment).

        GitHub Actions substitutes EVERY github.event expression in the
        whole step (run + env + comments). An in-comment reference would
        inline the body into a comment line → `bad substitution` /
        `unexpected EOF` (PR #142 first attempt, run 32213835576).
        """
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        run = step.get("run", "")
        env = step.get("env") or {}
        assert "PR_BODY" in env, "fix must pass the body via env: PR_BODY"
        assert "github.event.pull_request.body" not in run, (
            "the body expression must NOT appear in the run block "
            "(not even in a comment) — GitHub Actions substitutes it "
            "everywhere in the step and inlines the body into the script"
        )

    def test_run_uses_printf(self):
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        assert "printf '%s'" in step.get("run", ""), (
            "fix must use printf '%s' (safe literal transfer)"
        )

    @pytest.mark.parametrize("body", HOSTILE_BODIES)
    def test_step_succeeds_with_hostile_body(self, body: str):
        """The step must NOT crash on any of these bodies."""
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        result = _simulate_step(step, body)
        assert result.returncode == 0, (
            f"shell failed on body {body!r}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # No shell syntax error (the #140 regression).
        assert "unexpected EOF" not in result.stderr, (
            f"regression: shell syntax error on body {body!r}:\n{result.stderr}"
        )
        assert "bad substitution" not in result.stderr, (
            f"regression: bad substitution on body {body!r}:\n{result.stderr}"
        )

    def test_warning_fires_on_short_body(self):
        """A short body must trigger the WARNING echo (existing behavior)."""
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        result = _simulate_step(step, "short")
        assert result.returncode == 0
        assert "WARNING: PR description is very short" in result.stdout

    def test_no_warning_on_long_body(self):
        """A long body must NOT trigger the WARNING echo."""
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        result = _simulate_step(step, "long " * 50)
        assert result.returncode == 0
        assert "WARNING" not in result.stdout


class TestOtherRunBlocks:
    """Kritik 4: other quote-sensitive run: | blocks in the same workflow."""

    def test_no_other_step_inlines_pr_body(self):
        # Only the Check PR template step may reference the PR body, and it
        # must do so via the env block (not the run block).
        wf = _load_workflow()
        for job_name, job in wf["jobs"].items():
            for step in job.get("steps", []):
                if not isinstance(step, dict) or "run" not in step:
                    continue
                run = step["run"]
                if "github.event.pull_request.body" in run:
                    pytest.fail(
                        f"job {job_name!r} step {step.get('name')!r} inlines "
                        f"the PR body into the run block — quote-unsafe"
                    )

    def test_parse_pr_step_is_quote_safe(self):
        # The "Parse PR" step echoes the PR title/number/base.ref inside
        # double quotes; a single quote in the title is harmless (bash only
        # treats ' specially outside double quotes). We do NOT execute this
        # step's run block (it contains unrelated ${{ ... }} expressions
        # that would fail as shell syntax); we assert structural safety.
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Parse PR")
        run = step.get("run", "")
        assert 'echo "PR: ${{ github.event.pull_request.title }}"' in run
        assert "github.event.pull_request.body" not in run
