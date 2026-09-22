"""Tests for SLO mode: constraint parsing/evaluation, verdict logic,
sweep planning, config validation."""

from __future__ import annotations

import pytest

from clawperf.config import BenchmarkConfig, SloConstraint, parse_slo_constraint
from clawperf.runner import BenchmarkRunner


def _runner(**kw):
    defaults = dict(endpoint="http://x", model="m", mode="slo",
                    slo_ttft_ms=500, slo_tpot_ms=30)
    defaults.update(kw)
    return BenchmarkRunner(BenchmarkConfig(**defaults))


def _lists(ttft=(100,), tpot=(10,), e2e=(5000,)):
    return {"ttft": list(ttft), "tpot": list(tpot), "e2e": list(e2e)}


# ── Constraint parsing ────────────────────────────────────────────────────────

def test_parse_constraint_basic():
    c = parse_slo_constraint("ttft.p99<=1500")
    assert (c.metric, c.agg, c.op, c.value_ms) == ("ttft", "p99", "<=", 1500.0)
    assert c.label == "ttft.p99<=1500ms"
    assert c.column == "ttft.p99"


def test_parse_constraint_variants():
    assert parse_slo_constraint("TPOT.AVG >= 25.5").label == "tpot.avg>=25.5ms"
    assert parse_slo_constraint("e2e.max<30000ms").op == "<"
    assert parse_slo_constraint("ttft.p99.9<=100").agg == "p99.9"
    assert parse_slo_constraint("ttft.p95<=100").agg == "p95"


@pytest.mark.parametrize("bad", [
    "", "ttft<=1500", "foo.p99<=1", "ttft.p99~=1", "ttft.avg<=x",
    "ttft.p<=1", "ttft.p99<= ", "ttft..p99<=1",
])
def test_parse_constraint_invalid(bad):
    with pytest.raises(ValueError):
        parse_slo_constraint(bad)


# ── Aggregate computation ─────────────────────────────────────────────────────

def test_aggregate_avg_min_max():
    vals = [10, 40, 5, 30]
    assert SloConstraint("ttft", "avg", "<=", 1).aggregate(vals) == sum(vals) / 4
    assert SloConstraint("ttft", "min", "<=", 1).aggregate(vals) == 5
    assert SloConstraint("ttft", "max", "<=", 1).aggregate(vals) == 40


def test_aggregate_percentile_interpolation():
    # Linear interpolation — matches runner._percentile.
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert SloConstraint("ttft", "p50", "<=", 1).aggregate(vals) == 5.5
    assert SloConstraint("ttft", "p90", "<=", 1).aggregate(vals) == 9.1


def test_aggregate_empty_returns_none():
    assert SloConstraint("ttft", "p99", "<=", 1).aggregate([]) is None


def test_satisfied_by_ops():
    assert SloConstraint("ttft", "p99", "<=", 100).satisfied_by(100)
    assert not SloConstraint("ttft", "p99", "<", 100).satisfied_by(100)
    assert SloConstraint("ttft", "p99", ">=", 100).satisfied_by(100)
    assert SloConstraint("ttft", "p99", ">", 100).satisfied_by(101)
    assert not SloConstraint("ttft", "p99", "<=", 100).satisfied_by(None)


# ── Shell-safe syntax (the `--slo ttft.p99<=1500` bash trap) ──────────────────

@pytest.mark.parametrize("spec", [
    "ttft.p99<=1500",
    "ttft.p99:1500",
    "ttft.p99=1500",
    "ttft.p99:le:1500",
    "ttft.p99 le 1500",
    "ttft.p99<=1500ms",
    "ttft.p99 : 1500",
    "'ttft.p99:1500'",
])
def test_parse_constraint_shell_safe_equivalents(spec):
    c = parse_slo_constraint(spec)
    assert (c.metric, c.agg, c.op, c.value_ms) == ("ttft", "p99", "<=", 1500.0)


