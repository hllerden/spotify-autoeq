#!/usr/bin/env python3
"""Regenerate the README visuals.

    PYTHONPATH=src python3 docs/make_assets.py

* docs/assets/profiles.svg - the ten-band curve of every profile, drawn from
  the curves defined in the code.
* docs/assets/demo.gif     - terminal replay rendered from docs/assets/session.log,
  a log captured from a real session; timestamps set the pacing (gaps are
  shortened) and only the timestamp prefix and package name are reformatted.
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
sys.path.insert(0, str(ROOT / "src"))

from spotify_autoeq.modules.eq_controller import BAND_FREQUENCIES_HZ, builtin_profiles  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

BG, FG, DIM = (30, 30, 46), (205, 214, 244), (127, 132, 156)
GREEN, BLUE, ORANGE, BAR = (166, 227, 161), (137, 180, 250), (250, 179, 135), (24, 24, 37)


# --- profile curves -------------------------------------------------------

def profiles_svg() -> str:
    profiles = list(builtin_profiles().values())
    cols, cw, ch, pad = 4, 250, 150, 16
    rows = (len(profiles) + cols - 1) // cols
    width, height = cols * cw + pad, rows * ch + pad + 34
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="DejaVu Sans, Arial, sans-serif">',
           f'<rect width="{width}" height="{height}" rx="10" fill="#ffffff"/>',
           f'<text x="{pad}" y="24" font-size="14" font-weight="bold" fill="#24292f">'
           'Equalizer profiles (dB per band, 31 Hz to 16 kHz)</text>']
    for i, p in enumerate(profiles):
        x0 = pad + (i % cols) * cw
        y0 = 34 + (i // cols) * ch
        pw, ph = cw - 2 * pad, ch - 52
        top = y0 + 26
        mid = top + ph / 2
        out.append(f'<text x="{x0}" y="{y0 + 16}" font-size="13" font-weight="bold" fill="#24292f">{p.name}</text>')
        out.append(f'<rect x="{x0}" y="{top}" width="{pw}" height="{ph}" fill="#f6f8fa" stroke="#d0d7de"/>')
        out.append(f'<line x1="{x0}" y1="{mid}" x2="{x0 + pw}" y2="{mid}" stroke="#afb8c1" stroke-dasharray="3 3"/>')
        pts = []
        for j, g in enumerate(p.gains_db):
            x = x0 + pw * (j + 0.5) / len(p.gains_db)
            y = mid - (g / 8.0) * (ph / 2)
            pts.append(f"{x:.1f},{y:.1f}")
        out.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#0969da" stroke-width="2" '
                   'stroke-linejoin="round"/>')
        for pt in pts:
            x, y = pt.split(",")
            out.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#0969da"/>')
        out.append(f'<text x="{x0}" y="{top + ph + 14}" font-size="9" fill="#57606a">31</text>')
        out.append(f'<text x="{x0 + pw}" y="{top + ph + 14}" font-size="9" text-anchor="end" fill="#57606a">16k</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --- terminal replay ------------------------------------------------------

LINE = re.compile(r"^(\S+ \S+) (\w+) (\S+): (.*)$")


def load_session() -> "list[tuple[float, str, str, str]]":
    rows = []
    for raw in (ASSETS / "session.log").read_text(encoding="utf-8").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        stamp = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()
        name = m.group(3).removeprefix("spotify_autoeq.")
        msg = m.group(4)
        msg = re.sub(r"genres=(\[.*?\])", lambda g: "genres=" + ", ".join(ast.literal_eval(g.group(1))), msg)
        rows.append((stamp, m.group(2), name, msg))
    return rows


def wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> "list[str]":
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}" if cur else word
        if font.getlength(trial) > width and cur:
            lines.append(cur)
            cur = "  " + word
        else:
            cur = trial
    lines.append(cur)
    return lines


def draw_text(d, x, y, text, font, bold):
    """Colour a log line: level, logger name, profile names."""
    m = re.match(r"^(INFO|DEBUG|WARNING|ERROR)( \S+:)(.*)$", text)
    if not m:
        d.text((x, y), text, fill=FG, font=font)
        return
    d.text((x, y), m.group(1), fill=GREEN, font=font)
    x += font.getlength(m.group(1))
    d.text((x, y), m.group(2), fill=BLUE, font=font)
    x += font.getlength(m.group(2))
    for part in re.split(r"(profile(?:=| -> )\w+)", m.group(3)):
        hot = part.startswith("profile")
        d.text((x, y), part, fill=ORANGE if hot else FG, font=bold if hot else font)
        x += font.getlength(part)


def demo_gif() -> None:
    font, bold = ImageFont.truetype(FONT, 13), ImageFont.truetype(FONT_BOLD, 13)
    width, rows, lh, top, margin = 1040, 24, 19, 40, 18
    height = top + rows * lh + margin
    session = load_session()

    def frame(lines: "list[str]", prompt: str, cursor: bool) -> Image.Image:
        img = Image.new("RGB", (width, height), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, width, 28], fill=BAR)
        for i, c in enumerate(((237, 135, 150), (238, 212, 159), (166, 218, 149))):
            d.ellipse([14 + i * 20, 8, 26 + i * 20, 20], fill=c)
        d.text((width / 2 - 60, 7), "spotify-autoeq", fill=DIM, font=font)
        visible = lines[-(rows - 1):]
        d.text((margin, top), "$ " + prompt + ("_" if cursor else ""), fill=FG, font=bold)
        for i, text in enumerate(visible):
            draw_text(d, margin, top + (i + 1) * lh, text, font, bold)
        return img

    frames, durations = [], []
    command = "spotify-autoeq run"
    for n in range(0, len(command) + 1, 3):
        frames.append(frame([], command[:n], True))
        durations.append(90)
    shown: list[str] = []
    prev = session[0][0]
    for stamp, level, name, msg in session:
        gap = min(max(stamp - prev, 0.0), 2.2)
        prev = stamp
        if gap > 0.05 and frames:
            durations[-1] = max(durations[-1], int(gap * 1000))
        shown.extend(wrap(f"{level} {name}: {msg}", font, width - 2 * margin))
        frames.append(frame(shown, command, False))
        durations.append(350)
    durations[-1] = 4000
    frames = [f.quantize(colors=24, method=Image.MEDIANCUT) for f in frames]
    frames[0].save(ASSETS / "demo.gif", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True, disposal=2)


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "profiles.svg").write_text(profiles_svg(), encoding="utf-8")
    demo_gif()
    print("wrote", ASSETS / "profiles.svg", ASSETS / "demo.gif")
