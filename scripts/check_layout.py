#!/usr/bin/env python3
"""Layout assertions for the docs site, measured in a real browser.

Nobody eyeballs every docs change, and "the headings are too small" or "there is
no index" are not things a tag-balance check can catch. This loads every page in
headless Chrome at a desktop and a phone width and asserts the properties that
were actually asked for:

  * a left index exists on every page, is sticky, sits left of the content,
    and is populated
  * on narrow screens it collapses into a disclosure instead of eating the page
  * headings are big enough to act as landmarks
  * nothing overflows horizontally at either width
  * every image (and every diagram) actually loaded

Requires Chrome/Edge. CI runs it on ubuntu-latest, which ships Chrome.

Usage: python scripts/check_layout.py [--docs docs]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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

PROBE = """
<script>
(function () {
  var out = {vw: window.innerWidth, overflow: document.documentElement.scrollWidth - window.innerWidth};
  var toc = document.querySelector('details.toc');
  var main = document.querySelector('.layout > main');
  if (toc && main) {
    var tr = toc.getBoundingClientRect(), mr = main.getBoundingClientRect();
    var cs = getComputedStyle(toc);
    out.toc = {
      left: Math.round(tr.left), width: Math.round(tr.width),
      right: Math.round(tr.right), mainLeft: Math.round(mr.left),
      position: cs.position, open: toc.open,
      visibleLinks: Array.prototype.filter.call(toc.querySelectorAll('a'), function (a) {
        return a.getBoundingClientRect().height > 0;
      }).length,
      summaryDisplay: getComputedStyle(toc.querySelector('summary')).display
    };
  }
  out.headings = Array.prototype.map.call(
    document.querySelectorAll('h1, h2'),
    function (h) { return Math.round(parseFloat(getComputedStyle(h).fontSize)); }
  );
  var imgs = Array.prototype.slice.call(document.images);
  out.images = {
    total: imgs.length,
    broken: imgs.filter(function (i) { return i.complete && i.naturalWidth === 0; }).length
  };
  out.codeBlocks = document.querySelectorAll('.sample pre').length;
  document.title = JSON.stringify(out);
})();
</script>
"""


def find_browser() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def browser_run(browser: str, args: list[str]) -> subprocess.CompletedProcess:
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions"]
    proc = subprocess.run(base + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    if proc.returncode != 0 and "--headless=new" in base:
        base[1] = "--headless"
        proc = subprocess.run(base + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180)
    return proc


def probe(browser: str, page: Path, width: int, height: int) -> dict:
    text = page.read_text(encoding="utf-8")
    text = text.replace("</body>", PROBE + "</body>") if "</body>" in text else text + PROBE
    # The probe must sit next to the real page so relative asset URLs resolve.
    tmp = page.parent / f"__probe_{page.name}"
    tmp.write_text(text, encoding="utf-8", newline="\n")
    try:
        proc = browser_run(browser, [f"--window-size={width},{height}",
                                     "--virtual-time-budget=4000", "--dump-dom", tmp.as_uri()])
    finally:
        tmp.unlink(missing_ok=True)
    match = re.search(r"<title>(\{.*?\})</title>", proc.stdout, re.DOTALL)
    if not match:
        raise RuntimeError(f"{page.name} @{width}px: probe did not run ({proc.stdout[:200]})")
    return json.loads(unescape(match.group(1)))


def check_page(page: Path, browser: str, rel: str) -> list[str]:
    problems: list[str] = []
    desktop = probe(browser, page, 1440, 7000)   # tall: let lazy diagrams load
    mobile = probe(browser, page, 390, 4000)

    if desktop["overflow"] > 1:
        problems.append(f"{rel}: horizontal overflow at 1440px ({desktop['overflow']}px)")
    if mobile["overflow"] > 1:
        problems.append(f"{rel}: horizontal overflow at 390px ({mobile['overflow']}px)")

    headings = desktop.get("headings") or []
    small = [s for s in headings if s < 26]
    if not headings:
        problems.append(f"{rel}: no headings found")
    elif small:
        problems.append(f"{rel}: heading(s) below 26px: {small}")

    images = desktop.get("images") or {}
    if images.get("broken"):
        problems.append(f"{rel}: {images['broken']}/{images.get('total')} images failed to load")

    toc = desktop.get("toc")
    if not toc:
        problems.append(f"{rel}: no left index (details.toc) found")
        return problems
    if toc["position"] != "sticky":
        problems.append(f"{rel}: index is not sticky (position: {toc['position']})")
    if toc["right"] > toc["mainLeft"]:
        problems.append(f"{rel}: index is not to the left of the content")
    if not 180 <= toc["width"] <= 360:
        problems.append(f"{rel}: index width {toc['width']}px is out of range")
    if toc["visibleLinks"] < 12:
        problems.append(f"{rel}: only {toc['visibleLinks']} index links are visible")
    if toc["summaryDisplay"] != "none":
        problems.append(f"{rel}: the index summary should be hidden on desktop")
    mobile_toc = mobile.get("toc")
    if not mobile_toc or mobile_toc["summaryDisplay"] == "none":
        problems.append(f"{rel}: the index should collapse into a disclosure on mobile")
    elif mobile_toc["position"] != "static":
        problems.append(f"{rel}: the collapsed index should not be sticky on mobile")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", default=str(ROOT / "docs"), help="site directory")
    args = ap.parse_args(argv[1:])

    browser = find_browser()
    if not browser:
        print("SKIP: no Chrome/Edge found — cannot check the layout")
        return 0

    docs = Path(args.docs)
    problems: list[str] = []
    for rel in PAGES:
        page = docs / rel
        if not page.is_file():
            problems.append(f"{rel}: missing")
            continue
        problems.extend(check_page(page, browser, rel))

    if problems:
        print("layout check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"layout check OK: {len(PAGES)} pages at 1440px and 390px")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