@pytest.mark.parametrize("spec,op", [
    ("ttft.p99:ge:1500", ">="),
    ("ttft.p99:gt:1500", ">"),
    ("ttft.p99:lt:1500", "<"),
    ("ttft.p99>=1500", ">="),
    ("ttft.p99>1500", ">"),
    ("ttft.p99<1500", "<"),
])
def test_parse_constraint_word_and_symbol_operators(spec, op):
    assert parse_slo_constraint(spec).op == op


def test_parse_constraint_bare_metric_explains_shell_trap():
    """`--slo ttft.p99<=10000` unquoted leaves ClawPerf with just 'ttft.p99'."""
    with pytest.raises(ValueError) as ei:
        parse_slo_constraint("ttft.p99")
    msg = str(ei.value)
    assert "shell consumed '<'" in msg
    assert "ttft.p99:1500" in msg  # the fix is in the message


def test_split_slo_specs_flattens_commas():
    from clawperf.config import split_slo_specs
    assert split_slo_specs(["ttft.p99<=1500,tpot.avg<=30", "e2e.max<=30000"]) == [
        "ttft.p99<=1500", "tpot.avg<=30", "e2e.max<=30000",
    ]
    assert split_slo_specs("a;b , c") == ["a", "b", "c"]
    assert split_slo_specs(None) == []


def test_config_accepts_comma_separated_list_value():
    cfg = BenchmarkConfig(mode="slo",
                          slo_constraints=["ttft.p99:1500,tpot.avg:30", "e2e.max:30000"])
    assert [c.label for c in cfg.effective_slo_constraints()] == [
        "ttft.p99<=1500ms", "tpot.avg<=30ms", "e2e.max<=30000ms",
    ]


def test_mean_is_an_alias_for_avg():
    assert parse_slo_constraint("tpot.mean:30").agg == "avg"


# ── Config-level: normalization + legacy conversion ───────────────────────────

def test_config_constraint_normalization_from_string():
    cfg = BenchmarkConfig(mode="slo", slo_constraints="ttft.p99<=1500, tpot.avg<=30")
    assert cfg.slo_constraints == ("ttft.p99<=1500", "tpot.avg<=30")


def test_config_constraint_normalization_from_list():
    cfg = BenchmarkConfig(mode="slo", slo_constraints=["e2e.max<=30000"])
    assert cfg.slo_constraints == ("e2e.max<=30000",)


def test_config_constraint_invalid_raises():
    with pytest.raises(ValueError, match="invalid SLO constraint"):
        BenchmarkConfig(mode="slo", slo_constraints=("ttft.bogus<=1",))


def test_effective_constraints_legacy():
    cfg = BenchmarkConfig(mode="slo", slo_ttft_ms=500, slo_tpot_ms=30, slo_percentile=0.99)
    assert [c.label for c in cfg.effective_slo_constraints()] == [
        "ttft.p99<=500ms", "tpot.p99<=30ms",
    ]


def test_effective_constraints_legacy_custom_percentile():
    cfg = BenchmarkConfig(mode="slo", slo_ttft_ms=500, slo_percentile=0.95)
    assert [c.label for c in cfg.effective_slo_constraints()] == ["ttft.p95<=500ms"]


def test_effective_constraints_explicit_wins():
    cfg = BenchmarkConfig(mode="slo", slo_ttft_ms=500, slo_constraints=("e2e.max<=30000",))
    assert [c.label for c in cfg.effective_slo_constraints()] == ["e2e.max<=30000ms"]


# ── Verdict ───────────────────────────────────────────────────────────────────

def test_slo_verdict_ok():
    r = _runner()
    assert r._slo_verdict(_lists(), 0.0, timed_out=False)["met"] is True


def test_slo_verdict_ttft_exceeds():
    r = _runner()
    assert r._slo_verdict(_lists(ttft=[600]), 0.0, timed_out=False)["met"] is False


def test_slo_verdict_tpot_exceeds():
    r = _runner()
    assert r._slo_verdict(_lists(tpot=[40]), 0.0, timed_out=False)["met"] is False


def test_slo_verdict_timeout():
    r = _runner()
    assert r._slo_verdict(_lists(), 0.0, timed_out=True)["met"] is False


def test_slo_verdict_none_metrics_fail():
    """If nothing could be measured (all errors), the SLO is not met."""
    r = _runner()
    v = r._slo_verdict({"ttft": [], "tpot": [], "e2e": []}, 1.0, timed_out=False)
    assert v["met"] is False


