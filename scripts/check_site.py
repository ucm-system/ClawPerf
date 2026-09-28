#!/usr/bin/env python3
"""Validate the Markdown sources of the docs site.

These are the checks that must hold *before* `mkdocs build --strict` (which
catches broken links and anchors on its own, and is run in CI). They cover what
a build cannot know about:

  * every page exists in every language — a missing translation silently falls
    back to English, which is how a translated site quietly becomes English
  * a Chinese page actually contains Chinese, and an English page does not — a
    copy-paste that was never translated is invisible otherwise
  * every link and image in every page resolves to a real file
  * every committed SVG diagram is used by some page
  * no leftovers from the previous hand-written HTML site

Usage: python scripts/check_site.py [--docs docs]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LANGS = ("en", "zh")
PAGES = ["index", "quickstart", "configuration", "reference",
         "modes/scenario", "modes/hitrate", "modes/slo",
         "modes/agent", "modes/trace", "modes/record-replay"]

CJK = re.compile(r"[\u3400-\u9fff]")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")
NAV_ENTRY = re.compile(r"^\s*-?\s*[^:]+:\s*([\w/\-.]+\.md)\s*$", re.MULTILINE)


def page_path(docs: Path, name: str, lang: str) -> Path:
    return docs / f"{name}.{lang}.md"


def check_links(docs: Path, path: Path) -> list:
    problems = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
            continue
        file_part = target.split("#")[0]
        if not file_part:
            continue
        if not (path.parent / file_part).resolve().is_file():
            problems.append(f"{path.relative_to(docs)}: link target {target!r} does not exist")
    return problems


def check_language(docs: Path, path: Path, lang: str) -> list:
    body = re.sub(r"^---.*?---", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    has_cjk = bool(CJK.search(body))
    rel = path.relative_to(docs)
    if lang == "zh" and not has_cjk:
        return [f"{rel}: Chinese page contains no Chinese — was it translated?"]
    if lang == "en" and has_cjk:
        return [f"{rel}: English page contains Chinese characters"]
    return []


def check_mkdocs(conf: Path, docs: Path) -> list:
    problems = []
    text = conf.read_text(encoding="utf-8")
    for target in NAV_ENTRY.findall(text):
        stem = target[:-3]
        if stem == "E2E_TEST_REPORT":
            if not (docs / "E2E_TEST_REPORT.md").is_file():
                problems.append(f"mkdocs.yml: nav entry {target} does not exist")
            continue
        for lang in LANGS:
            if not (docs / f"{stem}.{lang}.md").is_file():
                problems.append(f"mkdocs.yml: nav entry {target} has no {lang} page")
    for required in ("strict: true", "content.code.copy", "i18n:", "docs_structure: suffix"):
        if required not in text:
            problems.append(f"mkdocs.yml: missing {required!r}")
    return problems


def check_no_legacy(docs: Path) -> list:
    problems = [f"{p.relative_to(docs)}: leftover from the hand-written site"
                for p in sorted(docs.rglob("*.html"))]
    problems += [f"{p.relative_to(docs)}: a screenshot, in a text site"
                 for p in sorted(docs.rglob("*.png"))]
    if (docs / "shots").exists():
        problems.append("docs/shots: the screenshot directory is back")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", default=str(ROOT / "docs"))
    ap.add_argument("--config", default=str(ROOT / "mkdocs.yml"))
    args = ap.parse_args(argv[1:])
    docs = Path(args.docs)

    problems: list = []
    for name in PAGES:
        for lang in LANGS:
            path = page_path(docs, name, lang)
            if not path.is_file():
                problems.append(f"{path.relative_to(docs)}: missing — run scripts/gen_site.py")
                continue
            problems += check_links(docs, path)
            problems += check_language(docs, path, lang)

    used = "\n".join(page_path(docs, n, lang).read_text(encoding="utf-8")
                     for n in PAGES for lang in LANGS if page_path(docs, n, lang).is_file())
    svgs = sorted((docs / "assets").glob("*.svg"))
    for svg in svgs:
        if svg.name in ("logo.svg", "favicon.svg"):
            continue
        if svg.name not in used:
            problems.append(f"assets/{svg.name}: not referenced by any page")

    problems += check_mkdocs(Path(args.config), docs)
    problems += check_no_legacy(docs)

    if problems:
        print("site check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"site check OK: {len(PAGES) * len(LANGS)} Markdown pages "
          f"({len(PAGES)} topics x {len(LANGS)} languages), {len(svgs)} SVG figures")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
