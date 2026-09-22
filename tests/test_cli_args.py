"""CLI → config mapping.

Regression suite for a bug that made *every* boolean flag a no-op when the CLI
was invoked normally: ``main()`` calls ``parse_args()`` (argv=None), and the
"was this flag passed?" set was only built from an explicit ``argv`` — so
``--no-preflight``, ``--reset-cache``, ``--metrics-samples``, ``-v`` and
``--no-ignore-eos`` were silently dropped.
"""

from __future__ import annotations

import sys

import pytest

from clawperf.cli import build_parser, parse_args


def _via_process_argv(monkeypatch, *flags):
    """Parse exactly the way main() does: sys.argv, argv=None."""
    monkeypatch.setattr(sys, "argv", ["clawperf", *flags])
    return parse_args()


def test_boolean_flag_from_process_argv(monkeypatch):
    cfg = _via_process_argv(monkeypatch, "--mode", "scenario", "--no-preflight")
    assert cfg.preflight is False


def test_boolean_flags_from_process_argv_all_kinds(monkeypatch):
    cfg = _via_process_argv(
        monkeypatch, "--mode", "scenario", "-v", "--reset-cache", "--metrics-samples",
    )
    assert cfg.verbose is True
    assert cfg.reset_cache is True
    assert cfg.metrics_samples is True


def test_boolean_flags_match_explicit_argv(monkeypatch):
    flags = ("--mode", "scenario", "-v", "--no-preflight", "--reset-cache")
    from_main = _via_process_argv(monkeypatch, *flags)
    from_explicit = parse_args(list(flags))
    assert from_main.preflight == from_explicit.preflight is False
    assert from_main.verbose == from_explicit.verbose is True
    assert from_main.reset_cache == from_explicit.reset_cache is True


def test_no_flag_keeps_defaults(monkeypatch):
    cfg = _via_process_argv(monkeypatch, "--mode", "scenario")
    assert cfg.preflight is True
    assert cfg.verbose is False
    assert cfg.reset_cache is False
    assert cfg.metrics_samples is False


def test_long_flag_with_equals_value(monkeypatch):
    cfg = _via_process_argv(
        monkeypatch, "--mode", "slo", "--slo=ttft.p99:1500", "--num-users=4",
    )
    assert cfg.slo_constraints == ("ttft.p99:1500",)
    assert cfg.num_users == 4


def test_short_flag_bundle(monkeypatch):
    parser = build_parser()
    # -vv is not defined (only -v), but the mapping must not crash on bundles.
    from clawperf.cli import _explicit_dests
    assert "verbose" in _explicit_dests(parser, ["-v"])
    assert "verbose" in _explicit_dests(parser, ["--verbose"])
    assert _explicit_dests(parser, ["-vv"]) == {"verbose"}


def test_explicit_value_equal_to_default_still_wins(monkeypatch):
    """--num-users 1 equals the default but must still beat an env var."""
    monkeypatch.setenv("CLAWPERF_NUM_USERS", "16")
    cfg = _via_process_argv(monkeypatch, "--mode", "scenario", "--num-users", "1")
    assert cfg.num_users == 1


def test_env_var_used_when_flag_absent(monkeypatch):
    monkeypatch.setenv("CLAWPERF_NUM_USERS", "16")
    cfg = _via_process_argv(monkeypatch, "--mode", "scenario")
    assert cfg.num_users == 16


def test_env_var_overrides_boolean_default(monkeypatch):
    monkeypatch.setenv("CLAWPERF_PREFLIGHT", "false")
    cfg = _via_process_argv(monkeypatch, "--mode", "scenario")
    assert cfg.preflight is False


def test_slo_flag_is_repeatable_and_comma_split(monkeypatch):
    cfg = _via_process_argv(
        monkeypatch, "--mode", "slo",
        "--slo", "ttft.p99:1500,tpot.avg:30", "--slo", "e2e.max:30000",
    )
    assert [c.label for c in cfg.effective_slo_constraints()] == [
        "ttft.p99<=1500ms", "tpot.avg<=30ms", "e2e.max<=30000ms",
    ]


def test_metrics_endpoint_is_repeatable(monkeypatch):
    cfg = _via_process_argv(
        monkeypatch, "--mode", "scenario",
        "--metrics-endpoint", "http://a:8000/metrics",
        "--metrics-endpoint", "http://b:8000/metrics",
    )
    assert len(cfg.metrics_endpoint) == 2


def test_malformed_slo_flag_is_a_config_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["clawperf", "--mode", "slo", "--slo", "ttft.p99"])
    with pytest.raises(ValueError, match="shell consumed"):
        parse_args()
