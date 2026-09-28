#!/usr/bin/env python3
"""Measure the *built* site in a real browser.

`mkdocs build --strict` proves the Markdown is well-formed and every link
resolves. It cannot prove the theme actually rendered: that the nav is there,
that the language switcher points at the real sibling pages, that JavaScript
produced the code-copy buttons, that the diagrams loaded, or that nothing
overflows on a phone. That is what this script does.

Measurements are taken on `load`, not during parsing, so client-side behaviour
(Material's bundle, our copy buttons) is included.

It builds nothing — run `mkdocs build` first (CI does both).

Usage: python scripts/check_layout.py [--site site] [--config mkdocs.yml]
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
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

# (path relative to the built site, language)
PAGES = [
    ("index.html", "en"),
    ("quickstart/index.html", "en"),
    ("reference/index.html", "en"),
    ("modes/slo/index.html", "en"),
    ("modes/record-replay/index.html", "en"),
    ("zh/index.html", "zh"),
    ("zh/quickstart/index.html", "zh"),
    ("zh/reference/index.html", "zh"),
    ("zh/modes/slo/index.html", "zh"),
    ("zh/modes/record-replay/index.html", "zh"),
]

PROBE = """
<script>
(function () {
  function measure() {
    var out = {vw: window.innerWidth};
    out.overflow = document.documentElement.scrollWidth - window.innerWidth;
    var nav = document.querySelector('.md-nav--primary');
    var links = nav ? Array.prototype.filter.call(nav.querySelectorAll('a.md-nav__link'),
      function (a) { return a.getBoundingClientRect().height > 0; }) : [];
    out.nav = {
      present: !!nav,
      visibleLinks: links.length,
      firstLabel: links.length ? links[0].innerText.trim().slice(0, 24) : null
    };
    out.langSwitcher = Array.prototype.map.call(document.querySelectorAll('.md-select__link'),
      function (a) { return a.getAttribute('href'); });
    out.hasSearch = !!document.querySelector('[data-md-component="search"]');
    out.hasPalette = !!document.querySelector('[data-md-component="palette"]');
    var h1 = document.querySelector('.md-content h1');
    out.h1 = h1 ? Math.round(parseFloat(getComputedStyle(h1).fontSize)) : null;
    var imgs = Array.prototype.slice.call(document.images);
    out.images = {
      total: imgs.length,
      broken: imgs.filter(function (i) { return i.complete && i.naturalWidth === 0; }).length,
      remote: imgs.filter(function (i) {
        return /^https?:/i.test(i.getAttribute('src') || '');
      }).map(function (i) { return i.getAttribute('src'); })
    };
    // Canonical/alternate links are absolute on purpose; anything the browser
    // must *fetch* (stylesheets, scripts, fonts, icons) must be local.
    out.remoteAssets = Array.prototype.slice.call(
      document.querySelectorAll('script[src^="http"], link[rel="stylesheet"][href^="http"],'
        + ' link[rel="icon"][href^="http"], link[rel="preconnect"][href^="http"],'
        + ' link[rel="preload"][href^="http"]')
    ).map(function (e) { return e.getAttribute('src') || e.getAttribute('href'); });
    out.code = {
      blocks: document.querySelectorAll('.md-content .highlight').length,
      copyButtons: document.querySelectorAll('.md-content .clawperf-copy, .md-content .md-clipboard,'
        + ' .md-content .md-code__button, .md-content button[title*="opy"]').length,
      titles: document.querySelectorAll('.md-content .filename, .md-content .md-code__title').length
    };
    out.tables = document.querySelectorAll('.md-typeset table').length;
    out.admonitions = document.querySelectorAll('.admonition').length;
    out.tabs = document.querySelectorAll('.tabbed-set').length;
    out.glightbox = document.querySelectorAll('.glightbox').length;
    document.title = JSON.stringify(out);
  }
  if (document.readyState === 'complete') { measure(); }
  else { window.addEventListener('load', measure); }
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


def browser_run(browser: str, args: list) -> subprocess.CompletedProcess:
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions"]
    proc = subprocess.run(base + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    if proc.returncode != 0:
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
                                     "--virtual-time-budget=6000", "--dump-dom", tmp.as_uri()])
    finally:
        tmp.unlink(missing_ok=True)
    match = re.search(r"<title>(\{.*?\})</title>", proc.stdout, re.DOTALL)
    if not match:
        raise RuntimeError(f"{page.name} @{width}px: probe did not run")
    return json.loads(unescape(match.group(1)))


CJK = re.compile(r"[\u3400-\u9fff]")


def resolve_href(page: Path, href: str, site: Path, base: str) -> Path | None:
    """Resolve a switcher href, which may be root-absolute or page-relative."""
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        href = urlparse(href).path
    if href.startswith("/"):
        if base and href.startswith(base):
            href = href[len(base):]
        else:
            href = href.lstrip("/")
        return (site / href).resolve()
    return (page.parent / href).resolve()


def check_page(page: Path, browser: str, rel: str, lang: str, site: Path, base: str) -> list:
    problems: list = []
    desktop = probe(browser, page, 1440, 4000)
    mobile = probe(browser, page, 390, 2400)

    for label, data in (("1440px", desktop), ("390px", mobile)):
        if data["overflow"] > 1:
            problems.append(f"{rel}: horizontal overflow at {label} ({data['overflow']}px)")
        if data["images"]["broken"]:
            problems.append(f"{rel}: {data['images']['broken']}/{data['images']['total']} "
                            f"images failed to load at {label}")
        # A docs site that calls out to a CDN on every page view is both a
        # privacy leak and a broken-image risk (an external twemoji once rendered
        # inside a documented flag). Everything must be local.
        if data["images"]["remote"]:
            problems.append(f"{rel}: remotely hosted image(s) at {label}: "
                            f"{data['images']['remote'][:3]}")
        if data["remoteAssets"]:
            problems.append(f"{rel}: remotely hosted script/stylesheet at {label}: "
                            f"{data['remoteAssets'][:3]}")

    nav = desktop["nav"]
    if not nav["present"]:
        problems.append(f"{rel}: no primary navigation rendered")
    elif nav["visibleLinks"] < 8:
        problems.append(f"{rel}: only {nav['visibleLinks']} nav links are visible")
    if lang == "zh" and nav["firstLabel"] and not CJK.search(nav["firstLabel"]):
        problems.append(f"{rel}: nav is not translated (first entry {nav['firstLabel']!r})")

    if not desktop["hasSearch"]:
        problems.append(f"{rel}: the search component is missing")
    if not desktop["hasPalette"]:
        problems.append(f"{rel}: the light/dark switch is missing")
    if desktop["h1"] is None:
        problems.append(f"{rel}: no H1 in the content")
    elif desktop["h1"] < 26:
        problems.append(f"{rel}: H1 is only {desktop['h1']}px")

    # The switcher must offer the equivalent page in the other language, and
    # that target must exist in the build.
    resolved = [resolve_href(page, href, site, base) for href in desktop["langSwitcher"]]
    existing = [p for p in resolved if p and p.is_dir()]
    zh_root = (site / "zh").resolve()
    if lang == "en":
        wanted = [p for p in existing if p == zh_root or zh_root in p.parents]
    else:
        wanted = [p for p in existing if (p == site.resolve() or site.resolve() in p.parents)
                  and zh_root not in p.parents and p != zh_root]
    if not wanted:
        problems.append(f"{rel}: the language switcher offers no existing "
                        f"{'zh' if lang == 'en' else 'en'} page "
                        f"(hrefs {desktop['langSwitcher']}, resolved {resolved})")

    code = desktop["code"]
    if code["blocks"] and not code["copyButtons"]:
        problems.append(f"{rel}: {code['blocks']} code blocks but no copy button")
    if code["blocks"] and code["copyButtons"] < code["blocks"]:
        problems.append(f"{rel}: only {code['copyButtons']} copy buttons for {code['blocks']} blocks")

    if mobile["vw"] < 700 and mobile["nav"]["visibleLinks"] > 40:
        problems.append(f"{rel}: the nav is not collapsed on mobile "
                        f"({mobile['nav']['visibleLinks']} links)")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--config", default=str(ROOT / "mkdocs.yml"))
    args = ap.parse_args(argv[1:])

    browser = find_browser()
    if not browser:
        print("SKIP: no Chrome/Edge found — cannot measure the layout")
        return 0

    site = Path(args.site).resolve()
    if not (site / "index.html").is_file():
        print("FAIL: no built site — run `mkdocs build` first")
        return 1
    base = urlparse(re.search(r"^site_url:\s*(\S+)", Path(args.config).read_text(encoding="utf-8"),
                              re.MULTILINE).group(1)).path

    problems: list = []
    for rel, lang in PAGES:
        page = site / rel
        if not page.is_file():
            problems.append(f"{rel}: missing from the build")
            continue
        problems.extend(check_page(page, browser, rel, lang, site, base))

    if problems:
        print("layout check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"layout check OK: {len(PAGES)} built pages measured at 1440px and 390px")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