def test_slo_verdict_error_rate():
    r = _runner(slo_error_rate=0.05)
    # 3% errors OK
    assert r._slo_verdict(_lists(), 0.03, timed_out=False)["met"] is True
    # 10% errors fail
    assert r._slo_verdict(_lists(), 0.10, timed_out=False)["met"] is False


def test_slo_verdict_only_tpot_configured():
    """If only TPOT SLO is set, TTFT is unchecked."""
    r = _runner(slo_ttft_ms=None)
    assert r._slo_verdict(_lists(ttft=[99999]), 0.0, timed_out=False)["met"] is True


def test_slo_verdict_flexible_constraints():
    r = _runner(slo_constraints=("ttft.p99<=1500", "tpot.avg<=15", "e2e.max<=8000"))
    ok = _lists(ttft=[100, 200, 300], tpot=[10, 12, 14], e2e=[5000, 6000, 7000])
    v = r._slo_verdict(ok, 0.0, timed_out=False)
    assert v["met"] is True
    assert set(v["values"]) == {"ttft.p99<=1500ms", "tpot.avg<=15ms", "e2e.max<=8000ms"}

    # e2e.max blows the budget → FAIL, with the offending value reported.
    bad = _lists(ttft=[100, 200, 300], tpot=[10, 12, 14], e2e=[5000, 9000, 7000])
    v = r._slo_verdict(bad, 0.0, timed_out=False)
    assert v["met"] is False
    assert v["values"]["e2e.max<=8000ms"] == 9000


def test_slo_verdict_e2e_only():
    r = _runner(slo_constraints=("e2e.avg<=10000",))
    assert r._slo_verdict(_lists(e2e=[9000, 11000]), 0.0, timed_out=False)["met"] is True


def test_slo_verdict_upper_bound_ops():
    r = _runner(slo_constraints=("ttft.avg>=100",))  # degenerate but valid
    assert r._slo_verdict(_lists(ttft=[120]), 0.0, timed_out=False)["met"] is True
    assert r._slo_verdict(_lists(ttft=[50]), 0.0, timed_out=False)["met"] is False


# ── Next-N stepping ───────────────────────────────────────────────────────────

def test_next_n_geometric():
    r = _runner(slo_step_strategy="geometric")
    assert r._next_n(1) == 2
    assert r._next_n(4) == 8
    assert r._next_n(5) == 10  # max(n+1, n*2)


def test_next_n_linear():
    r = _runner(slo_step_strategy="linear")
    assert r._next_n(4) == 5
    assert r._next_n(10) == 11


# ── Label ─────────────────────────────────────────────────────────────────────

def test_slo_label_legacy():
    r = _runner(slo_error_rate=0.01)
    label = r._slo_label()
    assert "ttft.p99<=500ms" in label
    assert "tpot.p99<=30ms" in label
    assert "err<=1.0%" in label


def test_slo_label_flexible():
    r = _runner(slo_constraints=("ttft.p50<=800", "e2e.max<=30000"))
    assert r._slo_label() == "ttft.p50<=800ms, e2e.max<=30000ms"


# ── Config validation ─────────────────────────────────────────────────────────

def test_config_validate_slo_ok():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="slo",
                          slo_ttft_ms=500, slo_tpot_ms=30)
    assert cfg.validate() == []


def test_config_validate_slo_flexible_ok():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="slo",
                          slo_constraints=("ttft.p99<=1500",))
    assert cfg.validate() == []


def test_config_validate_slo_no_targets():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="slo")
    problems = cfg.validate()
    assert any("--slo" in p for p in problems)


def test_config_validate_slo_bad_range():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="slo",
                          slo_ttft_ms=500, slo_min_users=10, slo_max_users=5)
    problems = cfg.validate()
    assert any("slo_max_users" in p for p in problems)


def test_config_validate_slo_bad_percentile():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="slo",
                          slo_ttft_ms=500, slo_percentile=1.5)
    problems = cfg.validate()
    assert any("slo_percentile" in p for p in problems)
