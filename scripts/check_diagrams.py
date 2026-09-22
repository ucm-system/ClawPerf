#!/usr/bin/env python3
"""Geometric self-check for the SVG figures in docs/assets/.

Implements the layout rules from the SVG diagramming conventions as executable
checks, so a diagram cannot silently ship with overlapping boxes, clipped text
or arrows that touch (or cut through) a box:

  1. every rect / text / arrow endpoint stays inside the viewBox
  2. solid boxes never overlap (dashed group containers may contain them)
  3. text fits inside its container box, horizontally and vertically centred
  4. arrows start/end outside boxes with a sane clearance
  5. straight arrow segments do not cut through a box

Usage: python3 scripts/check_diagrams.py docs/assets
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG = "{http://www.w3.org/2000/svg}"
VIEWBOX_MARGIN = 12          # tolerate a little slack against the 20-25px rule
TEXT_PAD = 4                 # min gap between text and its box edge
ARROW_MIN_GAP = 4            # start clearance (rule: 5px)
ARROW_MAX_GAP = 60           # a gap larger than this means the arrow is detached
V_CENTER_TOL = 4             # vertical centring tolerance, single-line box
V_BLOCK_TOL = 8              # tolerance for a title + body line block

# Latin char width by font size (from the conventions table); CJK = 1 em.
CHAR_WIDTH = {8: 4.5, 9: 5.0, 10: 5.5, 11: 6.0, 12: 7.0, 13: 7.5, 14: 8.0, 16: 9.0}
CJK_START = 0x2E80


def text_width(text: str, font_size: float) -> float:
    per = CHAR_WIDTH.get(int(round(font_size)), font_size * 0.6)
    width = 0.0
    for ch in text:
        width += font_size if ord(ch) >= CJK_START else per
    return width


class Box:
    def __init__(self, x, y, w, h, cls, elem_id):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.cls = cls
        self.id = elem_id

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def is_group(self):
        return self.cls == "group"

    def contains(self, other, pad=0.0):
        return (other.x >= self.x + pad and other.right <= self.right - pad
                and other.y >= self.y + pad and other.bottom <= self.bottom - pad)

    def overlaps(self, other, tol=0.5):
        return not (self.right <= other.x + tol or other.right <= self.x + tol
                    or self.bottom <= other.y + tol or other.bottom <= self.y + tol)

    def inside_point(self, px, py, pad=0.0):
        return (self.x + pad <= px <= self.right - pad
                and self.y + pad <= py <= self.bottom - pad)


class Label:
    def __init__(self, x, y, text, font_size, anchor):
        self.x, self.y, self.text = x, y, text
        self.font_size = font_size
        self.anchor = anchor
        self.width = text_width(text, font_size)

    @property
    def left(self):
        if self.anchor == "middle":
            return self.x - self.width / 2
        if self.anchor == "end":
            return self.x - self.width
        return self.x

    @property
    def right(self):
        return self.left + self.width

    @property
    def top(self):
        return self.y - self.font_size * 0.75

    @property
    def bottom(self):
        return self.y + self.font_size * 0.25


def parse(path: Path):
    tree = ET.parse(path)
    root = tree.getroot()
    vb = [float(v) for v in re.split(r"[,\s]+", root.get("viewBox", "0 0 0 0").strip())]
    # Font sizes usually live in the embedded <style> block, keyed by class.
    class_size: dict[str, float] = {}
    style_text = "".join(e.text or "" for e in root.iter(f"{SVG}style"))
    for cls, body in re.findall(r"\.([\w-]+)\s*\{([^}]*)\}", style_text):
        m = re.search(r"font-size:\s*([\d.]+)px", body)
        if m:
            class_size[cls] = float(m.group(1))

    boxes, labels, arrows = [], [], []
    for i, el in enumerate(root.iter()):
        tag = el.tag
        if tag == f"{SVG}rect":
            boxes.append(Box(float(el.get("x", 0)), float(el.get("y", 0)),
                             float(el.get("width", 0)), float(el.get("height", 0)),
                             el.get("class", ""), f"rect[{i}]"))
        elif tag == f"{SVG}text":
            raw = "".join(el.itertext()).strip()
            if not raw:
                continue
            size = el.get("font-size")
            if size:
                font_size = float(size)
            else:
                font_size = next((class_size[c] for c in el.get("class", "").split()
                                  if c in class_size), 12.0)
            labels.append(Label(float(el.get("x", 0)), float(el.get("y", 0)), raw,
                                font_size, el.get("text-anchor", "start")))
        elif tag == f"{SVG}path":
            if el.get("marker-end"):
                arrows.append((el.get("d", ""), f"path[{i}]"))
    return vb, boxes, labels, arrows


def path_points(d: str):
    """Endpoint and sampled points of an L/C/Q path (enough for our figures)."""
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    pts = []
    if d.strip().startswith("M") and len(nums) >= 4:
        x0, y0 = nums[0], nums[1]
        pts.append((x0, y0))
        rest = nums[2:]
        if "C" in d and len(rest) >= 6:
            for k in range(0, len(rest) - 5, 6):
                c1x, c1y, c2x, c2y, ex, ey = rest[k:k + 6]
                for t in (0.25, 0.5, 0.75, 1.0):
                    mt = 1 - t
                    bx = (mt ** 3) * x0 + 3 * (mt ** 2) * t * c1x + 3 * mt * (t ** 2) * c2x + (t ** 3) * ex
                    by = (mt ** 3) * y0 + 3 * (mt ** 2) * t * c1y + 3 * mt * (t ** 2) * c2y + (t ** 3) * ey
                    pts.append((bx, by))
                x0, y0 = ex, ey
        elif "Q" in d and len(rest) >= 4:
            for k in range(0, len(rest) - 3, 4):
                cx, cy, ex, ey = rest[k:k + 4]
                for t in (0.25, 0.5, 0.75, 1.0):
                    mt = 1 - t
                    bx = (mt ** 2) * x0 + 2 * mt * t * cx + (t ** 2) * ex
                    by = (mt ** 2) * y0 + 2 * mt * t * cy + (t ** 2) * ey
                    pts.append((bx, by))
                x0, y0 = ex, ey
        elif rest:
            for k in range(0, len(rest) - 1, 2):
                pts.append((rest[k], rest[k + 1]))
    return pts


def check(path: Path) -> list[str]:
    problems: list[str] = []
    vb, boxes, labels, arrows = parse(path)
    vw, vh = vb[2], vb[3]
    name = path.name

    def add(msg):
        problems.append(f"{name}: {msg}")

    # 1. inside the viewBox
    slack = VIEWBOX_MARGIN - 8
    for b in boxes:
        if (b.x < -slack or b.y < -slack
                or b.right > vw + slack or b.bottom > vh + slack):
            add(f"{b.id} ({b.cls or 'box'}) outside viewBox: "
                f"x={b.x} y={b.y} r={b.right} b={b.bottom} (viewBox {vw}x{vh})")
    for lb in labels:
        if lb.left < 4 or lb.right > vw - 4 or lb.top < 4 or lb.bottom > vh - 4:
            add(f"text {lb.text[:34]!r} outside viewBox: "
                f"l={lb.left:.0f} r={lb.right:.0f} t={lb.top:.0f} b={lb.bottom:.0f}")

    # 2. box/box overlap (groups may contain boxes; groups may not overlap each other)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if not a.overlaps(b):
                continue
            if a.is_group and a.contains(b):
                continue
            if b.is_group and b.contains(a):
                continue
            add(f"{a.id} ({a.cls or 'box'}) overlaps {b.id} ({b.cls or 'box'})")

    # 3. text inside its container box; centred (a single label) or the whole
    #    text block centred (title + body lines)
    solids = [b for b in boxes if not b.is_group]
    by_holder: dict[int, list[Label]] = {}
    for lb in labels:
        cx, cy = (lb.left + lb.right) / 2, (lb.top + lb.bottom) / 2
        holders = [b for b in solids if b.inside_point(cx, cy)]
        if not holders:
            continue
        holder = min(holders, key=lambda b: b.w * b.h)
        by_holder.setdefault(id(holder), []).append(lb)
        if lb.left < holder.x + TEXT_PAD or lb.right > holder.right - TEXT_PAD:
            add(f"text {lb.text[:34]!r} overflows its box horizontally "
                f"({lb.left:.0f}..{lb.right:.0f} vs {holder.x:.0f}..{holder.right:.0f})")
        if lb.top < holder.y + 2 or lb.bottom > holder.bottom - 2:
            add(f"text {lb.text[:34]!r} overflows its box vertically "
                f"({lb.top:.0f}..{lb.bottom:.0f} vs {holder.y:.0f}..{holder.bottom:.0f})")

    for holder in solids:
        group = by_holder.get(id(holder))
        if not group:
            continue
        box_center = holder.y + holder.h / 2
        if len(group) == 1:
            lb = group[0]
            off = ((lb.top + lb.bottom) / 2) - box_center
            if abs(off) > V_CENTER_TOL:
                add(f"text {lb.text[:34]!r} not vertically centred in its box (off by {off:.1f}px)")
        else:
            top = min(lb.top for lb in group)
            bottom = max(lb.bottom for lb in group)
            off = ((top + bottom) / 2) - box_center
            if abs(off) > V_BLOCK_TOL:
                add(f"text block in {holder.id} ({len(group)} lines) not centred "
                    f"(off by {off:.1f}px, want <= {V_BLOCK_TOL})")

    # 4/5. arrows: clearance at both ends, and no cutting through a box
    for d, pid in arrows:
        pts = path_points(d)
        if len(pts) < 2:
            add(f"{pid}: could not parse path {d!r}")
            continue
        for which, (px, py) in (("start", pts[0]), ("end", pts[-1])):
            for b in solids:
                if b.inside_point(px, py):
                    add(f"{pid} {which} ({px:.0f},{py:.0f}) is inside {b.id} ({b.cls or 'box'})")
                    break
            else:
                # nearest solid box edge distance
                best = None
                for b in solids:
                    dx = max(b.x - px, 0, px - b.right)
                    dy = max(b.y - py, 0, py - b.bottom)
                    dist = (dx * dx + dy * dy) ** 0.5
                    best = dist if best is None else min(best, dist)
                if best is not None and best > ARROW_MAX_GAP:
                    add(f"{pid} {which} is {best:.0f}px away from any box (arrow looks detached)")
                elif best is not None and best < ARROW_MIN_GAP:
                    add(f"{pid} {which} clearance only {best:.1f}px (want >= {ARROW_MIN_GAP})")
        # cutting through: sample interior points, ignore the two endpoint boxes
        inner = pts[1:-1]
        for b in solids:
            hits = sum(1 for px, py in inner if b.inside_point(px, py))
            if hits:
                add(f"{pid} passes through {b.id} ({b.cls or 'box'}) at {hits} sampled point(s)")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "docs/assets")
    svgs = sorted(root.glob("*.svg"))
    if not svgs:
        print(f"FAIL: no SVG files in {root}")
        return 1
    problems: list[str] = []
    for svg in svgs:
        try:
            problems.extend(check(svg))
        except ET.ParseError as exc:
            problems.append(f"{svg.name}: XML parse error: {exc}")
    if problems:
        print("diagram check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"diagram check OK: {len(svgs)} SVG figures, no overlap/overflow/clearance problems")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
