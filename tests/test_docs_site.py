"""Documentation contract for the generated multi-page site.

These are the guards behind the docs complaints that started this work: an
undocumented option ("what else besides --context-profile medium?"), a landing
page with no index, and screenshots that should have been copyable code.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from clawperf.cli import build_parser
from clawperf.context_profiles import CONTEXT_PROFILES, PROFILE_ORDER, SUITES

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
I18N = DOCS / "i18n" / "params_zh.json"
SAMPLES = DOCS / "samples.json"

PAGES = [
    "index.html",
    "quickstart.html",
    "configuration.html",
    "reference.html",
    "modes/scenario.html",
    "modes/hitrate.html",
    "modes/slo.html",
    "modes/agent.html",
    "modes/trace.html",
    "modes/record-replay.html",
]

# Flags that belong to *other* tools or to the subcommands, legitimately mentioned.
FOREIGN_FLAGS = {"--help", "--port", "--print", "--enable-auto-tool-choice",
                 "--tool-call-parser"}


def _actions():
    parser = build_parser()
    for group in parser._action_groups:
        for action in group._group_actions:
            if action.option_strings and action.dest != "help":
                yield group.title, action


def _page(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def _body(rel: str) -> str:
    """The page without CSS/JS, so flag scraping does not pick up CSS variables."""
    text = _page(rel)
    text = re.sub(r"<style>.*?</style>", "", text, flags=re.DOTALL)
    return re.sub(r"<script>.*?</script>", "", text, flags=re.DOTALL)


# ── the CLI is documented ────────────────────────────────────────────────────

def test_every_option_has_help_text():
    missing = [a.option_strings[0] for _, a in _actions() if not (a.help or "").strip()]
    assert missing == [], f"undocumented options: {missing}"


def test_help_renders():
    """argparse runs help through %-formatting: a bare '%' crashes --help."""
    parser = build_parser()
    text = parser.format_help()
    assert "usage:" in text
    assert "%%" not in text, "help output shows a literal '%%'"
    assert "1%" in text


def test_every_option_is_translated():
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    missing = sorted({a.dest for _, a in _actions() if a.dest not in i18n})
    assert missing == [], f"missing zh translations for: {missing}"


def test_no_stale_translations():
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    dests = {a.dest for _, a in _actions()}
    stale = sorted(k for k in i18n if k not in dests and not k.startswith("_"))
    assert stale == [], f"translations for options that no longer exist: {stale}"


# ── the site is generated, and in sync ───────────────────────────────────────

@pytest.mark.parametrize("script", ["gen_site.py", "gen_samples.py"])
def test_generator_runs(script):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    # gen_samples --check re-runs benchmarks; only gen_site is expected to be
    # checked in the default test run.
    if script == "gen_samples.py":
        pytest.skip("samples are verified by the e2e CI job, not the unit suite")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_page_exists():
    for rel in PAGES:
        assert (DOCS / rel).is_file(), f"{rel} is missing — run python scripts/gen_site.py"


def test_every_page_has_a_left_index():
    for rel in PAGES:
        body = _page(rel)
        assert "details class='toc'" in body or 'class="toc"' in body, f"{rel}: no index"
        assert "<main>" in body, f"{rel}: content is not wrapped in <main>"
        # every mode is reachable from every page
        for slug in ("scenario", "hitrate", "slo", "agent", "trace", "record-replay"):
            assert f"modes/{slug}.html" in body, f"{rel}: does not link to {slug}"


def test_pages_only_mention_real_flags():
    known = {opt for _, action in _actions() for opt in action.option_strings} | FOREIGN_FLAGS
    for rel in PAGES:
        mentioned = set(re.findall(r"--[a-z][a-z0-9-]+", _body(rel)))
        unknown = sorted(m for m in mentioned if m not in known)
        assert unknown == [], f"{rel} mentions options that do not exist: {unknown}"


def test_examples_use_a_local_tokenizer():
    """The documented commands must use a local tokenizer directory.

    Flags are syntax-highlighted into spans, so compare against the tag-stripped
    text rather than the raw HTML.
    """
    for rel in ("index.html", "quickstart.html", "reference.html", "modes/scenario.html"):
        plain = re.sub(r"<[^>]+>", "", _page(rel))
        assert "--tokenizer /mnt/model" in plain, f"{rel} has no local-tokenizer example"


def test_profiles_and_suites_are_documented():
    config = _page("configuration.html")
    for name in PROFILE_ORDER:
        assert f">{name}</code>" in config, f"profile {name} missing from configuration.html"
    for name in SUITES:
        assert f">{name}</code>" in config, f"suite {name} missing from configuration.html"
    # the real token counts, not rounded prose
    medium = CONTEXT_PROFILES["medium"]
    assert f"{medium['system_prefix_tokens']:,}" in config


def test_reference_lists_every_option():
    reference = _page("reference.html")
    for _, action in _actions():
        for opt in action.option_strings:
            assert opt in reference, f"{opt} missing from reference.html"


# ── real output is embedded as code, not as screenshots ──────────────────────

def test_samples_are_real_captures():
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    samples = data["samples"]
    assert len(samples) >= 8
    for key, sample in samples.items():
        assert sample["command"], f"{key}: no command recorded"
        assert len(sample["output"].splitlines()) >= 4, f"{key}: suspiciously short output"
        assert "Traceback (most recent call last)" not in sample["output"], (
            f"{key}: captured a raw traceback instead of a clean message"
        )


def test_mode_pages_embed_their_own_capture():
    for slug, key in [("scenario", "scenario"), ("hitrate", "hitrate"), ("slo", "slo"),
                      ("agent", "agent"), ("trace", "trace"), ("record-replay", "replay")]:
        page = _page(f"modes/{slug}.html")
        assert "class='sample'" in page, f"modes/{slug}.html has no output block"
        data = json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"][key]
        first_meaningful = next(
            line for line in data["output"].splitlines() if len(line.strip()) > 12
        )
        assert first_meaningful in page, f"modes/{slug}.html does not embed the {key} capture"


def test_no_screenshots_left():
    """The screenshots were replaced by themed code blocks."""
    assert not (DOCS / "shots").exists(), "docs/shots is back — use gen_samples.py instead"
    for rel in PAGES:
        assert "shots/" not in _page(rel), f"{rel} still references a screenshot"


def test_diagrams_are_referenced():
    """Every committed SVG figure is used by a page."""
    used = "".join(_page(rel) for rel in PAGES)
    for svg in sorted((DOCS / "assets").glob("*.svg")):
        assert svg.name in used, f"{svg.name} is not referenced by any page"
