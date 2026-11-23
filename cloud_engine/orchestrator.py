"""Sanatani Code-Animated Shorts Engine — Deterministic Pipeline Orchestrator."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from upload_lock import UploadLockStore
from story_pipeline import select_story, generate_and_critique_script, record_story_history
from lexicon_caption import apply_lexicon, build_synced_ass_captions
from providers import synthesize_tts_with_fallback, notify_vivo_y11
from renderer_2d import pick_visual_variety, render_2d_short_mp4, validate_animation_spec
from video_qc import run_video_qc
from youtube_uploader import upload_short_idempotent

IST = ZoneInfo("Asia/Kolkata")
STAGES = [
    "INIT_LOCK",
    "STORY_SELECT",
    "SCRIPT_AND_QC",
    "TTS_SYNTH",
    "ANIM_CODE_GEN",
    "RENDER_2D",
    "VIDEO_QC",
    "YT_UPLOAD",
    "NOTIFY_DONE",
]


def load_checkpoint(run_dir: Path) -> dict:
    cp_file = run_dir / "checkpoint.json"
    if cp_file.exists():
        return json.loads(cp_file.read_text(encoding="utf-8"))
    return {"completed_stages": [], "artifacts": {}}


def save_checkpoint(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "checkpoint.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanatani Code-Animated Shorts Engine")
    parser.add_argument("--dry-run", action="store_true", help="Skip YouTube upload; verify full render & QC")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    parser.add_argument("--publish-at", default=None, help="Optional ISO-8601 UTC timestamp for scheduled release")
    parser.add_argument("--resume-from", default=None, choices=STAGES, help="Force resume from a specific stage")
    args = parser.parse_args()

    now_ist = datetime.now(IST)
    date_key = now_ist.strftime("%Y-%m-%d")
    run_id = f"{date_key}-ist"
    state_dir = Path(os.getenv("ENGINE_STATE_DIR", "state"))
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    history_path = state_dir / "stories_history.json"

    lock_store = UploadLockStore(state_dir / "upload_lock.json")
    cp = load_checkpoint(run_dir)
    completed = set(cp.get("completed_stages", []))
    if args.resume_from:
        idx = STAGES.index(args.resume_from)
        completed = {s for s in completed if STAGES.index(s) < idx}

    # Stage 1: INIT_LOCK
    if not args.dry_run:
        lock_status, existing = lock_store.acquire_daily_lock(date_key, run_id)
        if lock_status == "ALREADY_UPLOADED_TODAY":
            print(f"[INIT_LOCK] ALREADY_UPLOADED_TODAY ({date_key} -> {existing['youtube_video_id']}). Exiting 0.")
            return 0
    print(f"[INIT_LOCK] Acquired lock for run_id={run_id} (dry_run={args.dry_run})")

    # Stage 2: STORY_SELECT
    if "STORY_SELECT" not in completed:
        story_seed = select_story(history_path, date_key)
        (run_dir / "story_seed.json").write_text(json.dumps(story_seed, indent=2), encoding="utf-8")
        completed.add("STORY_SELECT")
        cp["completed_stages"] = list(completed)
        save_checkpoint(run_dir, cp)
    else:
        story_seed = json.loads((run_dir / "story_seed.json").read_text(encoding="utf-8"))

    # Stage 3: SCRIPT_AND_QC
    if "SCRIPT_AND_QC" not in completed:
        script, qc_report = generate_and_critique_script(story_seed)
        (run_dir / "script.json").write_text(json.dumps(script, indent=2), encoding="utf-8")
        (run_dir / "qc_report.json").write_text(json.dumps(qc_report, indent=2), encoding="utf-8")
        if not qc_report["passed"]:
            notify_vivo_y11(f"CRITICAL Script QC failed for {run_id}: {qc_report['issues']}", priority="high")
            return 1
        completed.add("SCRIPT_AND_QC")
        cp["completed_stages"] = list(completed)
        save_checkpoint(run_dir, cp)
    else:
        script = json.loads((run_dir / "script.json").read_text(encoding="utf-8"))

    # Stage 4: TTS_SYNTH
    audio_path = run_dir / "narration.wav"
    if "TTS_SYNTH" not in completed or not audio_path.exists():
        tts_text = apply_lexicon(script, Path(__file__).parent / "lexicon.json")
        (run_dir / "tts_input.txt").write_text(tts_text, encoding="utf-8")
        tts_meta = synthesize_tts_with_fallback(tts_text, audio_path)
        cp["tts_provider"] = tts_meta["provider"]
        completed.add("TTS_SYNTH")
        cp["completed_stages"] = list(completed)
        save_checkpoint(run_dir, cp)

    # Stage 5: ANIM_CODE_GEN
    variety = cp.get("visual_variety")
    if "ANIM_CODE_GEN" not in completed or not variety:
        variety = pick_visual_variety(
            run_id,
            story_seed["story_id"],
            history_path,
            preferred_template=story_seed.get("template"),
        )
        anim_spec_code = f"VARIETY = {repr(variety)}\n"
        if not validate_animation_spec(anim_spec_code):
            variety = {"palette_id": "saffron_indigo_dusk", "template_id": "temple_lamp_zen", "seed": 1}
        (run_dir / "anim_spec.py").write_text(anim_spec_code, encoding="utf-8")
        cp["visual_variety"] = variety
        completed.add("ANIM_CODE_GEN")
        cp["completed_stages"] = list(completed)
        save_checkpoint(run_dir, cp)

    # Stage 6: RENDER_2D
    video_path = run_dir / "final_short.mp4"
    if "RENDER_2D" not in completed or not video_path.exists():
        ass_path = run_dir / "captions.ass"
        audio_dur = build_synced_ass_captions(script, audio_path, ass_path)
        render_2d_short_mp4(script, variety, audio_path, ass_path, video_path, audio_dur)
        completed.add("RENDER_2D")
        cp["completed_stages"] = list(completed)
        save_checkpoint(run_dir, cp)

    # Stage 7: VIDEO_QC
    qc_vid = run_video_qc(video_path)
    (run_dir / "video_qc.json").write_text(json.dumps(qc_vid, indent=2), encoding="utf-8")
    if not qc_vid["passed"]:
        notify_vivo_y11(f"VIDEO_QC failed for {run_id}: {qc_vid['errors']}", priority="high")
        return 1

    # Stage 8: YT_UPLOAD
    if args.dry_run:
        print(f"[YT_UPLOAD] Dry-run complete. Verified {video_path} ({qc_vid['resolution']}, {qc_vid['duration_sec']:.1f}s).")
        return 0

    yt_receipt = upload_short_idempotent(
        lock_store=lock_store,
        date_key=date_key,
        run_id=run_id,
        video_path=video_path,
        script=script,
        privacy_status=args.privacy,
        publish_at=args.publish_at,
    )
    record_story_history(history_path, script, variety, date_key)

    # Stage 9: NOTIFY_DONE
    notify_vivo_y11(
        f"Published Sanatani Short ({date_key} IST)\n"
        f"Title: {script['title']}\n"
        f"URL: https://youtube.com/shorts/{yt_receipt['youtube_video_id']}\n"
        f"TTS: {cp.get('tts_provider', 'sarvam')} | Privacy: {args.privacy}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
