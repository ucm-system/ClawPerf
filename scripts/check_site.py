#!/usr/bin/env python3
"""Sanity-check the GitHub Pages site before it is deployed.

Three checks, all stdlib-only so it runs anywhere:

1. every relative ``src``/``href`` in the HTML resolves to a real file
2. the HTML has balanced tags (catches an unclosed <div> that would silently
   break the layout of everything after it)
3. every SVG under ``docs/assets`` parses as XML (an unescaped ``&`` makes an
   SVG render as a broken image, and nothing else would notice)

Usage: python3 scripts/check_site.py docs
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

# HTML void elements never need a closing tag.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# Attributes whose values point at local files.
URL_ATTRS = ("src", "href")


class SiteParser(HTMLParser):
    """Collect local asset references and verify tag balance."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.problems: list[str] = []
        self.refs: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        for name, value in attrs:
            if name in URL_ATTRS and value:
                self.refs.append((value, line))
        if tag not in VOID:
            self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        for name, value in attrs:
            if name in URL_ATTRS and value:
                self.refs.append((value, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        line = self.getpos()[0]
        if not self.stack:
            self.problems.append(f"line {line}: </{tag}> with nothing open")
            return
        open_tag, open_line = self.stack.pop()
        if open_tag != tag:
            self.problems.append(
                f"line {line}: </{tag}> closes <{open_tag}> opened on line {open_line}"
            )


def check_html(path: Path, root: Path) -> list[str]:
    problems: list[str] = []
    parser = SiteParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()

    problems.extend(f"{path.name}: {p}" for p in parser.problems)
    if parser.stack:
        leftovers = ", ".join(f"<{t}> (line {ln})" for t, ln in parser.stack)
        problems.append(f"{path.name}: unclosed tags at end of file: {leftovers}")

    external = ("http://", "https://", "//", "#", "mailto:", "data:", "tel:")
    for value, line in parser.refs:
        if value.startswith(external) or value.startswith("{{"):
            continue
        target = (path.parent / value.split("#")[0].split("?")[0]).resolve()
        if not target.exists():
            problems.append(f"{path.name}: line {line}: missing asset {value!r}")
        elif root not in target.parents and target != root:
            problems.append(f"{path.name}: line {line}: asset {value!r} escapes the site root")
    return problems


def check_svgs(assets: Path) -> list[str]:
    problems: list[str] = []
    svgs = sorted(assets.glob("*.svg"))
    if not svgs:
        problems.append(f"{assets}: no SVG figures found")
    for svg in svgs:
        try:
            ET.parse(svg)
        except ET.ParseError as exc:
            problems.append(f"{svg.name}: XML parse error: {exc}")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "docs").resolve()
    index = root / "index.html"
    if not index.is_file():
        print(f"FAIL: {index} not found")
        return 1

    problems = check_html(index, root) + check_svgs(root / "assets")
    if problems:
        print("site check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"site check OK: {index.name} + {len(list((root / 'assets').glob('*.svg')))} SVG figures")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
