"""2D Flat Vector Animation Renderer (1080x1920, 30fps) with AST Guard & 5 Fallback Templates."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

PALETTES = {
    "saffron_indigo_dusk": ((15, 18, 43), (221, 107, 32), (255, 183, 77), (255, 224, 178)),
    "terracotta_teal_dawn": ((10, 46, 54), (224, 122, 95), (244, 162, 97), (255, 232, 204)),
    "sandalwood_emerald": ((6, 44, 36), (217, 155, 82), (246, 208, 138), (255, 243, 205)),
    "gold_midnight_violet": ((22, 11, 46), (180, 83, 9), (251, 191, 36), (254, 240, 138)),
}
TEMPLATES = [
    "temple_lamp_zen",
    "mountain_river_journey",
    "lotus_mandala_pulse",
    "starry_sky_reflection",
    "path_of_dharma_steps",
]


def pick_visual_variety(run_id: str, story_id: str, history_path: Path, preferred_template: str | None = None) -> dict:
    seed = int(hashlib.sha256(f"{run_id}_{story_id}".encode()).hexdigest(), 16)
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    recent = history[-3:]
    recent_palettes = {h.get("palette_id") for h in recent}
    recent_templates = {h.get("template_id") for h in recent}

    pal_keys = list(PALETTES.keys())
    chosen_pal = pal_keys[seed % len(pal_keys)]
    if chosen_pal in recent_palettes:
        chosen_pal = next((p for p in pal_keys if p not in recent_palettes), pal_keys[(seed + 1) % len(pal_keys)])

    chosen_tpl = preferred_template if preferred_template in TEMPLATES else TEMPLATES[(seed // 7) % len(TEMPLATES)]
    if chosen_tpl in recent_templates:
        chosen_tpl = next((t for t in TEMPLATES if t not in recent_templates), TEMPLATES[(seed + 2) % len(TEMPLATES)])

    return {"palette_id": chosen_pal, "template_id": chosen_tpl, "seed": seed % 100000}


def validate_animation_spec(spec_code: str) -> bool:
    """AST syntax check before running dynamic animation specs."""
    try:
        ast.parse(spec_code)
        return True
    except SyntaxError:
        return False


def _draw_template_frame(template_id: str, draw: Any, phase: float, colors: tuple) -> None:
    bg, horizon, accent, glow = colors
    w, h = 1080, 1920

    if template_id == "temple_lamp_zen":
        draw.polygon([(240, 1480), (380, 920), (540, 520), (700, 920), (840, 1480)], fill=(20, 17, 38))
        draw.chord([320, 1020, 760, 1220], start=0, end=180, fill=accent)
        sway = int(math.sin(phase * 6 * math.pi) * 18)
        draw.polygon([(540 + sway, 820), (490, 1020), (590, 1020)], fill=glow)
        for i in range(6):
            t = (phase + i * 0.16) % 1.0
            my = int(1000 - t * 620)
            mx = 420 + (i * 48) + int(math.sin(t * 6) * 16)
            draw.ellipse([mx - 6, my - 6, mx + 6, my + 6], fill=glow)

    elif template_id == "mountain_river_journey":
        sun_y = int(680 - 40 * math.sin(phase * 2 * math.pi))
        draw.ellipse([410, sun_y - 130, 670, sun_y + 130], fill=glow)
        drift = int(math.cos(phase * 2 * math.pi) * 24)
        draw.polygon([(0, 1280), (320 + drift, 860), (660 + drift, 1120), (1080, 820), (1080, 1920), (0, 1920)], fill=(18, 22, 42))
        draw.polygon([(510, 1120), (390, 1920), (690, 1920), (570, 1120)], fill=accent)

    elif template_id == "starry_sky_reflection":
        stars = [(220, 340), (410, 440), (580, 300), (790, 410), (880, 560)]
        for i in range(len(stars) - 1):
            draw.line([stars[i], stars[i + 1]], fill=accent, width=2)
        for idx, (sx, sy) in enumerate(stars):
            r = 6 + int(4 * math.sin((phase + idx * 0.2) * 2 * math.pi))
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=glow)
        draw.ellipse([430, 520, 650, 740], fill=glow)
        draw.ellipse([475, 500, 680, 710], fill=bg)
        draw.rectangle([0, 1180, 1080, 1920], fill=(12, 14, 30))
        for r in range(5):
            ry = 1260 + r * 75
            rw = 360 - r * 35
            draw.line([(540 - rw // 2, ry), (540 + rw // 2, ry)], fill=accent, width=4)

    elif template_id == "path_of_dharma_steps":
        cx, cy, rad = 540, 680, 190
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=glow, width=6)
        for i in range(8):
            ang = phase * math.pi + i * (math.pi / 4)
            draw.line([(cx, cy), (cx + int(math.cos(ang) * rad), cy + int(math.sin(ang) * rad))], fill=glow, width=4)
        for step in range(6):
            sw = int(900 - step * 90)
            y0 = 1600 - step * 90
            draw.rectangle([(1080 - sw) // 2, y0, (1080 + sw) // 2, y0 + 84], fill=(22, 24, 46), outline=accent, width=2)

    else:  # lotus_mandala_pulse
        draw.rectangle([0, 1220, 1080, 1920], fill=horizon)
        pulse = int(190 + 24 * math.sin(phase * 2 * math.pi))
        cx, cy = 540, 820
        draw.ellipse([cx - pulse, cy - pulse, cx + pulse, cy + pulse], outline=accent, width=6)
        for p in range(12):
            ang = phase * 2 * math.pi + p * (math.pi / 6)
            px = cx + int(math.cos(ang) * 260)
            py = cy + int(math.sin(ang) * 260)
            draw.ellipse([px - 22, py - 22, px + 22, py + 22], fill=glow)


def render_2d_short_mp4(
    script: dict,
    variety: dict,
    audio_path: Path,
    ass_path: Path,
    out_mp4: Path,
    duration_sec: float,
    fps: int = 30,
) -> None:
    from PIL import Image, ImageDraw

    frames_dir = out_mp4.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    colors = PALETTES[variety["palette_id"]]
    bg = colors[0]
    total_frames = max(30, int(duration_sec * fps))

    for i in range(total_frames):
        phase = (i % (fps * 6)) / float(fps * 6)
        img = Image.new("RGB", (1080, 1920), bg)
        draw = ImageDraw.Draw(img)
        _draw_template_frame(variety["template_id"], draw, phase, colors)
        img.save(frames_dir / f"frame_{i:05d}.png")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-i", str(audio_path),
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_mp4),
        ],
        check=True,
    )