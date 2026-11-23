"""Automated VIDEO_QC Gate using ffprobe and early/mid/late frame luma checks."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _sample_luma(video_path: Path, timestamp_sec: float, out_png: Path) -> float:
    from PIL import Image, ImageStat

    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{timestamp_sec:.2f}",
            "-i", str(video_path), "-frames:v", "1", str(out_png)
        ],
        capture_output=True,
        check=True,
    )
    img = Image.open(out_png).convert("L")
    return ImageStat.Stat(img).mean[0] / 255.0


def run_video_qc(video_path: Path) -> dict:
    errors = []
    if not video_path.exists() or video_path.stat().st_size < 100_000:
        return {"passed": False, "errors": ["Missing or undersized MP4"]}

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,width,height,duration", "-of", "json", str(video_path)
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not v_stream or v_stream.get("width") != 1080 or v_stream.get("height") != 1920:
        errors.append("Resolution is not strictly 1080x1920")
    if not a_stream:
        errors.append("Missing audio stream")

    v_dur = float(v_stream.get("duration", 0)) if v_stream else 0.0
    a_dur = float(a_stream.get("duration", 0)) if a_stream else 0.0
    if abs(v_dur - a_dur) > 1.5:
        errors.append(f"Audio/video duration drift {abs(v_dur - a_dur):.2f}s")

    luma_samples = []
    if v_dur >= 3.0:
        qc_dir = video_path.parent / "qc_frames"
        qc_dir.mkdir(parents=True, exist_ok=True)
        for idx, ts in enumerate((0.5, v_dur * 0.5, max(1.0, v_dur - 1.0))):
            luma = _sample_luma(video_path, ts, qc_dir / f"sample_{idx}.png")
            luma_samples.append(round(luma, 3))
        if any(val < 0.03 or val > 0.97 for val in luma_samples):
            errors.append(f"Blank or blown-out frame detected in samples {luma_samples}")

    return {
        "passed": len(errors) == 0,
        "resolution": f"{v_stream.get('width')}x{v_stream.get('height')}" if v_stream else "unknown",
        "duration_sec": v_dur,
        "luma_samples": luma_samples,
        "errors": errors,
    }
