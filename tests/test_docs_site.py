"""Documentation contract for the MkDocs site.

These are the guards behind the docs complaints that started this work: an
undocumented option ("what else besides --context-profile medium?"), a page that
was never translated, and screenshots where copyable text belongs.

`mkdocs build --strict` (CI) covers links and anchors; these cover the things a
build cannot know about.
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
CONFIG = ROOT / "mkdocs.yml"
I18N = DOCS / "i18n" / "params_zh.json"
SAMPLES = DOCS / "samples.json"

TOPICS = ["index", "quickstart", "configuration", "reference",
          "modes/scenario", "modes/hitrate", "modes/slo",
          "modes/agent", "modes/trace", "modes/record-replay"]
LANGS = ("en", "zh")
CJK = re.compile(r"[\u3400-\u9fff]")

# Flags that belong to other tools or to the subcommands, legitimately mentioned.
FOREIGN_FLAGS = {"--help", "--port", "--print", "--enable-auto-tool-choice",
                 "--tool-call-parser"}


def _actions():
    parser = build_parser()
    for group in parser._action_groups:
        for action in group._group_actions:
            if action.option_strings and action.dest != "help":
                yield group.title, action


def _page(topic: str, lang: str) -> str:
    return (DOCS / f"{topic}.{lang}.md").read_text(encoding="utf-8")


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

def test_generator_is_in_sync():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_site.py"), "--check"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_source_checker_passes():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_site.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("topic", TOPICS)
def test_every_topic_exists_in_both_languages(topic):
    for lang in LANGS:
        assert (DOCS / f"{topic}.{lang}.md").is_file(), f"{topic}.{lang}.md is missing"


@pytest.mark.parametrize("topic", TOPICS)
def test_translations_are_translated(topic):
    """A Chinese page with no Chinese in it is a copy-paste, not a translation."""
    zh = re.sub(r"^---.*?---", "", _page(topic, "zh"), flags=re.DOTALL)
    en = re.sub(r"^---.*?---", "", _page(topic, "en"), flags=re.DOTALL)
    assert CJK.search(zh), f"{topic}.zh.md contains no Chinese"
    assert not CJK.search(en), f"{topic}.en.md contains Chinese"


def test_mkdocs_config_is_pinned_to_mkdocs_1():
    """MkDocs 2.0 removes the plugin system; the build must not drift into it."""
    text = CONFIG.read_text(encoding="utf-8")
    assert "i18n:" in text and "docs_structure: suffix" in text
    assert "strict: true" in text
    extra = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "mkdocs>=1.6,<2" in extra


def test_pages_only_mention_real_flags():
    known = {opt for _, action in _actions() for opt in action.option_strings} | FOREIGN_FLAGS
    for topic in TOPICS:
        for lang in LANGS:
            # Strip Material's attribute lists ({ .md-button--primary }) first:
            # those are CSS classes, not command-line flags.
            body = re.sub(r"\{[^}]*\}", "", _page(topic, lang))
            mentioned = set(re.findall(r"--[a-z][a-z0-9-]+", body))
            unknown = sorted(m for m in mentioned if m not in known)
            assert unknown == [], f"{topic}.{lang}.md mentions non-existent options: {unknown}"


def test_examples_use_a_local_tokenizer():
    for topic in ("index", "quickstart", "reference", "modes/scenario"):
        assert "--tokenizer /mnt/model" in _page(topic, "en"), (
            f"{topic}.en.md has no local-tokenizer example")


def test_profiles_and_suites_are_documented():
    config = _page("configuration", "en")
    for name in PROFILE_ORDER:
        assert f"`{name}`" in config, f"profile {name} missing from configuration.en.md"
    for name in SUITES:
        assert f"`{name}`" in config, f"suite {name} missing from configuration.en.md"
    medium = CONTEXT_PROFILES["medium"]
    assert f"{medium['system_prefix_tokens']:,}" in config


def test_reference_lists_every_option():
    reference = _page("reference", "en")
    for _, action in _actions():
        for opt in action.option_strings:
            assert opt in reference, f"{opt} missing from reference.en.md"


# ── real output is embedded as text, not as screenshots ──────────────────────

def test_samples_are_real_captures():
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"]
    assert len(samples) >= 8
    for key, sample in samples.items():
        assert sample["command"], f"{key}: no command recorded"
        assert len(sample["output"].splitlines()) >= 4, f"{key}: suspiciously short output"
        assert "Traceback (most recent call last)" not in sample["output"], (
            f"{key}: captured a raw traceback instead of a clean message")


@pytest.mark.parametrize("topic,key", [
    ("modes/scenario", "scenario"), ("modes/hitrate", "hitrate"), ("modes/slo", "slo"),
    ("modes/agent", "agent"), ("modes/trace", "trace"), ("modes/record-replay", "replay"),
])
def test_mode_pages_embed_their_own_capture(topic, key):
    page = _page(topic, "en")
    assert "```console" in page, f"{topic}.en.md has no captured-output block"
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"][key]
    line = next(line for line in data["output"].splitlines() if len(line.strip()) > 12)
    assert line in page, f"{topic}.en.md does not embed the {key} capture"


def test_no_screenshots_or_html_left():
    assert not (DOCS / "shots").exists(), "docs/shots is back — use gen_samples.py instead"
    assert not list(DOCS.rglob("*.html")), "the hand-written HTML site is back"


def test_diagrams_are_referenced():
    used = "".join(_page(topic, lang) for topic in TOPICS for lang in LANGS)
    for svg in sorted((DOCS / "assets").glob("*.svg")):
        if svg.name in ("logo.svg", "favicon.svg"):
            continue
        assert svg.name in used, f"{svg.name} is not referenced by any page"
