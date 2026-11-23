"""Story Deduplication, Multi-LLM Script Generation, Fact Critique & Word-Error Repair."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from providers import call_llm_with_fallback

DOUBLED_WORD_RE = re.compile(r"\b([A-Za-z]+)\s+\1\b", re.IGNORECASE)
MOJIBAKE_RE = re.compile(r"[ÃÂâ€™â€œ]|\\u[0-9a-fA-F]{4}")
REPEATED_PUNCT_RE = re.compile(r"[!?.,]{3,}|,,|\.\.(?!\.)")

CURATED_STORIES = [
    {
        "story_id": "katha-nachiketa-01",
        "title": "Why Nachiketa Refused Gold From Yama",
        "deity_or_text": "Katha Upanishad",
        "core_theme": "Eternal wisdom over fleeting wealth",
        "template": "temple_lamp_zen",
        "hook": "If Death offered you kingdoms and gold, would you walk away?",
        "scenes": [
            {"scene_id": 1, "narration_text": "In the Katha Upanishad, young Nachiketa waited three nights at Yama's gate without food.", "visual_prompt_2d": "Boy silhouette before dark temple arch with golden diya glow", "on_screen_caption": "Three nights at Yama's gate", "duration_sec_est": 9.5},
            {"scene_id": 2, "narration_text": "Moved by his Tapasya, Yama offered wealth and long life instead of the secret of the soul.", "visual_prompt_2d": "Golden lotus petals fading beside a luminous Bindu", "on_screen_caption": "Wealth fades, truth endures", "duration_sec_est": 10.5},
            {"scene_id": 3, "narration_text": "Nachiketa answered gently: pleasures wear out tomorrow, teach me what never dies.", "visual_prompt_2d": "Radiant saffron lotus unfolding above calm indigo waters", "on_screen_caption": "Teach me what endures", "duration_sec_est": 10.0},
        ],
        "outro_reflection": "True wealth is clarity that remains when everything temporary falls away.",
        "sources_or_tradition_note": "Katha Upanishad (1.1.20-29), Krishna Yajurveda",
    },
    {
        "story_id": "yaksha-prashna-02",
        "title": "Yudhishthira's Answer That Revived His Brothers",
        "deity_or_text": "Mahabharata (Yaksha Prashna)",
        "core_theme": "Dharma as the shield of the wise",
        "template": "mountain_river_journey",
        "hook": "What is swifter than the wind, and heavier than the earth itself?",
        "scenes": [
            {"scene_id": 1, "narration_text": "Beside an enchanted lake, four Pandava brothers fell because they drank before answering the Yaksha.", "visual_prompt_2d": "Rippling emerald pool flanked by mountain silhouettes", "on_screen_caption": "The enchanted forest lake", "duration_sec_est": 10.0},
            {"scene_id": 2, "narration_text": "Yudhishthira paused and replied with calm Dharma: the mind is swifter than wind, and a mother's love outweighs the earth.", "visual_prompt_2d": "Glowing golden Dharma chakra reflecting on calm water", "on_screen_caption": "The mind outpaces wind", "duration_sec_est": 11.0},
            {"scene_id": 3, "narration_text": "Asked the greatest wonder, he said: every day we see mortality, yet live as if time were endless.", "visual_prompt_2d": "Sunrise breaking over Himalayan peaks and flowing river", "on_screen_caption": "Respect each waking dawn", "duration_sec_est": 10.5},
        ],
        "outro_reflection": "Pausing in patience turns crisis into clarity.",
        "sources_or_tradition_note": "Mahabharata, Vana Parva, Yaksha Prashna",
    },
    {
        "story_id": "ramayana-shabari-03",
        "title": "Shabari's Berries and the Measure of Bhakti",
        "deity_or_text": "Valmiki Ramayana",
        "core_theme": "Sincere devotion beyond ritual perfection",
        "template": "lotus_mandala_pulse",
        "hook": "For decades, an elderly hermit swept a forest path every morning for a guest she had never met.",
        "scenes": [
            {"scene_id": 1, "narration_text": "By Lake Pampa, Shabari gathered wild berries each day, tasting every single one so no bitter fruit would reach Shri Rama.", "visual_prompt_2d": "Lotus ripples on Lake Pampa at golden hour", "on_screen_caption": "Only the sweetest offering", "duration_sec_est": 10.5},
            {"scene_id": 2, "narration_text": "When Rama and Lakshmana arrived, he accepted those tasted berries with deep reverence.", "visual_prompt_2d": "Warm brass diya flame rising beside lotus mandala", "on_screen_caption": "Accepted with reverence", "duration_sec_est": 9.5},
            {"scene_id": 3, "narration_text": "He reminded the world that pure Bhakti is measured by love, never by wealth or status.", "visual_prompt_2d": "Expanding 12-petal sacred lotus geometry", "on_screen_caption": "Bhakti sees only love", "duration_sec_est": 9.5},
        ],
        "outro_reflection": "Small acts done with full-hearted sincerity become sacred.",
        "sources_or_tradition_note": "Valmiki Ramayana, Aranya Kanda (Canto 74)",
    },
    {
        "story_id": "gita-steadiness-04",
        "title": "The Chariot Lesson Before the First Arrow",
        "deity_or_text": "Bhagavad Gita",
        "core_theme": "Equanimity in action without anxiety over results",
        "template": "path_of_dharma_steps",
        "hook": "Right before the greatest battle of his life, the sharpest archer lowered his bow.",
        "scenes": [
            {"scene_id": 1, "narration_text": "Before the first arrow flew, Arjuna sat in turmoil; attachment to outcomes had clouded his Dharma.", "visual_prompt_2d": "Still chariot wheel beneath twilight sky", "on_screen_caption": "Attachment clouds clarity", "duration_sec_est": 10.0},
            {"scene_id": 2, "narration_text": "In the Bhagavad Gita, Krishna taught Karma Yoga: give excellence to duty, then release anxiety over reward.", "visual_prompt_2d": "Ascending Dharma steps bathed in golden sunrise rays", "on_screen_caption": "Act fully, release anxiety", "duration_sec_est": 11.0},
            {"scene_id": 3, "narration_text": "When effort becomes an offering, fear loses its grip on the mind.", "visual_prompt_2d": "Steady lamp flame shining through deep indigo night", "on_screen_caption": "Steady mind, fearless action", "duration_sec_est": 9.5},
        ],
        "outro_reflection": "Own your effort completely; let the universe arrange the harvest.",
        "sources_or_tradition_note": "Bhagavad Gita, Chapter 2 Verse 47",
    },
    {
        "story_id": "bhagavata-prahlada-05",
        "title": "Where Does the Pillar Answer From?",
        "deity_or_text": "Bhagavata Purana",
        "core_theme": "Fearless conviction and divine presence everywhere",
        "template": "starry_sky_reflection",
        "hook": "How does a child stay completely calm when every power in the palace stands against him?",
        "scenes": [
            {"scene_id": 1, "narration_text": "Young Prahlada told his father that the Supreme is not confined to heaven or stone shrines alone.", "visual_prompt_2d": "Nakshatra stars connected in geometric sacred lines", "on_screen_caption": "Present in every atom", "duration_sec_est": 10.0},
            {"scene_id": 2, "narration_text": "Asked if grace resided even inside a cold marble pillar, Prahlada answered yes without hesitation.", "visual_prompt_2d": "Golden light radiating outward from center geometry", "on_screen_caption": "Yes, even in the pillar", "duration_sec_est": 10.0},
            {"scene_id": 3, "narration_text": "True courage is not loud anger; it is knowing the sacred walks beside you everywhere.", "visual_prompt_2d": "Calm mirror lake reflecting crescent moon and dawn glow", "on_screen_caption": "Quiet courage endures all", "duration_sec_est": 9.5},
        ],
        "outro_reflection": "Carry stillness inside, and no outside noise can shake your center.",
        "sources_or_tradition_note": "Shrimad Bhagavata Purana, Canto 7",
    },
]


def select_story(history_path: Path, date_key: str, cooldown_days: int = 75) -> dict:
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    used_recently = {
        h["story_id"]
        for h in history
        if (date.fromisoformat(date_key) - date.fromisoformat(h["date_used"])).days < cooldown_days
    }
    for item in CURATED_STORIES:
        if item["story_id"] not in used_recently:
            return item
    return CURATED_STORIES[0]


def auto_repair_text(raw: str) -> str:
    cleaned = DOUBLED_WORD_RE.sub(r"\1", raw)
    cleaned = cleaned.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"')
    cleaned = REPEATED_PUNCT_RE.sub(".", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def generate_and_critique_script(seed: dict) -> tuple[dict, dict]:
    llm_provider = "curated-deterministic"
    script = dict(seed)

    prompt = (
        f"Write a respectful, historically accurate 40-second YouTube Short script about '{seed['title']}' "
        f"from '{seed['deity_or_text']}'. Return strict JSON with keys: title, hook, scenes "
        "(list of {scene_id, narration_text, visual_prompt_2d, on_screen_caption, duration_sec_est}), "
        "outro_reflection, sources_or_tradition_note."
    )
    try:
        llm_json, llm_provider = call_llm_with_fallback(prompt)
        if isinstance(llm_json.get("scenes"), list) and len(llm_json["scenes"]) >= 2:
            script.update({
                "title": llm_json.get("title", seed["title"]),
                "hook": llm_json.get("hook", seed["hook"]),
                "scenes": llm_json["scenes"],
                "outro_reflection": llm_json.get("outro_reflection", seed["outro_reflection"]),
                "sources_or_tradition_note": llm_json.get("sources_or_tradition_note", seed["sources_or_tradition_note"]),
            })
    except Exception:
        pass

    for scene in script["scenes"]:
        scene["narration_text"] = auto_repair_text(scene["narration_text"])
    script["outro_reflection"] = auto_repair_text(script["outro_reflection"])

    full_text = " ".join(s["narration_text"] for s in script["scenes"]) + " " + script["outro_reflection"]
    issues = []
    if DOUBLED_WORD_RE.search(full_text):
        issues.append("WORD_DOUBLED")
    if MOJIBAKE_RE.search(full_text):
        issues.append("ENCODING_MOJIBAKE")
    if not script.get("sources_or_tradition_note"):
        issues.append("MISSING_SOURCE_NOTE")

    script["script_hash"] = hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16]
    qc_report = {
        "passed": len(issues) == 0,
        "issues": issues,
        "word_count": len(full_text.split()),
        "llm_provider": llm_provider,
    }
    return script, qc_report


def record_story_history(history_path: Path, script: dict, variety: dict, date_key: str) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history.append({
        "story_id": script["story_id"],
        "canonical_title": script["title"],
        "deity_or_text": script.get("deity_or_text", script.get("sources_or_tradition_note", "")),
        "script_hash": script["script_hash"],
        "date_used": date_key,
        "palette_id": variety["palette_id"],
        "template_id": variety["template_id"],
    })
    tmp = history_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2), encoding="utf-8")
    tmp.replace(history_path)
