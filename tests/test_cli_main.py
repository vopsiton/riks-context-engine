"""Test CLI main module for coverage."""
import pytest
from io import StringIO


class TestCLI:
    """Tests for CLI main entry point."""

    def test_main_version_flag(self, capsys):
        """Test riks --version outputs version."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "--version"]
        result = main()
        captured = capsys.readouterr()
        assert "riks-context-engine" in captured.out or result == 0

    def test_main_no_args(self, capsys):
        """Test riks with no args shows help."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks"]
        result = main()
        captured = capsys.readouterr()
        # Returns 1, prints help
        assert result == 1

    def test_main_memory_stats(self, capsys):
        """Test riks memory stats."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "memory", "stats"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_memory_add(self, capsys):
        """Test riks memory add."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "memory", "add"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_memory_query(self, capsys):
        """Test riks memory query."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "memory", "query"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_context_stats(self, capsys):
        """Test riks context stats."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "context", "stats"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_context_prune(self, capsys):
        """Test riks context prune."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "context", "prune"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_context_clear(self, capsys):
        """Test riks context clear."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "context", "clear"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_task_command(self, capsys):
        """Test riks task <goal>."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "task", "test goal"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_reflection(self, capsys):
        """Test riks reflect --session."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "reflect", "--session", "test-session"]
        result = main()
        captured = capsys.readouterr()
        assert "Command executed" in captured.out or result == 0

    def test_main_unknown_command_exits_with_error(self, capsys):
        """Test riks with unknown command."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "unknown_cmd"]
        with pytest.raises(SystemExit):
            main()

    def test_main_memory_invalid_type(self, capsys):
        """Test riks memory with invalid type."""
        import sys
        from riks_context_engine.cli.main import main

        sys.argv = ["riks", "memory", "--type", "invalid", "add"]
        with pytest.raises(SystemExit):
            main()
