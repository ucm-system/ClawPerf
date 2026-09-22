"""Documentation contract: every CLI option must be documented, and the
generated reference page must be in sync with the code.

These are cheap guards against the exact complaint that started this file:
``--context-profile medium`` was usable but the other profiles were nowhere
described, and a third of the flags had no help text at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from clawperf.cli import build_parser
from clawperf.context_profiles import CONTEXT_PROFILES, PROFILE_ORDER, SUITES

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "reference.html"
I18N = ROOT / "docs" / "i18n" / "params_zh.json"


def _actions():
    parser = build_parser()
    for group in parser._action_groups:
        for action in group._group_actions:
            if action.option_strings and action.dest != "help":
                yield group.title, action


def test_every_option_has_help_text():
    missing = [a.option_strings[0] for _, a in _actions() if not (a.help or "").strip()]
    assert missing == [], f"undocumented options: {missing}"


def test_help_text_is_a_full_sentence():
    """A bare stub like 'Total requests.' is worse than nothing in the site."""
    too_short = [
        a.option_strings[0] for _, a in _actions() if len((a.help or "").strip()) < 15
    ]
    assert too_short == [], f"help text too terse: {too_short}"


def test_every_option_is_translated():
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    missing = sorted({a.dest for _, a in _actions() if a.dest not in i18n})
    assert missing == [], f"missing zh translations for: {missing}"


def test_no_stale_translations():
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    dests = {a.dest for _, a in _actions()}
    stale = sorted(k for k in i18n if k not in dests and not k.startswith("_"))
    assert stale == [], f"translations for options that no longer exist: {stale}"


def test_profiles_are_all_reachable_by_name():
    from clawperf.context_profiles import get_profile
    assert PROFILE_ORDER == list(CONTEXT_PROFILES)
    for name in PROFILE_ORDER:
        assert get_profile(name.upper())["system_prefix_tokens"] > 0
    with pytest.raises(ValueError, match="Unknown context profile"):
        get_profile("huge")


def test_suites_reference_real_profiles():
    from clawperf.context_profiles import REALISTIC_PROFILES
    for name, suite in SUITES.items():
        profiles = suite["profiles"]
        if profiles == "realistic":
            profiles = REALISTIC_PROFILES
        elif isinstance(profiles, str):
            profiles = [profiles]
        for profile in profiles:
            assert profile in CONTEXT_PROFILES, f"suite {name} uses unknown profile {profile}"
        assert suite["users"], f"suite {name} has no user counts"


@pytest.mark.skipif(not REFERENCE.is_file(), reason="reference page not generated")
def test_generated_reference_page_is_in_sync():
    """`python scripts/gen_reference.py --check` must pass (CI enforces it too)."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_reference.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(not REFERENCE.is_file(), reason="reference page not generated")
def test_reference_page_documents_every_profile_and_suite():
    html = REFERENCE.read_text(encoding="utf-8")
    for profile in PROFILE_ORDER:
        assert f'<code class="inline">{profile}</code>' in html, profile
    for suite in SUITES:
        assert f'<code class="inline">{suite}</code>' in html, suite
    # Every documented option spelling shows up on the page.
    for _, action in _actions():
        for opt in action.option_strings:
            assert opt in html, f"{opt} missing from reference.html"


def test_default_column_tells_the_truth():
    """A flag that defaults to *on* must not be rendered as 'off'."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from gen_reference import collect_groups, default_text

    def long_opt(row) -> str:
        return next(o for o in row["opts"] if o.startswith("--"))

    rendered = {
        long_opt(row): default_text(row)
        for _, rows in collect_groups() for row in rows
    }
    assert rendered["--ignore-eos"] == "on"        # store_true, default True
    assert rendered["--prefill"] == "on"
    assert rendered["--slo-step-reset-cache"] == "on"
    assert rendered["--no-preflight"] == "on"      # store_false, default True
    assert rendered["--metrics-samples"] == "off"
    assert rendered["--reset-cache"] == "off"
    assert rendered["--verbose"] == "off"
    assert rendered["--slo"] == "—"                # repeatable, unset by default
    assert rendered["--metrics-endpoint"] == "—"
    assert rendered["--num-requests"] == "100"
