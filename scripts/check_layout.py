#!/usr/bin/env python3
"""Layout assertions for the docs site, measured in a real browser.

Nobody eyeballs every docs change, and "the headings are too small" or "there is
no index" are not things a tag-balance check can catch. This loads the pages in
headless Chrome at a desktop and a phone width and asserts the properties that
were actually asked for:

  * a left index exists, is sticky, sits left of the content, and is populated
  * on narrow screens it collapses into a disclosure instead of eating the page
  * headings are big enough to act as landmarks
  * nothing overflows horizontally at either width
  * every image actually loaded

Requires Chrome/Edge. CI runs it on ubuntu-latest, which ships Chrome.

Usage: python scripts/check_layout.py [--url file:///...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gen_shots import _browser_run, find_browser  # noqa: E402

PAGES = ["index.html", "reference.html"]

# Runs inside the page: collect the measurements as JSON in the document title.
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
      position: cs.position, display: cs.display, open: toc.open,
      links: toc.querySelectorAll('a').length,
      visibleLinks: Array.prototype.filter.call(toc.querySelectorAll('a'), function (a) {
        return a.getBoundingClientRect().height > 0;
      }).length,
      summaryDisplay: getComputedStyle(toc.querySelector('summary')).display
    };
  }
  out.headings = Array.prototype.map.call(
    document.querySelectorAll('h1, h2, h3.mode-title'),
    function (h) { return Math.round(parseFloat(getComputedStyle(h).fontSize)); }
  );
  var imgs = Array.prototype.slice.call(document.images);
  out.images = {
    total: imgs.length,
    broken: imgs.filter(function (i) { return i.complete && i.naturalWidth === 0; }).length,
    pending: imgs.filter(function (i) { return !i.complete; }).length
  };
  document.title = JSON.stringify(out);
})();
</script>
"""


def probe(browser: str, page: Path, width: int, height: int = 1000) -> dict:
    html = page.read_text(encoding="utf-8")
    if "</body>" in html:
        html = html.replace("</body>", PROBE + "</body>")
    else:
        html += PROBE
    # The probe page must sit next to the real one, otherwise its relative
    # asset URLs (shots/*.png, assets/*.svg) do not resolve.
    tmp = page.parent / f"__probe_{page.name}"
    tmp.write_text(html, encoding="utf-8", newline="\n")
    try:
        proc = _browser_run(browser, [
            f"--window-size={width},{height}",
            "--virtual-time-budget=4000",   # let lazy images finish loading
            "--dump-dom", tmp.as_uri(),
        ])
    finally:
        tmp.unlink(missing_ok=True)
    match = re.search(r"<title>(\{.*?\})</title>", proc.stdout, re.DOTALL)
    if not match:
        raise RuntimeError(f"{page.name} @{width}px: probe did not run ({proc.stdout[:200]})")
    return json.loads(unescape(match.group(1)))


def check_page(page: Path, browser: str) -> list[str]:
    problems: list[str] = []
    # A tall viewport so lazy-loaded screenshots below the fold actually load.
    desktop = probe(browser, page, 1440, height=7000)
    mobile = probe(browser, page, 390, height=4000)

    if desktop["overflow"] > 1:
        problems.append(f"{page.name}: horizontal overflow at 1440px ({desktop['overflow']}px)")
    if mobile["overflow"] > 1:
        problems.append(f"{page.name}: horizontal overflow at 390px ({mobile['overflow']}px)")

    if not desktop.get("headings"):
        problems.append(f"{page.name}: no headings found")
    else:
        small = [s for s in desktop["headings"] if s < 26]
        if small:
            problems.append(f"{page.name}: heading(s) below 26px: {small}")

    if desktop["images"]["broken"]:
        problems.append(
            f"{page.name}: {desktop['images']['broken']}/{desktop['images']['total']} "
            "images failed to load"
        )

    toc = desktop.get("toc")
    if page.name == "index.html":
        if not toc:
            problems.append("index.html: no left index (details.toc) found")
        else:
            if toc["position"] != "sticky":
                problems.append(f"index.html: index is not sticky (position: {toc['position']})")
            if toc["right"] > toc["mainLeft"]:
                problems.append("index.html: index is not to the left of the content")
            if not 180 <= toc["width"] <= 360:
                problems.append(f"index.html: index width {toc['width']}px is out of range")
            if toc["visibleLinks"] < 18:
                problems.append(f"index.html: only {toc['visibleLinks']} index links are visible")
            if toc["summaryDisplay"] != "none":
                problems.append("index.html: the index summary should be hidden on desktop")
            mobile_toc = mobile.get("toc")
            if not mobile_toc or mobile_toc["summaryDisplay"] == "none":
                problems.append("index.html: the index should collapse into a disclosure on mobile")
            elif mobile_toc["position"] != "static":
                problems.append("index.html: the collapsed index should not be sticky on mobile")
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
    for name in PAGES:
        page = docs / name
        if not page.is_file():
            problems.append(f"{name}: missing")
            continue
        problems.extend(check_page(page, browser))

    if problems:
        print("layout check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"layout check OK: {len(PAGES)} page(s) at 1440px and 390px")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
