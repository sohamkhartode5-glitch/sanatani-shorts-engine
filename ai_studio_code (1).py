"""Multi-provider LLM, Sarvam AI TTS, and Vivo Y11 5G Notification Adapters."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def _is_configured(val: str | None) -> bool:
    return bool(val and val.strip() and not val.startswith("MY_"))


def call_llm_with_fallback(prompt: str) -> tuple[dict, str]:
    """Ordered fallback chain: Gemini REST -> Groq -> OpenRouter."""
    providers = [
        ("gemini", os.getenv("GEMINI_API_KEY")),
        ("groq", os.getenv("GROQ_API_KEY")),
        ("openrouter", os.getenv("OPENROUTER_API_KEY")),
    ]
    last_err: Exception | None = None

    for name, key in providers:
        if not _is_configured(key):
            continue
        for attempt in range(3):
            try:
                if name == "gemini":
                    url = (
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        f"gemini-2.5-flash:generateContent?key={key}"
                    )
                    payload = json.dumps({
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=25) as r:
                        body = json.loads(r.read().decode("utf-8"))
                        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
                        return json.loads(raw_text), "gemini-2.5-flash"

                if name == "groq":
                    req = urllib.request.Request(
                        "https://api.groq.com/openai/v1/chat/completions",
                        data=json.dumps({
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "response_format": {"type": "json_object"},
                        }).encode("utf-8"),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=25) as r:
                        body = json.loads(r.read().decode("utf-8"))
                        return json.loads(body["choices"][0]["message"]["content"]), "groq-llama-3.3-70b"

                if name == "openrouter":
                    req = urllib.request.Request(
                        "https://openrouter.ai/api/v1/chat/completions",
                        data=json.dumps({
                            "model": "meta-llama/llama-3.3-70b-instruct:free",
                            "messages": [{"role": "user", "content": prompt}],
                        }).encode("utf-8"),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=25) as r:
                        body = json.loads(r.read().decode("utf-8"))
                        content = body["choices"][0]["message"]["content"].strip()
                        if content.startswith("```"):
                            content = content.strip("`").lstrip("json").strip()
                        return json.loads(content), "openrouter-free"

            except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError) as err:
                last_err = err
                time.sleep(min(20, 2 ** (attempt + 1)))

    raise RuntimeError(f"All remote LLM providers unavailable ({last_err})")


def synthesize_tts_with_fallback(tts_input_text: str, out_wav: Path) -> dict:
    """Primary: Sarvam AI bulbul:v2 -> Secondary: Edge TTS -> Tertiary: gTTS -> Local espeak-ng."""
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    if _is_configured(sarvam_key):
        for attempt in range(3):
            try:
                payload = json.dumps({
                    "inputs": [tts_input_text[:490]],
                    "target_language_code": "en-IN",
                    "speaker": "anushka",
                    "pace": 0.96,
                    "loudness": 1.1,
                    "speech_sample_rate": 22050,
                    "enable_preprocessing": True,
                    "model": "bulbul:v2",
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.sarvam.ai/text-to-speech",
                    data=payload,
                    headers={"api-subscription-key": sarvam_key, "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    out_wav.write_bytes(base64.b64decode(data["audios"][0]))
                    return {"provider": "sarvam-ai-bulbul-v2"}
            except Exception:
                time.sleep(3 * (attempt + 1))

    # Fallback 2: edge-tts CLI
    try:
        mp3_tmp = out_wav.with_suffix(".mp3")
        subprocess.run(
            ["edge-tts", "--voice", "en-IN-NeerjaNeural", "--text", tts_input_text, "--write-media", str(mp3_tmp)],
            check=True,
            timeout=35,
        )
        subprocess.run(["ffmpeg", "-y", "-i", str(mp3_tmp), "-ar", "22050", "-ac", "1", str(out_wav)], check=True)
        return {"provider": "edge-tts-en-in-fallback"}
    except Exception:
        pass

    # Fallback 3: gTTS
    try:
        from gtts import gTTS

        mp3_tmp = out_wav.with_suffix(".gtts.mp3")
        gTTS(text=tts_input_text, lang="en", tld="co.in").save(str(mp3_tmp))
        subprocess.run(["ffmpeg", "-y", "-i", str(mp3_tmp), "-ar", "22050", "-ac", "1", str(out_wav)], check=True)
        return {"provider": "gtts-en-in-fallback"}
    except Exception:
        pass

    # Fallback 4: local espeak-ng
    subprocess.run(["espeak-ng", "-v", "en-in", "-w", str(out_wav), tts_input_text], check=True)
    return {"provider": "espeak-local-fallback"}


def notify_vivo_y11(message: str, priority: str = "default") -> None:
    """Bandwidth-conscious mobile alerts via ntfy.sh and/or Telegram Bot API."""
    ntfy_topic = os.getenv("NTFY_TOPIC", "sanatani-shorts-vivo-y11").strip()
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=message.encode("utf-8"),
                headers={"Title": "Sanatani Shorts Engine", "Priority": priority},
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if _is_configured(tg_token) and _is_configured(tg_chat):
        try:
            payload = json.dumps({"chat_id": tg_chat, "text": message}).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass