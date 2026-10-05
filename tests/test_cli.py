"""
Unit tests for the VerbaClear CLI interface.
Validates subcommands: devices, diagnose, and argument parsing.
"""

from unittest.mock import patch
import pytest

from src.interfaces.cli import list_audio_devices, main, run_diagnostics


def test_cli_list_devices(capsys):
    """Verifies that 'verbaclear devices' runs without exceptions and prints device table."""
    list_audio_devices()
    captured = capsys.readouterr()
    assert "Detected Hardware Audio Input Interfaces" in captured.out


def test_cli_run_diagnostics(capsys):
    """Verifies that 'verbaclear diagnose' checks all local components."""
    run_diagnostics()
    captured = capsys.readouterr()
    assert "Running VerbaClear Appliance Self-Diagnostics" in captured.out
    assert "All diagnostic checks passed." in captured.out


def test_cli_main_help_and_subcommands(capsys):
    """Verifies that main CLI parser handles arguments correctly."""
    with patch("sys.argv", ["verbaclear", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Operational Subcommands" in captured.out
