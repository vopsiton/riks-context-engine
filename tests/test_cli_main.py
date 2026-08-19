"""Test CLI main entry point (#124).

2026-08-19: updated after `riks memory add/query` became real implementations
(#124 turn 1). The old placeholder tests asserted the fake
"Command executed successfully" no-op behavior — replaced with honest
assertions: implemented commands return 0, unimplemented ones return 1 and
say so. Full integration coverage lives in tests/test_cli_memory.py.
"""

import sys

import pytest

from riks_context_engine.cli.main import main


class TestCLI:
    """Tests for CLI main entry point."""

    def test_main_version_flag(self, capsys):
        """Test riks --version outputs version."""
        sys.argv = ["riks", "--version"]
        result = main()
        out = capsys.readouterr().out
        assert result == 0
        assert "riks-context-engine" in out

    def test_main_no_args(self, capsys):
        """Test riks with no args shows help."""
        sys.argv = ["riks"]
        result = main()
        capsys.readouterr()
        # Returns 1, prints help
        assert result == 1

    def test_main_memory_add_requires_content(self, capsys):
        """memory add with no content must fail with a real error (#124)."""
        sys.argv = ["riks", "memory", "add"]
        result = main()
        err = capsys.readouterr().err
        assert result != 0
        assert "error:" in err

    def test_main_memory_query_requires_term(self, capsys):
        """memory query with no term must fail with a real error (#124)."""
        sys.argv = ["riks", "memory", "query"]
        result = main()
        err = capsys.readouterr().err
        assert result != 0
        assert "error:" in err

    def test_memory_stats_still_reports_not_implemented(self, capsys):
        """memory stats is out of scope for #124 turn 2: must NOT pretend success."""
        sys.argv = ["riks", "memory", "stats"]
        result = main()
        out = capsys.readouterr()
        combined = out.out + out.err
        assert result == 1
        assert "not implemented yet" in combined
        assert "Command executed successfully" not in combined

    def test_main_unknown_command_exits_with_error(self):
        """Test riks with unknown command."""
        sys.argv = ["riks", "unknown_cmd"]
        with pytest.raises(SystemExit):
            main()

    def test_main_memory_invalid_type(self):
        """Test riks memory with invalid type."""
        sys.argv = ["riks", "memory", "--type", "invalid", "add"]
        with pytest.raises(SystemExit):
            main()
