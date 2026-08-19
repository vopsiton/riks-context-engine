"""Tests for the PR Triage workflow fix (#140).

Validates that the ``Check PR template`` step in
``.github/workflows/issues.yml`` survives a PR body containing single
quotes (``Rik's``, ``don't``), double quotes, newlines, ``$`` and backticks.

The previous implementation used::

    body_length=$(echo "${{ github.event.pull_request.body }}" | wc -c)

GitHub Actions inlines the expression into the ``run: |`` block on a single
line; any single quote in the PR body broke the shell quoting and produced
``unexpected EOF while looking for matching `'```. The fix uses a
single-quoted heredoc (``<<'EOF_BODY'``) which transfers the body literally.

These tests simulate the workflow step locally (GitHub Actions is not
available in the test environment) by extracting the ``run: |`` block from
the YAML and executing it with a hostile PR body. The tests assert that the
step runs without a shell error and that the WARNING echo fires when the
body is short.
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
    """Substitute the PR body expression and run the block in a shell.

    Mirrors what GitHub Actions does: the ``env:`` block's
    ``${{ github.event.pull_request.body }}`` expression is inlined into
    the environment variable ``PR_BODY`` (as a literal string, not
    shell-interpreted), and the ``run: |`` block is executed with that env
    set. This is the #140 fix pattern (env + ``printf '%s'``).
    """
    run_block = step.get("run", "")
    env = dict(step.get("env") or {})
    # Inline the expression into the env value (GitHub Actions behavior).
    env["PR_BODY"] = pr_body
    # Pass env to the shell via env -S (safe for values with quotes/newlines).
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
    # Realistic PR body with apostrophes in Turkish.
    "## Summary\nRik's API artık çalışıyor. Don't break it.\n\n" + "details " * 10,
]


class TestCheckPRTemplate:
    def test_step_exists_in_workflow(self):
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Check PR template")
        assert "PR_BODY" in (step.get("env") or {}), (
            "fix must pass the body via env: PR_BODY (literal transfer)"
        )
        assert "printf '%s'" in step.get("run", ""), "fix must use printf '%s' (safe transfer)"

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

    def test_parse_pr_step_is_quote_safe(self):
        # The "Parse PR" step echoes the PR title/number/base.ref. A single
        # quote in the title is harmless inside the double-quoted echo
        # (bash only treats ' as a quote inside double quotes when it is
        # unbalanced — but the title is interpolated by GitHub Actions as
        # a literal string, and a single quote inside "..." is safe).
        # We do NOT execute this step's run block (it contains unrelated
        # ${{ ... }} expressions that would fail as shell syntax); we only
        # assert the structural safety: echo inside double quotes, no
        # inline body interpolation.
        wf = _load_workflow()
        job = wf["jobs"]["triage-pr"]
        step = _find_step(job, "Parse PR")
        run = step.get("run", "")
        assert 'echo "PR: ${{ github.event.pull_request.title }}"' in run
        # The body expression must NOT appear in this step (it is only in
        # the Check PR template step, which is env+printf fixed).
        assert "github.event.pull_request.body" not in run

    def test_issue_triage_steps_are_quote_safe(self):
        # Issue Triage uses actions/github-script (JavaScript), not a bash
        # run: | block with event-payload inlining — so it is not subject
        # to the same shell-quoting regression. Verify that the only bash
        # run: | block that inlines the PR body uses the env + printf
        # pattern (the #140 fix).
        wf = _load_workflow()
        for job in wf["jobs"].values():
            for step in job.get("steps", []):
                if "run" not in step:
                    continue
                run = step["run"]
                if "github.event.pull_request.body" in run:
                    env = step.get("env") or {}
                    assert "PR_BODY" in env and "printf '%s'" in run, (
                        f"step {step.get('name')!r} inlines PR body without "
                        f"the env+printf fix — quote-unsafe"
                    )
