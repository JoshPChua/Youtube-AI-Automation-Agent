#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║         JPEEEZY AI VIDEO FACTORY — AGENTIC WORKFLOW          ║
║                   Powered by Claude AI                        ║
║                                                               ║
║  MODES:                                                       ║
║    python jpeeezy_agent.py run       → process one video now  ║
║    python jpeeezy_agent.py schedule  → run every 24 hours     ║
║    python jpeeezy_agent.py chat      → interactive AI chat    ║
╚═══════════════════════════════════════════════════════════════╝
"""

import os
import sys


def _get_key(name: str) -> str:
    """Read credential from globals — always current after credentials.py loads."""
    return globals().get(name) or ""

def _anthropic_client():
    """Create Anthropic client using current credentials."""
    key = _get_key("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set — check credentials.py")
    import anthropic as _ant
    return _ant.Anthropic(api_key=key)

def _openai_headers() -> dict:
    """Return OpenAI auth headers using current credentials."""
    return {
        "Authorization": f"Bearer {_get_key('OPENAI_API_KEY')}",
        "Content-Type":  "application/json"
    }


import json
import time
import random
import pickle
import argparse
import tempfile
import schedule
import threading
from pathlib import Path
from datetime import datetime, date

import requests
import anthropic
import hmac
import hashlib
import base64
import gspread
from colorama import Fore, Back, Style, init
from google.oauth2.service_account import Credentials as SACredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

init(autoreset=True)

# ════════════════════════════════════════════════════════════════
#  CONFIG — edit these or set as environment variables
# ════════════════════════════════════════════════════════════════

# ── These defaults are overridden by credentials.py ──────────────
ANTHROPIC_API_KEY   = ""
OPENAI_API_KEY      = ""
PEXELS_API_KEY      = ""
CREATOMATE_API_KEY  = ""
CREATOMATE_TEMPLATE = ""
GOOGLE_SHEET_ID     = ""
GDRIVE_AUDIO_FOLDER_ID = "1PDxuHuBDqak9LvQRAgqJTaBTFNCyqIOV"
KLING_ACCESS_KEY    = ""
KLING_SECRET_KEY    = ""
KLING_API_BASE   = "https://api.klingai.com"  # constant, not in credentials
LUMA_API_KEY        = ""  # Luma AI Dream Machine — primary animation provider (subtle motion/facial expression)
TELEGRAM_BOT_TOKEN  = ""
TELEGRAM_CHAT_ID    = ""
IMGBB_API_KEY       = ""  # Optional: get free key at imgbb.com/api — improves Kling image hosting
GSHEETS_SERVICE_ACCOUNT_FILE = "gsheets_service_account.json"

# YouTube OAuth credentials files (one per channel)
# Download from Google Cloud Console → APIs → Credentials
YOUTUBE_CHANNELS = {
    "nyorkies": {
        "display_name":   "NyorkieTales",
        "watermark":      "@NyorkieTales",
        "niche":          "cute animals, animal adventures, and heartwarming animal stories",
        "tags":           "shorts,viral,trending,animals,cuteanimals,funnyanimal,animalstory,pets,wildlife,adorable",
        "cta":            "Follow @NyorkieTales for daily animal stories that warm your heart.",
        "hashtags":       "#Animals #CuteAnimals #AnimalStory #Pets #Wildlife #FunnyAnimals #shorts #viral #trending",
        "credentials":    "youtube_credentials_nyorkies.json",
        "token":          "youtube_token_nyorkies.pickle",
        "style":          "pixar_animals",
        "script_format":  "animal_story",
        "schedule_hour":  8,
    },
    "jpeezy": {
        "display_name":   "UntoldSelf2",
        "watermark":      "@UntoldSelf2",
        "niche":          "emotional storytelling, personal growth, and AI money-making strategies",
        "tags":           "shorts,viral,trending,storytelling,motivation,lifelessons,aitools,makemoneyonline,mindset,inspiration",
        "cta":            "Follow @UntoldSelf2 for stories and money strategies that change your life.",
        "hashtags":       "#Storytelling #Motivation #LifeLessons #AITools #MakeMoneyOnline #Mindset #shorts #viral #trending",
        "credentials":    "youtube_credentials_jpeezy.json",
        "token":          "youtube_token_jpeezy.pickle",
        "style":          "pixar_story",
        "script_format":  "mixed_story_money",
        "schedule_hour":  20,
    },
}


# Load credentials from credentials.py — direct import (most reliable)
try:
    import importlib.util as _ilu, pathlib as _pl
    _cp   = _pl.Path(__file__).parent / "credentials.py"
    _spec = _ilu.spec_from_file_location("_creds", _cp)
    _cm   = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_cm)
    # Directly inject all credential values into this module's globals
    for _k, _v in vars(_cm).items():
        if not _k.startswith("_"):
            globals()[_k] = _v
    print(f"[✅ credentials.py loaded from {_cp}]")
except Exception as _e:
    print(f"[⚠️  credentials.py not loaded: {_e} — using inline values]")
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# ════════════════════════════════════════════════════════════════
#  PRETTY LOGGING
# ════════════════════════════════════════════════════════════════

def log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    icons = {"info": "ℹ️ ", "success": "✅", "error": "❌", "warn": "⚠️ ", "agent": "🤖", "tool": "🔧", "step": "▶️ "}
    colors = {
        "info":    Fore.CYAN,
        "success": Fore.GREEN,
        "error":   Fore.RED,
        "warn":    Fore.YELLOW,
        "agent":   Fore.MAGENTA,
        "tool":    Fore.BLUE,
        "step":    Fore.WHITE,
    }
    icon  = icons.get(level, "  ")
    color = colors.get(level, Fore.WHITE)
    print(f"{Fore.LIGHTBLACK_EX}[{ts}] {color}{icon} {msg}{Style.RESET_ALL}")

def banner():
    print(f"""
{Fore.MAGENTA}╔═══════════════════════════════════════════════════════════╗
║        JPEEEZY AI VIDEO FACTORY — AGENTIC MODE           ║
║                  Powered by Claude AI                     ║
╚═══════════════════════════════════════════════════════════╝{Style.RESET_ALL}
""")

def _sanitize_caption(text: str) -> str:
    """Remove Unicode chars that render as boxes (□) in Creatomate.
    Replaces em-dashes, curly quotes, and other problem chars with ASCII equivalents."""
    replacements = {
        '\u2014': ' - ', '\u2013': ' - ',   # em/en dash
        '\u2018': "'",  '\u2019': "'",      # curly single quotes
        '\u201c': '"',  '\u201d': '"',      # curly double quotes
        '\u2026': '...', '\u00a0': ' ',      # ellipsis, non-breaking space
        '\u2022': '-',   '\u00b7': '-',      # bullets
        '\u2012': '-',   '\u2015': '-',      # other dashes
        '\u2033': '"',   '\u2032': "'",      # prime marks
        '\u201a': ',',   '\u201e': '"',      # low quotes
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Strip any remaining non-ASCII to be safe
    return text.encode('ascii', 'ignore').decode('ascii').strip()


# ════════════════════════════════════════════════════════════════
#  TOOL IMPLEMENTATIONS (what Claude can call)
# ════════════════════════════════════════════════════════════════

def get_pending_topic(channel: str = "") -> dict:
    """
    Fetch the next pending topic from Google Sheets.
    If channel is specified, only returns topics for that channel.
    """
    log(f"Reading pending topic from Google Sheets{' for ' + channel if channel else ''}...", "tool")
    try:
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds  = SACredentials.from_service_account_file(GSHEETS_SERVICE_ACCOUNT_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(GOOGLE_SHEET_ID).worksheet("Topics")
        rows   = sheet.get_all_records()

        for row in rows:
            row_status  = str(row.get("status",  "")).strip().lower()
            row_channel = str(row.get("channel", "jpeezy")).strip().lower()
            if row_status == "pending":
                if channel and row_channel != channel.lower():
                    continue
                log(f"Found topic: {row['topic']} → channel: {row_channel}", "success")
                return {
                    "found":    True,
                    "topic":    str(row.get("topic",    "")),
                    "audience": str(row.get("audience", "general")),
                    "tone":     str(row.get("tone",     "energetic")),
                    "channel":  row_channel,
                }
        msg = f"No pending topics for channel '{channel}'" if channel else "No pending topics found"
        return {"found": False, "message": msg}
    except Exception as e:
        return {"found": False, "error": str(e)}


def estimate_scene_duration(text: str) -> float:
    """Dynamic duration based on word count — matches deep male TTS (onyx 0.9x)."""
    words = len(text.strip().split())
    # Onyx at 0.9x speaks ~2.0 words/sec (slower, more dramatic), add 0.7s pause between scenes
    duration = max(3.5, words / 2.0) + 0.7
    return round(duration, 2)


def generate_hooks(topic: str, audience: str, channel: str) -> dict:
    """
    Generate 5 scroll-stopping hook candidates, tuned per channel.
    NyorkieTales: emotional animal story hooks ending with ... (creates open loop)
    UntoldSelf2:  controversial/shocking money+mindset hooks, direct confrontation
    """
    log("Generating 5 viral hook candidates...", "tool")
    niche   = YOUTUBE_CHANNELS.get(channel, YOUTUBE_CHANNELS["nyorkies"])["niche"]
    headers = _openai_headers()

    if channel == "nyorkies":
        hook_rules = """You write hooks for a cute/emotional ANIMAL story channel (NyorkieTales).

HOOK FORMULA — pick one per hook:
1. SPECIFIC SITUATION HOOK: Name the animal + exact detail + cliffhanger
   Examples: "This puppy waited 3 days alone..." / "A kitten born blind found something..."
2. SHOCKING FACT HOOK: something surprising about the animal
   Examples: "No one expected this from a cat..." / "This dog refused to leave..."
3. EMOTIONAL SETUP: triggers immediate empathy
   Examples: "She was abandoned with her puppies..." / "He waited every single day..."

RULES:
- 5 to 8 words MAXIMUM
- MUST end with ... to create an open loop that forces viewers to watch
- Use: alone, abandoned, refused, waited, unexpected, nobody, found, saved
- Never generic — be SPECIFIC (not "a dog story" but "a dog who refused to leave")
- Sound like a person telling a story, NOT an AI
- Return ONLY a valid JSON array of 5 strings"""
    else:
        hook_rules = """You write hooks for a money/AI/mindset channel (UntoldSelf2).

HOOK FORMULA — pick one per hook:
1. DIRECT CONFRONTATION: call out the viewer's mistake directly
   Examples: "Stop saving money right now." / "You're still broke because of this."
2. BANNED/SECRET TRUTH: implies hidden knowledge
   Examples: "Nobody tells you this about money." / "This is why you'll never be rich."
3. PATTERN INTERRUPT: contradicts common belief
   Examples: "Rich people don't save money." / "Working harder keeps you poor."

RULES:
- 5 to 8 words MAXIMUM
- Use: broke, poor, secret, nobody, banned, truth, stop, warning, never, rich
- Must feel like a SLAP — confrontational, urgent, personal
- Sound like a real person who is angry at the system
- Never passive — always active voice, always present tense
- Return ONLY a valid JSON array of 5 strings"""

    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"""{hook_rules}

Topic: {topic}
Audience: {audience}
Niche: {niche}"""}],
        "max_tokens": 250, "temperature": 0.95
    }
    resp  = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=90)
    resp.raise_for_status()
    raw   = resp.json()["choices"][0]["message"]["content"].strip()
    try:
        hooks = json.loads(raw.replace("```json","").replace("```","").strip())
        # Guarantee nyorkies hooks end with ...
        if channel == "nyorkies":
            hooks = [h if h.endswith("...") else h.rstrip(".") + "..." for h in hooks]
    except Exception:
        fallback = f"This {topic} will break your heart..." if channel == "nyorkies" else f"Nobody tells you this about {topic}."
        hooks = [fallback]
    log(f"Generated {len(hooks)} channel-tuned hooks", "success")
    return {"hooks": hooks}


def select_best_hook(hooks: list) -> dict:
    """Pick the single most viral hook."""
    log("Selecting best hook...", "tool")
    headers = _openai_headers()
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"""Which hook is MOST likely to stop the scroll on YouTube Shorts?

{json.dumps(hooks, indent=2)}

Pick the one with highest shock + curiosity + emotional trigger.
Return ONLY the hook text. Nothing else."""}],
        "max_tokens": 50, "temperature": 0.2
    }
    resp      = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    best_hook = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    log(f"Best hook: {best_hook}", "success")
    return {"best_hook": best_hook}


def generate_scene_keyword(scene_text: str, channel: str) -> str:
    """Generate a specific cinematic Pexels keyword for a single scene."""
    headers = _openai_headers()
    niche   = YOUTUBE_CHANNELS.get(channel, YOUTUBE_CHANNELS["nyorkies"])["niche"]
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"""Give ONE specific cinematic stock video search keyword for this scene.

Scene: {scene_text}
Niche: {niche}

Rules:
- Must describe a PERSON doing something visual and emotional
- Be specific, not generic (bad: "money", good: "rich man counting cash dark room")
- 3-6 words max
- Return ONLY the keyword string. Nothing else."""}],
        "max_tokens": 30, "temperature": 0.7
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    keyword = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    # Ensure human subject
    human_words = ["person","man","woman","people","girl","boy","entrepreneur","student","rich","young"]
    if not any(w in keyword.lower() for w in human_words):
        keyword = "person " + keyword
    return keyword[:60]


def evaluate_script(script_lines: list) -> dict:
    """
    Score the 5-scene script 1-10 for viral potential.
    Calibrated scoring: a solid specific script should score 7-8.
    Only truly generic/AI-sounding content scores below 6.
    """
    log("Evaluating script viral score...", "tool")
    script_text = "\n".join([f"Scene {i+1}: {s}" for i, s in enumerate(script_lines)])
    headers     = _openai_headers()
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"""You are a YouTube Shorts content quality judge.
Rate this 5-scene script for viral potential on a scale of 1-10.

{script_text}

SCORING GUIDE — be fair and calibrated:
- Start at 7 (baseline for a solid, specific script)
- ADD +1 if the hook is genuinely shocking or emotionally grabbing in under 5 words
- ADD +1 if Scene 4 (Twist) is specific, surprising, and memorable
- ADD +1 if the whole script feels human-written and emotionally resonant
- SUBTRACT -1 if the hook is generic or vague
- SUBTRACT -1 if Scene 4 is weak, predictable, or too short
- SUBTRACT -1 if any line is too long (over 9 words)
- SUBTRACT -2 if it sounds obviously AI-generated throughout

A script with a specific hook, good tension build, and strong Scene 4 = 7 or 8.
Only truly generic or broken scripts score below 6.
Find the single weakest scene and give one concrete rewrite suggestion.

Return ONLY valid JSON: {{"score": number, "improve": "Scene X: [exact one-line rewrite suggestion]"}}"""}],
        "max_tokens": 120, "temperature": 0.15
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    try:
        result = json.loads(raw.replace("```json","").replace("```","").strip())
    except Exception:
        result = {"score": 7, "improve": "Scene 4: Add a specific number or name to make it more concrete"}
    log(f"Script score: {result.get('score')}/10 — {result.get('improve')}", "success")
    return result


def write_viral_script(topic: str, audience: str, tone: str, channel: str) -> dict:
    """
    Full multi-agent scene-based script pipeline:
    1. Generate 5 hooks → pick best
    2. Write script as JSON array of scenes (5 lines)
    3. Inject pattern interrupts every 2-3 scenes
    4. Score and retry up to 3x if score < 7
    5. Calculate per-scene durations
    6. Generate cinematic keyword per scene
    Returns: scenes[], full_script, hook, score, keywords[], durations[], total_duration
    """
    log("Starting scene-based multi-agent script pipeline...", "tool")
    niche   = YOUTUBE_CHANNELS.get(channel, YOUTUBE_CHANNELS["nyorkies"])["niche"]
    headers = _openai_headers()

    # Step 1: Generate + select best hook
    hooks_result = generate_hooks(topic, audience, channel)
    hooks        = hooks_result.get("hooks", [topic])
    hook_result  = select_best_hook(hooks)
    best_hook    = hook_result.get("best_hook", hooks[0])

    best_result = None

    for attempt in range(3):
        log(f"Script attempt {attempt + 1}/3...", "info")

        # Step 2: Write scene-based script — EXACTLY 5 scenes per content strategy
        if channel == "nyorkies":
            channel_rules = f"""CHANNEL: NyorkieTales — Cute/emotional ANIMAL stories

5-SCENE STRUCTURE (MANDATORY — exactly 5 lines):
Scene 1 HOOK: Use EXACTLY this hook: {best_hook}
  First 2 seconds must make the viewer FREEZE. Emotional, shocking, or irresistibly curious.
Scene 2 SETUP: Introduce the animal with ONE vivid, hyper-specific detail.
  Make the viewer care instantly. "He waited by the door every single day."
Scene 3 BUILD: Raise the tension. Something goes wrong. Use pattern interrupt.
  "But then..." or "No one knew that..." — make them lean in.
Scene 4 TWIST: THE EMOTIONAL PAYOFF — must HIT HARD.
  The moment that changes everything. One sentence that gives chills.
  This is the scene people screenshot and share. Make it UNFORGETTABLE.
Scene 5 CTA: Follow @NyorkieTales for daily animal stories that warm your heart.
  (Last line should echo the hook for loop effect — max retention)

CONTENT RULES:
- ONLY animals — no humans as main characters
- Be SPECIFIC: not "a dog" but "a 3-legged golden retriever named Max"
- Use exact details: numbers, breeds, colors, locations
- Sound like you are texting a friend at 2am about something you just witnessed
- NEVER generic — every sentence must be specific and visual"""
        else:
            channel_rules = f"""CHANNEL: UntoldSelf2 — Money, AI tools, mindset truths

5-SCENE STRUCTURE (MANDATORY — exactly 5 lines):
Scene 1 HOOK: Use EXACTLY this hook: {best_hook}
  No soft openings. Confrontational, controversial, or shocking from word one.
Scene 2 SETUP: State the common belief everyone holds as truth.
  Make the viewer nod: "You think saving money makes you rich."
Scene 3 BUILD: Contradict it hard. Use a pattern interrupt phrase.
  MUST include one of: "Wait..." / "But here is the truth:" / "Nobody tells you this:"
  Hit the pain point so hard the viewer feels personally called out.
Scene 4 TWIST: THE SHOCKING SPECIFIC TRUTH.
  Name a real tool, a specific number, a named strategy. Never vague — EXACT.
  "Rich people use Claude AI to make $500/day in 20 minutes."
  This scene gets saved, shared, and screenshot. Make it HARD-HITTING.
Scene 5 CTA: Follow @UntoldSelf2 for money secrets that actually work.
  (Last line should echo the hook for loop effect — max retention)

CONTENT RULES:
- ONLY human/money/AI content — zero animal content
- Name SPECIFIC tools (ChatGPT, Claude AI, Midjourney) and REAL numbers
- Scene 4 must be the most shocking, specific sentence in the video
- Write like a person who cracked the code and is angry the system hid it"""

        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": f"""{channel_rules}

UNIVERSAL RULES (NON-NEGOTIABLE):
- EXACTLY 5 lines — not 4, not 6, not 7. EXACTLY 5.
- 5 to 8 words per line — short, punchy, conversational
- NO em-dashes, curly quotes, or special Unicode — plain ASCII only
- NO filler words (very, really, just, basically)
- Sound HUMAN — raw, real, like a person not an AI script
- NEVER say "click the link" — no links in Shorts
- Return ONLY a valid JSON array of exactly 5 strings. Zero extra text, no markdown."""},
                {"role": "user", "content": f"Topic: {topic} | Audience: {audience} | Tone: {tone} | Niche: {niche}"}
            ],
            "max_tokens": 350, "temperature": 0.88
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=90)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        try:
            scenes = json.loads(raw.replace("```json","").replace("```","").strip())
            if not isinstance(scenes, list):
                scenes = [raw]
        except Exception:
            # Fallback: split by newlines
            scenes = [l.strip() for l in raw.split("\n") if l.strip()][:5]

        # Ensure scene 1 is always the best hook
        if scenes:
            scenes[0] = best_hook

        # Step 3: Score it
        evaluation  = evaluate_script(scenes)
        score       = evaluation.get("score", 0)
        improvement = evaluation.get("improve", "")
        log(f"Attempt {attempt+1} score: {score}/10", "info")

        if best_result is None or score > best_result.get("score", 0):
            best_result = {"scenes": scenes, "score": score, "improvement": improvement}

        if score >= 7:
            log(f"Script passed! Score: {score}/10", "success")
            break
        else:
            log(f"Score {score}/10 — retrying with improvement hint: {improvement}", "warn")
            # Inject the improvement hint into the next attempt via channel_rules
            # so the LLM knows exactly what to fix
            channel_rules += (f"\n\nPREVIOUS ATTEMPT SCORED {score}/10. REQUIRED FIX:\n{improvement}\nApply this fix while keeping everything else strong.")

    scenes = best_result["scenes"]
    score  = best_result["score"]

    # Step 4: Calculate per-scene durations
    durations      = [estimate_scene_duration(s) for s in scenes]
    total_duration = round(sum(durations), 2)
    # Cap at 58s for YouTube Shorts
    if total_duration > 58:
        scale  = 58 / total_duration
        durations      = [round(d * scale, 2) for d in durations]
        total_duration = 58.0

    log(f"Total video duration: {total_duration}s across {len(scenes)} scenes", "success")

    # Step 5: Generate cinematic keyword per scene
    log("Generating cinematic keywords per scene...", "tool")
    keywords = []
    for scene in scenes:
        kw = generate_scene_keyword(scene, channel)
        keywords.append(kw)
        log(f"  Scene keyword: {kw}", "info")

    full_script = " ".join(scenes)

    return {
        "scenes":         scenes,
        "full_script":    full_script,
        "hook":           best_hook,
        "score":          score,
        "keywords":       keywords,
        "durations":      durations,
        "total_duration": total_duration
    }



def fetch_pexels_footage(keyword: str) -> dict:
    """Fetch a portrait video from Pexels API matching the keyword."""
    log(f"Searching Pexels for: {keyword}", "tool")
    url     = f"https://api.pexels.com/videos/search?query={requests.utils.quote(keyword)}&per_page=10&orientation=portrait&size=medium"
    headers = {"Authorization": PEXELS_API_KEY}
    resp    = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    videos  = resp.json().get("videos", [])

    if not videos:
        return {"error": f"No videos found for: {keyword}"}

    portrait = [v for v in videos if v.get("height", 0) > v.get("width", 0)]
    pool     = portrait if portrait else videos
    video    = pool[0]
    files    = video.get("video_files", [])

    video_url = None
    for check in [
        lambda f: f["height"] >= 1080 and f["height"] > f["width"],
        lambda f: f["height"] >= 720  and f["height"] > f["width"],
        lambda f: f["height"] > f["width"],
    ]:
        match = next((f for f in files if check(f)), None)
        if match:
            video_url = match["link"]
            break

    if not video_url and files:
        video_url = files[0]["link"]

    if not video_url:
        return {"error": "No suitable video file found"}

    log(f"Video found: ID {video['id']}", "success")
    return {"video_url": video_url, "video_id": video["id"]}

def generate_voiceover(script: str) -> dict:
    """
    Generate TTS audio using OpenAI nova voice, upload to Google Drive.
    IMPORTANT: script must be the FULL joined script (all 5 scenes joined with spaces),
    NOT just the hook. The agent must pass full_script from write_viral_script result.
    """
    log("Generating voiceover with OpenAI TTS...", "tool")

    # Guard: if script looks truncated (less than 30 chars) it's probably just the hook
    # Try to detect and warn — the agent should be passing full_script
    if len(script.strip()) < 40:
        log(f"WARNING: Script very short ({len(script)} chars) — agent may have passed only the hook. Full script needed.", "warn")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    # Clean script: remove any JSON artifacts, normalize spacing
    clean_script = script.strip().replace('["', '').replace('"]', '').replace('","', ' ').replace('"', '')
    body = {
        "model": "tts-1-hd",
        "input": clean_script[:4096],
        "voice": "onyx",    # Deep calm male narrator — matches ExcuseErased style
        "speed": 0.9         # Slightly slower for dramatic narration pacing
    }

    resp = requests.post("https://api.openai.com/v1/audio/speech", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    audio_bytes = resp.content
    log(f"Audio generated: {len(audio_bytes) // 1024}KB (tts-1-hd)", "success")

    # Upload to personal Google Drive using YouTube OAuth (jpeezy channel)
    # This uses the user's personal Drive which has 15GB free storage
    log("Uploading audio to personal Google Drive...", "tool")
    try:
        from googleapiclient.discovery import build as gdrive_build
        from googleapiclient.http import MediaIoBaseUpload
        import io as _io

        # Reuse YouTube OAuth credentials — add Drive scope on first auth
        DRIVE_SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/drive.file"
        ]
        ch_config   = YOUTUBE_CHANNELS["nyorkies"]
        token_file  = "youtube_drive_token.pickle"
        creds_file  = ch_config["credentials"]
        creds       = None

        if Path(token_file).exists():
            with open(token_file, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                log("One-time Google Drive auth — browser will open...", "warn")
                flow  = InstalledAppFlow.from_client_secrets_file(creds_file, DRIVE_SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_file, "wb") as f:
                pickle.dump(creds, f)

        drive    = gdrive_build("drive", "v3", credentials=creds)
        filename = f"jpeeezy_audio_{int(time.time())}.mp3"
        media    = MediaIoBaseUpload(_io.BytesIO(audio_bytes), mimetype="audio/mpeg", resumable=False)
        file_md  = {"name": filename, "mimeType": "audio/mpeg", "parents": [GDRIVE_AUDIO_FOLDER_ID]}
        uploaded = drive.files().create(body=file_md, media_body=media, fields="id").execute()
        file_id  = uploaded.get("id")

        # Make publicly readable so Creatomate can fetch it
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"}
        ).execute()

        audio_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        log(f"Audio uploaded to Google Drive: {audio_url}", "success")

        # Get exact audio duration using mutagen (accurate MP3 parsing)
        audio_duration = 0.0
        try:
            from mutagen.mp3 import MP3 as _MP3
            _audio_file = _MP3(_io.BytesIO(audio_bytes))
            audio_duration = round(_audio_file.info.length, 2)
            log(f"Exact audio duration: {audio_duration}s (mutagen)", "success")
        except Exception:
            # Fallback: estimate from file size (tts-1-hd ~48kbps)
            audio_duration = round((len(audio_bytes) * 8) / 48000, 2)
            log(f"Estimated audio duration: {audio_duration}s (fallback)", "warn")

        return {"audio_url": audio_url, "drive_file_id": file_id, "audio_duration": audio_duration}

    except Exception as e:
        log(f"Google Drive upload failed: {e}", "error")
        return {"error": f"Audio upload failed: {str(e)}"}



def generate_scene_image(scene_text: str, scene_index: int, topic: str, channel: str) -> str:
    """
    Generate a scene image using DALL-E 3, tuned per channel visual identity.

    NyorkieTales: Same consistent animal style every video — close-up expressive faces,
    warm cinematic lighting, hyper-emotional. Consistency builds brand recognition.

    UntoldSelf2: Dark cinematic style — same male character identity, neon/city/serious tone.
    Consistent visual identity makes the channel feel like a real brand.
    """
    log(f"Generating AI image for scene {scene_index+1}: {scene_text[:40]}...", "tool")

    import random

    # Scene-role context for better prompt grounding
    scene_roles = ["hook", "setup", "build", "twist", "cta"]
    scene_role   = scene_roles[min(scene_index, 4)]

    if channel == "nyorkies":
        # NyorkieTales: BRIGHT, VIBRANT, LIVELY — like a Nature photographer's best shot.
        # Style reference: vivid daylight colors, crisp detail, animals look ALIVE and joyful.
        # NOT dark, NOT moody — bright, colorful, warm, and emotionally expressive.
        animal_styles = [
            "vibrant wildlife photography, bright natural daylight, ultra-sharp animal portrait close-up, vivid saturated colors, lush green bokeh background, warm sunlight from above, animal looks directly at camera with huge expressive eyes, fur/feathers ultra-detailed, professional nature photography, 9:16 vertical portrait",
            "bright cheerful animal portrait, crisp clear daylight, vivid yellow and green tones, adorable expressive face in sharp focus, soft creamy bokeh of colorful flowers or grass, catch-light sparkle in eyes, ultra-detailed fur texture, feels alive and joyful, 9:16 vertical portrait",
            "hyper-realistic cute animal portrait, brilliant sunshine lighting, vivid warm color palette, enormous sparkling expressive eyes, shallow depth of field with lush colorful background, ultra-HD detail on fur and whiskers, feels like a real magical moment captured, 9:16 vertical portrait",
        ]
        if scene_index == 3:
            # Twist: peak emotional moment — still bright but adds warmth and drama
            style_prefix = "stunning bright animal portrait, golden hour sunshine, warm glowing backlight creates halo effect, ultra-close expressive animal face, vivid saturated colors, eyes glistening with emotion and light, fur glowing, unforgettably heartwarming, 9:16 vertical portrait"
        else:
            style_prefix = random.choice(animal_styles)
        character_context = (
            f"ONLY the animal — absolutely no humans, no text in image. "
            f"Animal face fills 65% of frame. Eyes must be large, bright, and expressive. "
            f"Colors must be VIVID and SATURATED — bright greens, warm golds, clear blues. "
            f"Scene: {scene_role}. Animal feels: {'joyful and hopeful' if scene_role == 'cta' else 'alive, curious, and emotionally present'}."
        )

    else:
        # UntoldSelf2: Pixar/Disney 3D animated CGI style — like Image 5 reference.
        # Expressive relatable 3D characters, warm cinematic lighting, emotionally charged faces.
        # Scenarios: money stress, hustle, revelation moments, confidence, ambition.
        if scene_index == 0:
            # Hook: character looking directly at viewer with intense/confrontational expression
            style_prefix = "Pixar Disney 3D animated style, young confident male character staring directly into camera with intense serious expression, dramatic warm side lighting, clean modern urban background, ultra-detailed 3D render, expressive eyes, cinematic composition, 9:16 vertical portrait"
        elif scene_index == 3:
            # Twist: revelation/shock moment — most dramatic expression
            style_prefix = "Pixar 3D animated CGI, male character experiencing dramatic revelation moment, eyes wide with realization or intensity, warm golden dramatic lighting, cinematic depth of field, emotionally charged expression, high-quality 3D render, 9:16 vertical portrait"
        else:
            # Other scenes: consistent Pixar style, different relatable situations
            untold_styles = [
                "Pixar Disney 3D animation style, relatable young male character in everyday modern scenario, warm ambient lighting, emotionally expressive face, cozy or urban environment, ultra-detailed 3D render, cinematic framing, 9:16 vertical portrait",
                "high-quality Pixar CGI 3D render, young adult male with expressive thoughtful face, warm cinematic lighting, modern lifestyle setting, emotionally resonant storytelling composition, 9:16 vertical portrait",
                "Disney Pixar 3D animated character, young confident man in relatable life moment, warm golden tones, sharp detail, expressive eyes and face, clean cinematic background, professional 3D quality, 9:16 vertical",
            ]
            style_prefix = random.choice(untold_styles)
        character_context = (
            f"A relatable young male Pixar/Disney 3D animated character. NO animals. NO text in image. "
            f"Scene context: {scene_role}. Character emotion matches the scene narrative. "
            f"Pixar style: expressive large eyes, warm skin tones, clean cinematic 3D render. "
            f"Environment feels real and relatable — modern home, city street, or office setting."
        )

    prompt = (
        f"{style_prefix}. "
        f"Scene context: {scene_text}. "
        f"Subject: {character_context}. "
        f"CRITICAL: No text, no captions, no watermarks in the image. "
        f"Vertical 9:16 composition optimized for mobile full-screen viewing."
    )

    headers = _openai_headers()
    body = {
        "model":   "dall-e-3",
        "prompt":  prompt[:4000],
        "n":       1,
        "size":    "1024x1792",  # closest to 9:16 vertical
        "quality": "hd",
        "style":   "vivid"
    }

    try:
        resp = requests.post("https://api.openai.com/v1/images/generations", headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        image_url = resp.json()["data"][0]["url"]
        log(f"  Scene {scene_index+1} image ready", "success")
        return image_url
    except Exception as e:
        log(f"  DALL-E failed for scene {scene_index+1}: {e} — using fallback Pexels", "warn")
        # Fallback to Pexels if DALL-E fails
        try:
            kw   = generate_scene_keyword(scene_text, channel)
            url  = f"https://api.pexels.com/videos/search?query={requests.utils.quote(kw)}&per_page=5&orientation=portrait"
            resp = requests.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
            vids = resp.json().get("videos", [])
            if vids:
                files = vids[0].get("video_files", [])
                if files:
                    return files[0]["link"]
        except Exception:
            pass
        return ""


def generate_all_scene_images(scenes: list, topic: str, channel: str) -> dict:
    """
    Generates DALL-E 3 images for all 5 scenes.
    Kling removed — all animation handled by Creatomate-native zoom/pan/rotate.
    Scene 1 (Hook) and Scene 4 (Twist) get extra-dramatic DALL-E prompts.
    Returns image_urls[] for render_video().
    """
    log(f"Generating DALL-E 3 images for {len(scenes)} scenes ({channel})...", "tool")
    image_urls = []
    for i, scene in enumerate(scenes):
        label = {0: "Hook", 1: "Setup", 2: "Build", 3: "Twist", 4: "CTA"}.get(i, f"Scene {i+1}")
        log(f"  Scene {i+1}: DALL-E image ({label})", "tool")
        dalle_url = generate_scene_image(scene, i, topic, channel)
        image_urls.append(dalle_url if dalle_url else "")
        time.sleep(0.5)  # respect DALL-E rate limits

    successful = sum(1 for u in image_urls if u)
    log(f"DALL-E complete: {successful}/{len(scenes)} images ready", "success")
    return {"image_urls": image_urls, "channel": channel, "mode": "dalle_creatomate_motion"}


def _is_animated_url(url: str) -> bool:
    """Check if a URL points to a video (animated) rather than a static image."""
    if not url:
        return False
    u = url.lower()
    return u.endswith(".mp4") or "klingai" in u or "kling" in u or "lumalabs" in u or "luma" in u


def fetch_scene_videos(keywords: list, fallback_url: str = "") -> list:
    """Fetch Pexels clips as fallback when DALL-E is unavailable."""
    log(f"Fetching {len(keywords)} fallback clips from Pexels...", "tool")
    video_urls = []
    seen_ids   = set()
    for kw in keywords:
        chosen_url = None
        try:
            url  = f"https://api.pexels.com/videos/search?query={requests.utils.quote(kw)}&per_page=10&orientation=portrait&size=medium"
            resp = requests.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            for v in videos:
                if v["id"] not in seen_ids:
                    files = v.get("video_files", [])
                    link  = next(
                        (f["link"] for f in files if f.get("height",0) >= 720 and f.get("height",0) > f.get("width",0)),
                        next((f["link"] for f in files), None)
                    )
                    if link:
                        seen_ids.add(v["id"])
                        chosen_url = link
                        break
        except Exception as e:
            log(f"  Pexels failed for '{kw}': {e}", "warn")
        video_urls.append(chosen_url or fallback_url or "")
    return video_urls


def render_video(video_url: str, audio_url: str, caption: str, channel: str,
                 duration: float = 0, scenes: list = None, durations: list = None,
                 keywords: list = None, image_urls: list = None) -> dict:
    """
    Render multi-scene video via Creatomate source API.

    MICRO-ANIMATION SYSTEM — All 5 scenes use DALL-E images +
    stacked Creatomate-native animations (scale + pan) per scene:
      Scene 1 (Hook)  → aggressive zoom-in + upward drift
      Scene 2 (Setup) → slow zoom + rightward drift
      Scene 3 (Build) → zoom-out reveal + leftward drift
      Scene 4 (Twist) → dramatic surge zoom + diagonal pan
      Scene 5 (CTA)   → gentle zoom + soft drift

    Captions: simple white text + black outline, one per scene, no overlap.
    HD export: 1080x1920, 30fps, 10Mbps bitrate
    """
    log("Building multi-scene Creatomate render (Fake Motion Animation)...", "tool")
    watermark      = YOUTUBE_CHANNELS.get(channel, {}).get("watermark", "@nyorkietales")
    video_duration = round(float(duration), 2) if duration and duration > 0 else 45.0
    video_duration = min(video_duration, 58.0)
    video_duration = max(video_duration, 15.0)
    log(f"Duration: {video_duration}s", "info")

    headers    = {"Authorization": f"Bearer {CREATOMATE_API_KEY}", "Content-Type": "application/json"}
    use_scenes = scenes or [caption]

    # ── Per-scene source routing — all DALL-E images, Kling removed ──
    if image_urls and len(image_urls) == len(use_scenes) and any(image_urls):
        scene_sources = image_urls
        log(f"{channel}: Using DALL-E images with Creatomate micro-animation", "info")
    else:
        use_kws = keywords or [caption] * len(use_scenes)
        if len(use_kws) < len(use_scenes):
            use_kws = (use_kws * ((len(use_scenes) // len(use_kws)) + 1))[:len(use_scenes)]
        scene_sources = fetch_scene_videos(use_kws[:len(use_scenes)], fallback_url=video_url)
        scene_sources = [u if u else video_url for u in scene_sources]
        log(f"{channel}: Using Pexels footage fallback", "warn")

    # ── Per-scene durations — scale word-count durations to actual audio length ──
    if durations and len(durations) == len(use_scenes):
        orig_total = sum(durations)
        if orig_total > 0:
            scale = video_duration / orig_total
            scene_durations = [round(d * scale, 2) for d in durations]
        else:
            per = max(3.0, round(video_duration / len(use_scenes), 2))
            scene_durations = [per] * len(use_scenes)
    else:
        per = max(3.0, round(video_duration / len(use_scenes), 2))
        scene_durations = [per] * len(use_scenes)

    # Enforce minimum 3.0s per scene
    for idx in range(len(scene_durations)):
        if scene_durations[idx] < 3.0:
            scene_durations[idx] = 3.0

    # Ensure total sums exactly to video_duration
    diff = round(video_duration - sum(scene_durations), 2)
    if diff != 0 and scene_durations:
        scene_durations[-1] = round(scene_durations[-1] + diff, 2)

    is_untold = (channel == "jpeezy")
    log(f"Style: {'UntoldSelf storytelling' if is_untold else 'NyorkieTales animal'} | Scenes: {len(use_scenes)} | Durations: {scene_durations}", "info")

    # ── Fake Motion Animation presets ──
    # Scene 1 (index 0): Hook — Kling animated OR strong zoom-in Ken Burns
    # Scene 2 (index 1): Setup  — slow zoom in
    # Scene 3 (index 2): Build  — slow zoom out (creates visual contrast)
    # Scene 4 (index 3): Twist  — Kling animated OR dramatic pan + zoom
    # Scene 5 (index 4): CTA    — subtle horizontal pan

    def _scene_ken_burns(scene_index: int, dur: float) -> list:
        """
        Enhanced Creatomate-native micro-animation — ExcuseErased "Fake Animation" style.
        More dramatic zoom/pan/rotate to simulate camera movement on AI-generated images.
        Creates the illusion of the character being alive: breathing, tilting, swaying.
        Scale starts at 108%+ to prevent black edge gaps during stronger pan/rotate.
        """
        if scene_index == 0:
            # Hook: aggressive zoom-in + upward drift
            # Camera rushes toward subject — maximum energy, grabs attention
            return [
                {"time": "start", "duration": dur, "easing": "ease-in",
                 "type": "scale", "scope": "element",
                 "start_scale": "108%", "end_scale": "125%"},
                {"time": "start", "duration": dur, "easing": "ease-in-out",
                 "type": "pan", "scope": "element",
                 "start_y": "3%", "end_y": "-3%"},
            ]
        elif scene_index == 1:
            # Setup: slow zoom + rightward drift
            # Feels like character slowly turning head — natural curiosity
            return [
                {"time": "start", "duration": dur, "easing": "linear",
                 "type": "scale", "scope": "element",
                 "start_scale": "106%", "end_scale": "116%"},
                {"time": "start", "duration": dur, "easing": "ease-in-out",
                 "type": "pan", "scope": "element",
                 "start_x": "-4%", "end_x": "4%"},
            ]
        elif scene_index == 2:
            # Build: zoom-out reveal + leftward drift
            # Stepping back to see the bigger picture — tension builds
            return [
                {"time": "start", "duration": dur, "easing": "linear",
                 "type": "scale", "scope": "element",
                 "start_scale": "118%", "end_scale": "106%"},
                {"time": "start", "duration": dur, "easing": "ease-in-out",
                 "type": "pan", "scope": "element",
                 "start_x": "4%", "end_x": "-4%"},
            ]
        elif scene_index == 3:
            # Twist: dramatic surge zoom + diagonal pan
            # Maximum kinetic energy — emotional peak, the viral moment
            return [
                {"time": "start", "duration": dur, "easing": "ease-in",
                 "type": "scale", "scope": "element",
                 "start_scale": "106%", "end_scale": "128%"},
                {"time": "start", "duration": dur, "easing": "ease-in-out",
                 "type": "pan", "scope": "element",
                 "start_x": "-5%", "start_y": "4%", "end_x": "5%", "end_y": "-4%"},
            ]
        else:
            # CTA: gentle zoom + soft rightward drift = warm, inviting
            return [
                {"time": "start", "duration": dur, "easing": "ease-out",
                 "type": "scale", "scope": "element",
                 "start_scale": "106%", "end_scale": "113%"},
                {"time": "start", "duration": dur, "easing": "ease-in-out",
                 "type": "pan", "scope": "element",
                 "start_x": "-3%", "end_x": "3%"},
            ]

    elements      = []
    time_offset   = 0.0
    caption_track = 1  # increments per scene — each caption on unique track (no overlap)

    for i, (scene_text, src, dur) in enumerate(zip(use_scenes, scene_sources, scene_durations)):
        motion_label = ["Hook-zoom", "Setup-drift", "Build-reveal", "Twist-surge", "CTA-float"][min(i, 4)]
        log(f"  Scene {i+1}: DALL-E image + Creatomate micro-animation ({motion_label})", "info")

        # ── Background layer: DALL-E image with stacked micro-animations ──
        elements.append({
            "type":       "image",
            "track":      1,
            "time":       time_offset,
            "duration":   dur,
            "source":     src,
            "fit":        "cover",
            "width":      "100%",
            "height":     "100%",
            "animations": _scene_ken_burns(i, dur),
        })

        # ── CAPTION LAYER — Simple white text with black outline ────────
        # Uses text shadow to simulate outline (stroke_color renders as
        # a solid filled rectangle in Creatomate — NOT a text outline).
        # Each caption on its own track to prevent any overlap.
        safe_text = _sanitize_caption(scene_text)
        if safe_text:
            caption_track += 1
            elements.append({
                "type":          "text",
                "track":         caption_track,
                "time":          time_offset,
                "duration":      dur,
                "text":          safe_text.upper(),
                "font_family":   "Montserrat",
                "font_weight":   "800",
                "font_size":     "7 vmin",
                "fill_color":    "#FFFFFF",
                "shadow_color":  "#000000",
                "shadow_blur":   "0",
                "shadow_x":      "0.15 vmin",
                "shadow_y":      "0.15 vmin",
                "x_alignment":   "50%",
                "y_alignment":   "80%",
                "width":         "90%",
                "line_height":   "120%",
            })

        time_offset = round(time_offset + dur, 2)

    # ── Audio — track 200 (far above all visual tracks) ──
    elements.append({
        "type":     "audio",
        "track":    200,
        "time":     0,
        "duration": video_duration,
        "source":   audio_url,
        "volume":   "100%"
    })

    # ── Watermark — small and subtle ──
    elements.append({
        "type":        "text",
        "track":       201,
        "time":        0,
        "duration":    video_duration,
        "text":        watermark,
        "font_family": "Montserrat",
        "font_weight": "500",
        "font_size":   "3 vmin",
        "fill_color":  "rgba(255,255,255,0.45)",
        "x_alignment": "50%",
        "y_alignment": "4.5%",
        "width":       "88%",
    })

    body = {
        "source": {
            "output_format":  "mp4",
            "width":          1080,
            "height":         1920,
            "duration":       video_duration,
            "frame_rate":     30,
            # Full-duration black background — prevents black flash between scenes
            "fill_color":     "#000000",
            # HD quality: 10Mbps bitrate — ensures YouTube processes at 1080p
            "export_settings": {
                "video_bitrate": "10000k",
                "audio_bitrate": "192k"
            },
            "elements": elements
        }
    }

    # ── Submit render to Creatomate — with retry for DNS/network errors ──
    max_retries = 3
    last_error  = None
    for attempt in range(max_retries):
        try:
            resp = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=body, timeout=120)
            resp.raise_for_status()
            result    = resp.json()
            render_id = result[0]["id"] if isinstance(result, list) else result.get("id")
            log(f"Render started: {render_id} | {len(use_scenes)} scenes | ExcuseErased style | {video_duration}s | 1080p HD 8000k", "success")
            return {"render_id": render_id}
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            wait_secs = 3 * (attempt + 1)
            log(f"Creatomate connection failed (attempt {attempt+1}/{max_retries}): {e} — retrying in {wait_secs}s...", "warn")
            time.sleep(wait_secs)
        except Exception as e:
            # Non-retryable error (e.g. 400 bad request)
            raise

    # All retries exhausted
    log(f"Creatomate render failed after {max_retries} attempts: {last_error}", "error")
    return {"error": f"Creatomate render failed after {max_retries} retries: {str(last_error)}"}



def wait_and_get_render_url(render_id: str, max_wait: int = 300) -> dict:
    """Poll Creatomate until render is done, return the final video URL."""
    log(f"Waiting for Creatomate render: {render_id}", "tool")
    headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}"}
    url = f"https://api.creatomate.com/v1/renders/{render_id}"
    waited = 0

    while waited < max_wait:
        time.sleep(15)
        waited += 15
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "")
        log(f"Render status: {status} ({waited}s elapsed)", "info")

        if status == "succeeded":
            render_url = data.get("url", "")
            log(f"Render complete: {render_url}", "success")
            return {"render_url": render_url}
        elif status == "failed":
            return {"error": f"Render failed: {data.get('error_message', 'unknown error')}"}

    return {"error": f"Render timed out after {max_wait}s"}


def upload_to_youtube(render_url: str, title: str, description: str, channel: str) -> dict:
    """Download the rendered video and upload to the correct YouTube channel."""
    log(f"Downloading rendered video from Creatomate...", "tool")

    # Download video to temp file
    resp = requests.get(render_url, stream=True, timeout=120)
    resp.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            tmp.write(chunk)
        tmp_path = tmp.name

    log(f"Video downloaded to {tmp_path}", "success")

    # Get YouTube credentials for this channel
    ch_config = YOUTUBE_CHANNELS.get(channel, YOUTUBE_CHANNELS["nyorkies"])
    creds = _get_youtube_credentials(channel)

    youtube = build("youtube", "v3", credentials=creds)
    tags = ch_config["tags"].split(",")

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        tags,
            "categoryId":  "22",
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
            "notifySubscribers":       True,
        }
    }

    log(f"Uploading to YouTube: {ch_config['display_name']}...", "tool")
    media = MediaFileUpload(tmp_path, chunksize=1024*1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log(f"Upload progress: {pct}%", "info")

    video_id = response.get("id", "")
    video_link = f"https://youtube.com/shorts/{video_id}"
    log(f"Uploaded! {video_link}", "success")

    # Cleanup temp file
    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    return {"youtube_url": video_link, "video_id": video_id}


def mark_topic_done(topic: str, video_url: str) -> dict:
    """Update Google Sheets to mark the topic as done."""
    log(f"Marking topic as done in Google Sheets: {topic}", "tool")
    try:
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds  = SACredentials.from_service_account_file(GSHEETS_SERVICE_ACCOUNT_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(GOOGLE_SHEET_ID).worksheet("Topics")
        rows   = sheet.get_all_records()

        for i, row in enumerate(rows, start=2):  # row 1 is header
            if str(row.get("topic", "")).strip().lower() == topic.strip().lower():
                sheet.update(f"D{i}", [["done"]])              # status
                sheet.update(f"F{i}", [[str(date.today())]])   # posted_date
                sheet.update(f"G{i}", [[video_url]])           # video_url
                log(f"Sheet updated for: {topic}", "success")
                return {"updated": True}

        return {"updated": False, "message": "Topic not found in sheet"}
    except Exception as e:
        return {"updated": False, "error": str(e)}


def list_pending_topics() -> dict:
    """List all pending topics in the sheet."""
    log("Fetching all pending topics...", "tool")
    try:
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds  = SACredentials.from_service_account_file(GSHEETS_SERVICE_ACCOUNT_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(GOOGLE_SHEET_ID).worksheet("Topics")
        rows   = sheet.get_all_records()
        pending = [r for r in rows if str(r.get("status","")).strip().lower() == "pending"]
        return {
            "count": len(pending),
            "topics": [{"topic": r["topic"], "channel": r.get("channel","nyorkies")} for r in pending]
        }
    except Exception as e:
        return {"count": 0, "error": str(e)}


# ════════════════════════════════════════════════════════════════
#  YOUTUBE AUTH HELPER
# ════════════════════════════════════════════════════════════════

def _get_youtube_credentials(channel: str):
    """Handle YouTube OAuth2 — loads saved token or runs auth flow."""
    ch_config    = YOUTUBE_CHANNELS[channel]
    token_file   = ch_config["token"]
    creds_file   = ch_config["credentials"]
    creds        = None

    if Path(token_file).exists():
        with open(token_file, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log(f"Refreshing YouTube token for {channel}...", "info")
            creds.refresh(Request())
        else:
            log(f"First-time YouTube auth for {channel} — browser will open...", "warn")
            if not Path(creds_file).exists():
                raise FileNotFoundError(
                    f"Missing {creds_file}. Download from Google Cloud Console → APIs → Credentials → OAuth 2.0 Client IDs"
                )
            flow  = InstalledAppFlow.from_client_secrets_file(creds_file, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "wb") as f:
            pickle.dump(creds, f)

    return creds



# ════════════════════════════════════════════════════════════════
#  SELF-IMPROVING SYSTEM — learns from YouTube analytics
# ════════════════════════════════════════════════════════════════

PERFORMANCE_LOG = "performance_log.json"

def log_video_performance(topic: str, hook: str, script_score: int, channel: str, video_id: str) -> None:
    """Save video metadata so we can compare against real analytics later."""
    try:
        logs = []
        if Path(PERFORMANCE_LOG).exists():
            with open(PERFORMANCE_LOG, 'r') as f:
                logs = json.load(f)
        logs.append({
            "date":          str(date.today()),
            "topic":         topic,
            "hook":          hook,
            "script_score":  script_score,
            "channel":       channel,
            "video_id":      video_id,
            "views":         None,
            "likes":         None,
            "avg_watch_pct": None,
            "issues_noted":  []
        })
        with open(PERFORMANCE_LOG, 'w') as f:
            json.dump(logs, f, indent=2)
        log(f"Performance logged for video: {video_id}", "info")
    except Exception as e:
        log(f"Performance log error: {e}", "warn")



def delete_drive_file(file_id: str) -> None:
    """Delete an audio file from Google Drive by ID to free storage."""
    if not file_id:
        return
    try:
        from googleapiclient.discovery import build as gdrive_build
        import pickle as _pickle
        DRIVE_SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/drive.file"
        ]
        token_file = "youtube_drive_token.pickle"
        creds      = None
        if Path(token_file).exists():
            with open(token_file, "rb") as f:
                creds = _pickle.load(f)
        if creds and creds.valid:
            drive = gdrive_build("drive", "v3", credentials=creds)
            drive.files().delete(fileId=file_id).execute()
            log(f"🗑️  Deleted audio file from Drive: {file_id}", "info")
    except Exception as e:
        log(f"Drive cleanup skipped: {e}", "warn")


def generate_dynamic_hashtags(topic: str, script: str, channel: str) -> dict:
    """Generate viral topic-specific hashtags based on the script content."""
    log("Generating dynamic hashtags...", "tool")
    niche        = YOUTUBE_CHANNELS.get(channel, YOUTUBE_CHANNELS["nyorkies"])["niche"]
    channel_base = (
        "#shorts #viral #trending #fyp #foryou #foryoupage #youtube #youtubeshorts"
        if channel == "jpeezy"
        else "#shorts #viral #trending #fyp #foryou #animals #cuteanimals #pets #animalstory"
    )
    headers = _openai_headers()
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": f"""Generate 15 viral topic-specific YouTube Shorts hashtags.

Topic: {topic}
Niche: {niche}
Script: {script[:300]}

Rules:
- Mix broad viral tags + niche tags + actual search terms people use
- No spaces in hashtags, CamelCase or lowercase
- Do NOT include: #shorts #viral #trending (added separately)
- Return ONLY a space-separated string of 15 hashtags starting with #
- Example: #fitness #gymlife #weightloss #motivation #workout

Return ONLY the hashtag string."""}],
        "max_tokens": 150, "temperature": 0.7
    }
    resp         = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    dynamic_tags = resp.json()["choices"][0]["message"]["content"].strip()
    full_hashtags = dynamic_tags + " " + channel_base
    tags_list     = [t.lstrip("#") for t in full_hashtags.split() if t.startswith("#")]
    tags_csv      = ",".join(tags_list)[:500]
    log(f"Hashtags: {dynamic_tags[:80]}...", "success")
    return {"hashtags_string": full_hashtags, "tags_csv": tags_csv}


def fetch_and_update_analytics(channel: str = "nyorkies") -> dict:
    """Fetch real YouTube analytics for logged videos and update performance log."""
    log("Fetching YouTube analytics for performance learning...", "tool")
    try:
        creds   = _get_youtube_credentials(channel)
        youtube = build("youtube", "v3", credentials=creds)

        if not Path(PERFORMANCE_LOG).exists():
            return {"message": "No performance log found yet. Run some videos first."}

        with open(PERFORMANCE_LOG, 'r') as f:
            logs = json.load(f)

        updated = 0
        for entry in logs:
            if entry.get("video_id") and entry.get("views") is None:
                try:
                    resp = youtube.videos().list(
                        part="statistics",
                        id=entry["video_id"]
                    ).execute()
                    items = resp.get("items", [])
                    if items:
                        stats = items[0]["statistics"]
                        entry["views"]  = int(stats.get("viewCount",  0))
                        entry["likes"]  = int(stats.get("likeCount",  0))
                        updated += 1
                except Exception:
                    pass

        with open(PERFORMANCE_LOG, 'w') as f:
            json.dump(logs, f, indent=2)

        log(f"Updated analytics for {updated} videos", "success")
        return {"updated": updated, "total_logged": len(logs)}
    except Exception as e:
        return {"error": str(e)}


def get_performance_insights() -> dict:
    """Analyze performance log to extract what hooks/topics/tones perform best."""
    log("Analyzing performance data for insights...", "tool")
    try:
        if not Path(PERFORMANCE_LOG).exists():
            return {"message": "No performance data yet. Need at least 5 videos with view data."}

        with open(PERFORMANCE_LOG, 'r') as f:
            logs = json.load(f)

        # Only analyze entries with real view data
        with_data = [e for e in logs if e.get("views") is not None]
        if len(with_data) < 3:
            return {"message": f"Only {len(with_data)} videos with analytics. Need at least 3 to find patterns."}

        # Sort by views
        sorted_logs = sorted(with_data, key=lambda x: x.get("views", 0), reverse=True)
        top3    = sorted_logs[:3]
        bottom3 = sorted_logs[-3:]

        # Extract patterns from top performers
        top_hooks    = [e["hook"] for e in top3]
        top_topics   = [e["topic"] for e in top3]
        top_scores   = [e["script_score"] for e in top3]
        avg_top_views = sum(e["views"] for e in top3) // len(top3)

        insights = {
            "total_videos":      len(with_data),
            "avg_top_views":     avg_top_views,
            "top_performing_hooks":   top_hooks,
            "top_performing_topics":  top_topics,
            "avg_quality_score_top":  sum(top_scores) // len(top_scores),
            "worst_performing_topics": [e["topic"] for e in bottom3],
            "recommendation": f"Hooks with words like: {', '.join(set(w for h in top_hooks for w in h.split()[:3]))} perform best. Avg quality score of top videos: {sum(top_scores)//len(top_scores)}/10"
        }

        log(f"Insights ready — top performer: {top3[0]['topic']} ({top3[0]['views']} views)", "success")
        return insights

    except Exception as e:
        return {"error": str(e)}


def get_ai_content_recommendation() -> dict:
    """Use Claude to recommend next topics based on performance data."""
    log("Getting AI content recommendations based on performance...", "tool")
    insights = get_performance_insights()

    if "error" in insights or "message" in insights:
        return insights

    try:
        client = _anthropic_client()
        prompt = f"""You are a YouTube Shorts growth strategist.

Based on this channel performance data:
{json.dumps(insights, indent=2)}

Recommend 5 new video topics that will likely outperform previous content.
For each topic suggest: topic, audience, tone, channel (jpeezy or nyorkies).

Return ONLY valid JSON array:
[{{"topic": "...", "audience": "...", "tone": "...", "channel": "..."}}]"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()
        recommendations = json.loads(raw.replace("```json","").replace("```","").strip())
        log(f"AI recommended {len(recommendations)} new topics", "success")
        return {"recommendations": recommendations}
    except Exception as e:
        return {"error": str(e)}


def report_video_issues(video_id: str, issues: list) -> dict:
    """Log specific issues noticed in a video for self-improvement learning."""
    try:
        logs = []
        if Path(PERFORMANCE_LOG).exists():
            with open(PERFORMANCE_LOG, 'r') as f:
                logs = json.load(f)
        for entry in logs:
            if entry.get("video_id") == video_id:
                entry["issues_noted"] = issues
                break
        with open(PERFORMANCE_LOG, 'w') as f:
            json.dump(logs, f, indent=2)
        # Also append to a lessons-learned file
        lessons_file = "lessons_learned.json"
        lessons = []
        if Path(lessons_file).exists():
            with open(lessons_file, 'r') as f:
                lessons = json.load(f)
        lessons.append({
            "date":     str(date.today()),
            "video_id": video_id,
            "issues":   issues
        })
        with open(lessons_file, 'w') as f:
            json.dump(lessons, f, indent=2)
        log(f"Issues logged for self-improvement: {issues}", "info")
        return {"logged": True, "issues": issues}
    except Exception as e:
        return {"error": str(e)}


def get_lessons_learned() -> dict:
    """Return all logged issues and lessons from previous videos to avoid repeating mistakes."""
    try:
        lessons_file = "lessons_learned.json"
        if not Path(lessons_file).exists():
            return {"lessons": [], "message": "No lessons logged yet."}
        with open(lessons_file, 'r') as f:
            lessons = json.load(f)
        # Summarize recurring issues
        all_issues = [i for l in lessons for i in l.get("issues", [])]
        from collections import Counter
        common = Counter(all_issues).most_common(5)
        return {
            "total_videos_with_issues": len(lessons),
            "most_common_issues": [{"issue": k, "count": v} for k, v in common],
            "all_lessons": lessons[-10:]  # last 10
        }
    except Exception as e:
        return {"error": str(e)}



# ════════════════════════════════════════════════════════════════
#  KLING AI — Image to Video Animation
# ════════════════════════════════════════════════════════════════

def _kling_jwt_token() -> str:
    """Generate JWT token for Kling API authentication."""
    import time, json
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode()).rstrip(b"=").decode()
    now     = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": KLING_ACCESS_KEY,
        "exp": now + 1800,
        "nbf": now - 5
    }).encode()).rstrip(b"=").decode()
    sig_input = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(KLING_SECRET_KEY.encode(), sig_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


def _rehost_image_for_kling(image_url: str) -> str:
    """
    Kling rejects DALL-E temporary CDN URLs and Google Drive redirect URLs (400 error).
    Strategy: download image, upload to imgbb (free, no API key needed for anonymous upload),
    which returns a permanent direct image URL that Kling accepts.
    Fallback chain: imgbb → freeimage.host → original URL.
    """
    log("Re-hosting image for Kling compatibility...", "tool")
    try:
        # Download DALL-E image bytes
        img_resp = requests.get(image_url, timeout=45)
        img_resp.raise_for_status()
        img_bytes = img_resp.content
        log(f"  Image downloaded: {len(img_bytes)//1024}KB", "info")
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        # ── Host 1: imgbb — free image host, returns permanent direct URL ──
        # Requires API key — uses the global IMGBB_API_KEY if set, else tries anonymous
        try:
            imgbb_key = globals().get("IMGBB_API_KEY", "")
            imgbb_url = "https://api.imgbb.com/1/upload"
            params    = {"key": imgbb_key} if imgbb_key else {}
            upload = requests.post(
                imgbb_url,
                params=params,
                data={"image": img_b64, "expiration": 3600},
                timeout=30
            )
            if upload.status_code == 200:
                direct_url = upload.json()["data"]["url"]
                log(f"  Image hosted on imgbb: {direct_url}", "success")
                return direct_url
        except Exception as e1:
            log(f"  imgbb failed ({e1}), trying freeimage.host...", "warn")

        # ── Host 2: freeimage.host — no API key required ──
        try:
            upload = requests.post(
                "https://freeimage.host/api/1/upload",
                data={"key": "6d207e02198a847aa98d0a2a901485a5", "source": img_b64, "format": "json"},
                timeout=30
            )
            if upload.status_code == 200:
                direct_url = upload.json()["image"]["url"]
                log(f"  Image hosted on freeimage.host: {direct_url}", "success")
                return direct_url
        except Exception as e2:
            log(f"  freeimage.host failed ({e2}), using original URL", "warn")

        # ── Fallback: original DALL-E URL (valid ~1hr, may still work) ──
        log("  All re-hosting failed — using original DALL-E URL", "warn")
        return image_url

    except Exception as e:
        log(f"  Image download/re-host failed ({e}) — using original URL", "warn")
        return image_url


def animate_image_with_kling(image_url: str, motion_prompt: str, duration: int = 5) -> str:
    """
    LEGACY — Kling removed from main pipeline. This function is kept for manual use only.
    The main pipeline now uses Creatomate-native animations exclusively.
    Returns empty string immediately if called from the main agent pipeline.
    """
    if not KLING_ACCESS_KEY or KLING_ACCESS_KEY == "PASTE_KLING_ACCESS_KEY":
        log("Kling not configured — skipping animation", "warn")
        return ""

    # Re-host DALL-E image to stable Google Drive URL — fixes Kling 400 Bad Request
    stable_image_url = _rehost_image_for_kling(image_url)

    log(f"Animating image with Kling: {motion_prompt[:50]}...", "tool")
    token   = _kling_jwt_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json"
    }

    # Submit image-to-video task
    body = {
        "model_name":  "kling-v1-6",
        "image_url":    stable_image_url,
        "prompt":       motion_prompt,
        "duration":     str(duration),
        "aspect_ratio": "9:16",
        "mode":         "std",
        "cfg_scale":    0.5
    }

    try:
        resp = requests.post(
            f"{KLING_API_BASE}/v1/videos/image2video",
            headers=headers,
            json=body,
            timeout=30
        )
        resp.raise_for_status()
        data    = resp.json()
        task_id = data.get("data", {}).get("task_id", "")
        if not task_id:
            log(f"Kling task creation failed: {data}", "warn")
            return ""

        log(f"Kling task started: {task_id}", "info")

        # Poll for completion (max 3 minutes)
        for attempt in range(18):
            time.sleep(10)
            poll = requests.get(
                f"{KLING_API_BASE}/v1/videos/image2video/{task_id}",
                headers={"Authorization": f"Bearer {_kling_jwt_token()}"},
                timeout=20
            )
            poll.raise_for_status()
            poll_data = poll.json().get("data", {})
            status    = poll_data.get("task_status", "")
            log(f"Kling status: {status} ({(attempt+1)*10}s)", "info")

            if status == "succeed":
                videos = poll_data.get("task_result", {}).get("videos", [])
                if videos:
                    video_url = videos[0].get("url", "")
                    log(f"Kling animation done: {video_url[:60]}", "success")
                    return video_url
                break
            elif status == "failed":
                log(f"Kling task failed: {poll_data.get('task_status_msg','')}", "warn")
                return ""

        log("Kling timed out — using static image fallback", "warn")
        return ""

    except Exception as e:
        log(f"Kling error: {e}", "warn")
        return ""


def generate_motion_prompt(scene_text: str, channel: str, scene_index: int = 0) -> str:
    """
    Generate a Kling motion prompt tuned to the scene's narrative role.
    Scene 1 (Hook): dynamic, attention-grabbing motion
    Scene 4 (Twist): dramatic, emotionally charged motion
    """
    import random
    if channel == "nyorkies":
        if scene_index == 0:
            # Hook: immediate attention-grabbing movement
            motions = [
                "Animal turns head and looks directly into camera with big emotional eyes, slow push-in zoom, warm backlight blooms, fur detail sharpens",
                "Camera slowly drifts toward animal face, animal blinks slowly with soulful eyes, soft bokeh tightens, warm golden light pulses gently",
                "Animal ears perk up, eyes widen with curiosity, gentle cinematic zoom-in, soft natural light, intimate close-up",
            ]
        else:
            # Twist (scene 4): peak emotional moment
            motions = [
                "Slow dramatic zoom-in on animal face, eyes glisten with emotion, warm backlight intensifies, cinematic depth of field",
                "Animal looks up with hopeful eyes, camera gently pushes in, warm golden rays break through background, emotional peak",
                "Gentle camera drift toward animal, animal breathes softly, subtle light shift from cool to warm, heartwarming atmosphere",
            ]
    else:
        if scene_index == 0:
            # Hook: confrontational direct energy
            motions = [
                "Character turns and looks directly into camera with intense gaze, slow push-in zoom, dramatic side light sharpens on face",
                "Camera slowly approaches character face, character's expression becomes more serious, neon light flickers subtly, high tension",
                "Slow cinematic zoom toward serious male face, direct eye contact, dark background, atmosphere becomes more intense",
            ]
        else:
            # Twist (scene 4): dramatic revelation
            motions = [
                "Character reacts to shocking revelation, subtle expression change, dramatic light shift, slow zoom-in, cinematic intensity",
                "Slow push-in on character, atmospheric neon light pulses, expression hardens with determination, powerful and dramatic",
                "Camera slowly drifts in, character looks down then up with intensity, light contrast increases, emotional peak moment",
            ]
    return random.choice(motions)


def animate_all_scenes(image_urls: list, scenes: list, channel: str) -> list:
    """
    Animate all scene images using Kling AI.
    Falls back to original static image URL if Kling fails for any scene.
    Returns list of video URLs (or image URLs as fallback).
    """
    if not KLING_ACCESS_KEY or KLING_ACCESS_KEY == "PASTE_KLING_ACCESS_KEY":
        log("Kling not configured — using static images with Ken Burns", "warn")
        return []

    log(f"Animating {len(image_urls)} scenes with Kling AI...", "tool")
    animated_urls = []
    total_cost_estimate = len(image_urls) * 0.15  # rough estimate

    send_telegram(f"🎬 Animating {len(image_urls)} scenes with Kling AI (~${total_cost_estimate:.2f} credits)...")

    for i, (img_url, scene_text) in enumerate(zip(image_urls, scenes)):
        if not img_url:
            animated_urls.append("")
            continue
        log(f"Animating scene {i+1}/{len(image_urls)}: {scene_text[:40]}", "tool")
        motion = generate_motion_prompt(scene_text, channel, scene_index=i)
        video_url = animate_image_with_kling(img_url, motion, duration=5)
        if video_url:
            animated_urls.append(video_url)
        else:
            log(f"Scene {i+1} animation failed — using static image", "warn")
            animated_urls.append(img_url)  # fallback to static

    success_count = sum(1 for u in animated_urls if u)
    log(f"Kling animation complete: {success_count}/{len(image_urls)} scenes animated", "success")
    return animated_urls


# ════════════════════════════════════════════════════════════════
#  LUMA AI — Image to Video (Simple Subtle Motion)
#  Primary animation provider — facial expressions, eye movement,
#  head tilt, hair/hand motion without full animation.
#  Fallback chain: Luma → Kling → Creatomate Ken Burns (static)
# ════════════════════════════════════════════════════════════════

def animate_with_luma(image_url: str, motion_prompt: str, duration: int = 5) -> str:
    """
    Animate a still image using Luma AI Dream Machine.
    Creates subtle motion: facial expressions, eye blinks, head tilts,
    breathing, hand gestures — perfect for "Fake Animation" style.

    Returns video URL on success, empty string on failure.
    """
    luma_key = _get_key("LUMA_API_KEY") or globals().get("LUMA_API_KEY", "")
    if not luma_key:
        log("Luma AI not configured — skipping", "warn")
        return ""

    log(f"Animating with Luma AI: {motion_prompt[:50]}...", "tool")

    # Step 1: Re-host image to a stable URL (Luma also rejects DALL-E temp URLs)
    stable_url = _rehost_image_for_kling(image_url)  # reuse existing re-host logic

    # Step 2: Submit generation task to Luma API
    headers = {
        "Authorization": f"Bearer {luma_key}",
        "Content-Type": "application/json"
    }

    body = {
        "prompt": motion_prompt,
        "keyframes": {
            "frame0": {
                "type": "image",
                "url": stable_url
            }
        },
        "aspect_ratio": "9:16",
        "loop": False
    }

    try:
        resp = requests.post(
            "https://api.lumalabs.ai/dream-machine/v1/generations",
            headers=headers,
            json=body,
            timeout=30
        )
        resp.raise_for_status()
        data    = resp.json()
        task_id = data.get("id", "")
        if not task_id:
            log(f"Luma task creation failed: {data}", "warn")
            return ""

        log(f"Luma task started: {task_id}", "info")

        # Step 3: Poll for completion (max 4 minutes — Luma is typically ~60-120s)
        for attempt in range(24):
            time.sleep(10)
            poll = requests.get(
                f"https://api.lumalabs.ai/dream-machine/v1/generations/{task_id}",
                headers=headers,
                timeout=20
            )
            poll.raise_for_status()
            poll_data = poll.json()
            status    = poll_data.get("state", "")
            log(f"Luma status: {status} ({(attempt+1)*10}s)", "info")

            if status == "completed":
                video_data = poll_data.get("assets", {})
                video_url  = video_data.get("video", "")
                if video_url:
                    log(f"Luma animation done: {video_url[:60]}", "success")
                    return video_url
                break
            elif status == "failed":
                fail_reason = poll_data.get("failure_reason", "unknown")
                log(f"Luma task failed: {fail_reason}", "warn")
                return ""

        log("Luma timed out — falling back to static image", "warn")
        return ""

    except Exception as e:
        log(f"Luma error: {e}", "warn")
        return ""


def animate_key_scenes(image_urls: list, scenes: list, channel: str) -> list:
    """
    Animate ONLY key scenes (Hook=0, Twist=3) using the best available provider.
    Fallback chain per scene: Luma AI → Kling AI → original static image.
    Non-key scenes keep their DALL-E image (animated by Creatomate Ken Burns).

    This is cost-effective: only 2 out of 5 scenes get API animation,
    and those are the highest-impact scenes for viewer retention.
    """
    log(f"Animating key scenes (Hook + Twist) for {channel}...", "tool")
    result_urls = list(image_urls)  # copy — start with all DALL-E images

    # Scenes to animate: 0 (Hook) and 3 (Twist)  — highest viewer impact
    key_scenes = [0, 3]

    for idx in key_scenes:
        if idx >= len(image_urls) or not image_urls[idx]:
            continue

        scene_text = scenes[idx] if idx < len(scenes) else ""
        motion = generate_motion_prompt(scene_text, channel, scene_index=idx)
        log(f"  Scene {idx+1}: Trying Luma AI for subtle motion...", "tool")

        # Try Luma AI first
        video_url = animate_with_luma(image_urls[idx], motion, duration=5)

        # Fallback to Kling if Luma fails
        if not video_url:
            log(f"  Scene {idx+1}: Luma failed, trying Kling...", "info")
            video_url = animate_image_with_kling(image_urls[idx], motion, duration=5)

        if video_url:
            result_urls[idx] = video_url
            log(f"  Scene {idx+1}: Animated ✓", "success")
        else:
            log(f"  Scene {idx+1}: All animation providers failed — using static + Ken Burns", "warn")

    animated_count = sum(1 for i in key_scenes if i < len(result_urls) and result_urls[i] != image_urls[i])
    log(f"Key scene animation: {animated_count}/{len(key_scenes)} scenes animated", "success")
    return result_urls


# ════════════════════════════════════════════════════════════════
#  NOTIFICATION SYSTEM — Email + Telegram alerts
# ════════════════════════════════════════════════════════════════

# ── Telegram (loaded from credentials.py) ──────────────────────
# ────────────────────────────────────────────────────────────────


def send_telegram(message: str) -> bool:
    """Send a Telegram message via bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram not configured — skipping", "warn")
        return False
    # Strip HTML tags for plain text fallback
    import re as _re
    plain = _re.sub(r"<[^>]+>", "", message).strip()
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": plain}
        resp = requests.post(url, json=data, timeout=15)
        if resp.status_code == 200:
            log("Telegram sent ✅", "success")
            return True
        else:
            rj = resp.json()
            err_desc = rj.get("description", resp.text[:100])
            if "bot was blocked" in err_desc:
                log("Telegram: you blocked the bot — unblock it in Telegram", "warn")
            elif "chat not found" in err_desc:
                log("Telegram: wrong chat_id — send /start to your bot first", "warn")
            elif "Unauthorized" in err_desc:
                log("Telegram: invalid token — check @BotFather for correct token", "warn")
            else:
                log(f"Telegram failed: {err_desc}", "warn")
            return False
    except Exception as e:
        log(f"Telegram error: {e}", "warn")
        return False


def send_email(subject: str, body: str) -> bool:
    """Email notifications disabled — using Telegram only."""
    return False

def notify_success(channel_name: str, topic: str, youtube_url: str, score: int = 0) -> None:
    """Send success notification after a video is uploaded."""
    msg_tg = (
        f"✅ <b>Video Uploaded!</b>\n"
        f"📺 Channel: {channel_name}\n"
        f"🎯 Topic: {topic}\n"
        f"⭐ Script score: {score}/10\n"
        f"🔗 {youtube_url}\n"
        f"🕐 {datetime.now().strftime('%b %d %I:%M %p')}"
    )
    msg_email = f"""
    <h2>✅ New Video Uploaded — {channel_name}</h2>
    <p><b>Topic:</b> {topic}</p>
    <p><b>Script Score:</b> {score}/10</p>
    <p><b>YouTube URL:</b> <a href="{youtube_url}">{youtube_url}</a></p>
    <p><b>Time:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
    """
    send_telegram(msg_tg)
    send_email(f"✅ [{channel_name}] New video uploaded: {topic[:50]}", msg_email)
    log(f"Notifications sent for: {topic}", "info")


def notify_error(channel_name: str, topic: str, error: str, step: str = "") -> None:
    """Send error notification when pipeline fails."""
    msg_tg = (
        f"❌ <b>Pipeline Error!</b>\n"
        f"📺 Channel: {channel_name}\n"
        f"🎯 Topic: {topic}\n"
        f"💥 Step: {step}\n"
        f"⚠️ Error: {error[:200]}\n"
        f"🕐 {datetime.now().strftime('%b %d %I:%M %p')}"
    )
    msg_email = f"""
    <h2>❌ Pipeline Error — {channel_name}</h2>
    <p><b>Topic:</b> {topic}</p>
    <p><b>Failed at step:</b> {step}</p>
    <p><b>Error:</b> {error}</p>
    <p><b>Time:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
    <p><i>Check your terminal or logs for full details.</i></p>
    """
    send_telegram(msg_tg)
    send_email(f"❌ [{channel_name}] Pipeline error at {step}", msg_email)
    log(f"Error notifications sent for: {topic}", "warn")


def notify_daily_schedule(schedule_times: dict) -> None:
    """Send morning notification with today's posting schedule."""
    lines = ["📅 <b>Today\'s posting schedule:</b>\n"]
    for ch_key, post_time in schedule_times.items():
        ch = YOUTUBE_CHANNELS.get(ch_key, {})
        lines.append(f"  {ch.get('display_name','?')} → {post_time}")
    msg_tg = "\n".join(lines)
    send_telegram(msg_tg)


def auto_generate_topics(channel: str, count: int = 10) -> dict:
    """Auto-generate trending viral topics for a channel and add to Google Sheets."""
    log(f"Auto-generating {count} trending topics for {channel}...", "tool")
    ch    = YOUTUBE_CHANNELS.get(channel, {})
    niche = ch.get("niche", "general")
    fmt   = ch.get("script_format", "mixed")

    try:
        ai_client = _anthropic_client()
        prompt    = f"""You are a viral YouTube Shorts content strategist for 2025-2026.
Channel niche: {niche}
Script format: {fmt}

Generate {count} highly viral, UNIQUE video topics. Each topic must be ready to become a
scroll-stopping YouTube Short that feels HUMAN, not AI-generated.

{"NYORKIETALES ANIMAL CHANNEL RULES:" if channel == "nyorkies" else "UNTOLDSELF2 MONEY/AI/MINDSET CHANNEL RULES:"}

{"- Topics must be specific emotional animal stories — not generic 'cute dog' content" if channel == "nyorkies" else "- Topics must be money mindset, AI tools, or psychological/controversial truths"}
{"- Good: 'The golden retriever who refused to leave his owner's hospital room for 11 days'" if channel == "nyorkies" else "- Good: 'Why saving money is making you poor (what banks don't tell you)'"}
{"- Bad: 'A cute puppy story' / 'An animal adventure'" if channel == "nyorkies" else "- Bad: 'Money tips' / 'How to make money online'"}
{"- Each topic must have a clear emotional payoff: heartwarming, shocking, tear-jerking, or surprising" if channel == "nyorkies" else "- Each topic must be controversial or counterintuitive — challenges a common belief"}
{"- Source inspiration from: viral animal videos on TikTok/YouTube, r/aww, r/MadeMeSmile, real news stories" if channel == "nyorkies" else "- Source inspiration from: r/personalfinance, financial Twitter/X threads, AI tool discoveries, money psychology research"}
{"- NEVER generic: every topic sounds like a specific TRUE story that happened" if channel == "nyorkies" else "- NEVER generic: every topic names a specific strategy, tool, or psychological truth"}

HOOK POTENTIAL TEST — before including a topic ask:
- Can I write a 5-word hook for this that stops a scroll?
- Does Scene 4 (the twist) hit emotionally or intellectually hard?
- Would someone send this to a friend?
If no to any — replace it.

Alternate content styles across the {count} topics for variety:
{"Animals: mix of dogs, cats, birds, wild animals, marine animals" if channel == "nyorkies" else "Content: mix of AI tools, money mindset, psychological truths, controversial facts"}

Return ONLY valid JSON array (no markdown, no extra text):
[{{"topic": "...", "audience": "...", "tone": "..."}}]"""

        resp   = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = resp.content[0].text.strip()
        topics = json.loads(raw.replace("```json","").replace("```","").strip())

        scopes    = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
        gs_creds  = SACredentials.from_service_account_file(GSHEETS_SERVICE_ACCOUNT_FILE, scopes=scopes)
        gs_client = gspread.authorize(gs_creds)
        sheet     = gs_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Topics")

        rows_added = 0
        for t in topics:
            sheet.append_row([
                t.get("topic",""), t.get("audience","general"),
                t.get("tone","energetic"), "pending", channel, "", ""
            ])
            rows_added += 1

        log(f"Added {rows_added} new topics for {channel}", "success")
        return {"added": rows_added, "channel": channel}

    except Exception as e:
        log(f"Auto-topic generation failed: {e}", "error")
        return {"error": str(e)}


def check_and_refill_topics(channel: str, min_threshold: int = 5) -> dict:
    """Check pending topic count for a channel. Auto-refill if below threshold."""
    try:
        scopes    = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
        gs_creds  = SACredentials.from_service_account_file(GSHEETS_SERVICE_ACCOUNT_FILE, scopes=scopes)
        gs_client = gspread.authorize(gs_creds)
        sheet     = gs_client.open_by_key(GOOGLE_SHEET_ID).worksheet("Topics")
        rows      = sheet.get_all_records()
        pending   = [r for r in rows
                     if str(r.get("status","")).strip().lower() == "pending"
                     and str(r.get("channel","")).strip().lower() == channel.lower()]
        count = len(pending)
        log(f"{channel}: {count} pending topics remaining", "info")
        if count < min_threshold:
            log(f"{channel}: low on topics — auto-generating 10 more", "warn")
            result = auto_generate_topics(channel, count=10)
            ch_name = YOUTUBE_CHANNELS.get(channel, {}).get("display_name", channel)
            send_telegram(f"📋 Auto-generated 10 new topics for {ch_name} (was running low)")
            return {"refilled": True, "was": count, "added": result.get("added", 0)}
        return {"refilled": False, "pending_count": count}
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS FOR CLAUDE
# ════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "get_pending_topic",
        "description": "Fetch the next pending topic from Google Sheets. Pass channel to get a topic specific to that channel (nyorkies or jpeezy).",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Required: nyorkies (animal content) or jpeezy (stories/AI money) — filters to that channel only"}
            },
            "required": []
        }
    },
    {
        "name": "write_viral_script",
        "description": "Full multi-agent scene-based script pipeline. Generates 5 hooks, selects best, writes 5-scene script with pattern interrupts, scores it (retries if <7/10), calculates per-scene durations, generates cinematic keywords per scene. Returns: scenes[], full_script, hook, score, keywords[], durations[], total_duration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic":    {"type": "string", "description": "The video topic"},
                "audience": {"type": "string", "description": "Target audience"},
                "tone":     {"type": "string", "description": "Tone of the script"},
                "channel":  {"type": "string", "description": "Channel: nyorkies (NyorkieTales) or jpeezy (UntoldSelf2)"}
            },
            "required": ["topic", "audience", "tone", "channel"]
        }
    },
    {
        "name": "fetch_pexels_footage",
        "description": "Search Pexels for a portrait video clip matching the keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword for Pexels"}
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "generate_voiceover",
        "description": "Generate TTS voiceover. MUST pass full_script (all 5 scenes joined as one string) from write_viral_script — NOT just the hook or a single scene. Passing only the hook causes audio cutoff after first sentence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "The full script text to convert to speech"}
            },
            "required": ["script"]
        }
    },
    {
        "name": "render_video",
        "description": "Render final video. jpeezy=Pixar AI images+storytelling captions. nyorkies=Pixar animal images+story captions. Pass ALL: video_url, audio_url, caption (FULL first scene — all words), channel, duration=audio_duration, scenes[], durations[], keywords[], image_urls[] from generate_all_scene_images.",
        "input_schema": {
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "Pexels portrait video URL"},
                "audio_url": {"type": "string", "description": "Google Drive audio URL"},
                "caption":   {"type": "string", "description": "FULL hook line — ALL words, never cut short"},
                "channel":   {"type": "string", "description": "Channel: jpeezy or nyorkies"},
                "duration":  {"type": "number", "description": "total_duration from write_viral_script result"},
                "scenes":    {"type": "array",  "items": {"type": "string"}, "description": "scenes[] from write_viral_script"},
                "durations": {"type": "array",  "items": {"type": "number"}, "description": "durations[] from write_viral_script"},
                "keywords":   {"type": "array", "items": {"type": "string"}, "description": "keywords[] from write_viral_script"},
                "image_urls": {"type": "array", "items": {"type": "string"}, "description": "image_urls[] from generate_all_scene_images — ALWAYS pass this"}
            },
            "required": ["video_url", "audio_url", "caption", "channel", "duration", "scenes", "durations", "keywords", "image_urls"]
        }
    },
    {
        "name": "wait_and_get_render_url",
        "description": "Poll Creatomate until the render is complete and return the final video URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "render_id": {"type": "string", "description": "The render job ID from Creatomate"}
            },
            "required": ["render_id"]
        }
    },
    {
        "name": "upload_to_youtube",
        "description": "Download the rendered video and upload it to the correct YouTube channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "render_url":  {"type": "string", "description": "The Creatomate video URL"},
                "title":       {"type": "string", "description": "YouTube video title"},
                "description": {"type": "string", "description": "YouTube video description with hashtags"},
                "channel":     {"type": "string", "description": "Channel: jpeezy or nyorkies"}
            },
            "required": ["render_url", "title", "description", "channel"]
        }
    },
    {
        "name": "mark_topic_done",
        "description": "Mark the topic as done in Google Sheets and save the video URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic":     {"type": "string", "description": "The topic string to match in the sheet"},
                "video_url": {"type": "string", "description": "The YouTube or render URL"}
            },
            "required": ["topic", "video_url"]
        }
    },
    {
        "name": "list_pending_topics",
        "description": "List all pending topics in the Google Sheets content queue.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "fetch_and_update_analytics",
        "description": "Fetch real YouTube view/like data for previously uploaded videos and update the performance log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel: jpeezy or nyorkies"}
            },
            "required": []
        }
    },
    {
        "name": "get_performance_insights",
        "description": "Analyze logged video performance to find what hooks, topics, and tones get the most views.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_ai_content_recommendation",
        "description": "Use AI to recommend new video topics based on what has performed best historically.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "generate_dynamic_hashtags",
        "description": "Generate viral topic-specific hashtags based on the script and topic. Returns hashtags_string for description and tags_csv for YouTube API.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic":   {"type": "string", "description": "The video topic"},
                "script":  {"type": "string", "description": "The generated script"},
                "channel": {"type": "string", "description": "Channel: jpeezy or nyorkies"}
            },
            "required": ["topic", "script", "channel"]
        }
    },
    {
        "name": "delete_drive_file",
        "description": "Delete an audio file from Google Drive after upload to free storage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID to delete"}
            },
            "required": ["file_id"]
        }
    },
    {
        "name": "report_video_issues",
        "description": "Log specific quality issues noticed in a completed video so the agent learns to avoid them in future runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "YouTube video ID"},
                "issues":   {"type": "array", "items": {"type": "string"}, "description": "List of issue descriptions e.g. ['caption truncated', 'video too short', 'CTA vague']"}
            },
            "required": ["video_id", "issues"]
        }
    },
    {
        "name": "get_lessons_learned",
        "description": "Retrieve all logged issues and lessons from previous videos. Call this at the START of each run to avoid repeating past mistakes.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "auto_generate_topics",
        "description": "Auto-generate trending viral topics for a channel using AI and add them directly to Google Sheets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "nyorkies or jpeezy"},
                "count":   {"type": "integer", "description": "Number of topics to generate (default 10)"}
            },
            "required": ["channel"]
        }
    },
    {
        "name": "check_and_refill_topics",
        "description": "Check if channel has enough pending topics. Auto-refills if below 5. Call this at start of every run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "nyorkies or jpeezy"}
            },
            "required": ["channel"]
        }
    },
    {
        "name": "generate_all_scene_images",
        "description": "Generates DALL-E 3 images for all 5 scenes. ALWAYS call before animate_key_scenes. Returns image_urls[].",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenes":  {"type": "array",  "items": {"type": "string"}, "description": "scenes[] from write_viral_script"},
                "topic":   {"type": "string", "description": "Video topic"},
                "channel": {"type": "string", "description": "nyorkies or jpeezy"}
            },
            "required": ["scenes", "topic", "channel"]
        }
    },
    {
        "name": "animate_key_scenes",
        "description": "Animate Hook (scene 0) and Twist (scene 3) with subtle facial expression/eye/head motion using Luma AI (primary) or Kling (fallback). Non-key scenes keep DALL-E images + Creatomate Ken Burns motion. Call AFTER generate_all_scene_images, BEFORE render_video. Returns updated image_urls[] with video URLs for animated scenes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_urls": {"type": "array", "items": {"type": "string"}, "description": "image_urls[] from generate_all_scene_images"},
                "scenes":     {"type": "array", "items": {"type": "string"}, "description": "scenes[] from write_viral_script"},
                "channel":    {"type": "string", "description": "nyorkies or jpeezy"}
            },
            "required": ["image_urls", "scenes", "channel"]
        }
    },
]

# ════════════════════════════════════════════════════════════════
#  TOOL DISPATCHER
# ════════════════════════════════════════════════════════════════

TOOL_MAP = {
    "get_pending_topic":       get_pending_topic,
    "write_viral_script":      write_viral_script,
    "fetch_pexels_footage":    fetch_pexels_footage,
    "generate_voiceover":      generate_voiceover,
    "render_video":            render_video,
    "wait_and_get_render_url": wait_and_get_render_url,
    "upload_to_youtube":       upload_to_youtube,
    "mark_topic_done":         mark_topic_done,
    "list_pending_topics":          list_pending_topics,
    "fetch_and_update_analytics":   fetch_and_update_analytics,
    "get_performance_insights":     get_performance_insights,
    "get_ai_content_recommendation":  get_ai_content_recommendation,
    "generate_dynamic_hashtags":      generate_dynamic_hashtags,
    "delete_drive_file":              delete_drive_file,
    "report_video_issues":            report_video_issues,
    "get_lessons_learned":            get_lessons_learned,
    "generate_all_scene_images":      generate_all_scene_images,
    "auto_generate_topics":            auto_generate_topics,
    "check_and_refill_topics":         check_and_refill_topics,
    "animate_key_scenes":              animate_key_scenes,
    "animate_all_scenes":              animate_all_scenes,  # legacy — keep for backward compat
}

def run_tool(name: str, inputs: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**inputs)
        return json.dumps(result)
    except Exception as e:
        log(f"Tool {name} raised exception: {e}", "error")
        return json.dumps({"error": str(e)})


# ════════════════════════════════════════════════════════════════
#  AGENT LOOP — Claude Haiku (primary) → GPT-4o-mini (fallback)
# ════════════════════════════════════════════════════════════════

AGENT_SYSTEM_PROMPT = """You are the Jpeeezy AI Video Factory agent — a self-improving YouTube Shorts automation system.
Your style is inspired by @ExcuseErased: cinematic "Motion Design / Fake Animation" YouTube Shorts.

CHANNEL SEPARATION — CRITICAL:
- Channel 'nyorkies' = NyorkieTales (@NyorkieTales) → EXCLUSIVELY animal content: cute animals, animal stories, animal adventures. NEVER include human stories, AI tools, or money content.
- Channel 'jpeezy' = UntoldSelf2 (@UntoldSelf2) → Mix of narrative stories, AI money-making tools, and unique interesting stories sourced from web, TikTok, YouTube, Reddit. NEVER include animal content.
- Valid channel values are ONLY 'nyorkies' and 'jpeezy'. Never use any other channel name.
- ALWAYS pass the correct channel from the topic to EVERY tool call. NEVER mix content between channels.

When asked to PROCESS A VIDEO, follow this exact sequence:
1.  get_pending_topic → get topic, audience, tone, channel
2.  check_and_refill_topics → ensure channel has enough topics queued
3.  write_viral_script → multi-agent pipeline: 5 hooks → best hook → script → score (retry if <7/10)
4.  generate_all_scene_images → DALL-E 3 images for all 5 scenes. Returns image_urls[].
5.  animate_key_scenes → Animate Hook (scene 0) + Twist (scene 3) with Luma AI (primary) / Kling (fallback) for subtle facial expression, eye movement, head tilt. Non-key scenes keep DALL-E images. Returns updated image_urls[]. If Luma/Kling are not configured, scenes will still look great with Creatomate Ken Burns motion.
6.  generate_voiceover → Pass full_script (ALL 5 scenes joined) from step 3 — NOT just the hook. SAVE drive_file_id AND audio_duration.
7.  fetch_pexels_footage → get ONE portrait video URL as fallback
8.  generate_dynamic_hashtags → topic-specific viral hashtags (pass topic + script + channel)
9.  render_video → combine Fake Motion visuals + audio + word-chunk captions. Pass ALL these params:
    - video_url (from step 7), audio_url (from step 6), caption=FULL first scene text
    - channel, duration=audio_duration from step 6
    - scenes=scenes[] from step 3, durations=durations[] from step 3
    - keywords=keywords[] from step 3, image_urls=image_urls[] from step 5 (animated version!)
10. wait_and_get_render_url → poll Creatomate until render is complete
11. upload_to_youtube → title = hook (max 55 chars) + hashtag | description = script + CTA + hashtags_string from step 8 | tags = tags_csv from step 8
12. delete_drive_file → pass the drive_file_id saved in step 6 to clean up audio from Drive
13. mark_topic_done → update Google Sheet with YouTube URL

CRITICAL PIPELINE RULES:
- ALWAYS call animate_key_scenes AFTER generate_all_scene_images and pass its output to render_video
- ALWAYS use audio_duration from step 6 as the duration in step 9
- The caption in step 9 must be the FULL first scene text — never truncate
- NyorkieTales CTA: 'Follow @NyorkieTales for daily animal stories that warm your heart.'
- UntoldSelf2 CTA: 'Follow @UntoldSelf2 for money secrets that actually work.'
- If delete_drive_file fails, continue anyway — don't fail the pipeline over cleanup

CONTENT QUALITY RULES:
- Scripts MUST be exactly 5 scenes — reject and regenerate if any other count
- Hook (Scene 1): must stop scroll in first 2 seconds — no soft openings, ever
- Scene 4 (Twist): MUST be the most emotionally or intellectually impactful line — this is the viral moment
- Pattern interrupt required in Scene 3: use 'Wait...' / 'But here is the truth:' / 'Nobody tells you this:'
- Last scene CTA must echo the hook for loop retention effect
- Scripts that sound AI-generated must be retried — retry if score < 7

VISUAL STYLE (ExcuseErased reference):
- NyorkieTales: Disney/Pixar 3D animal close-up with expressive face — warm lighting, vibrant colors
- UntoldSelf2: Pixar-style 3D human character — dark cinematic with neon/city aesthetic, dramatic lighting
- Voiceover: Deep calm Onyx male narrator at 0.9x speed — dramatic pauses, emotional delivery
- Captions: Word-chunk style (2-3 words at a time, UPPERCASE, pop-in scale animation, center-bottom)
- Transitions: Hard cuts between scenes (no crossfade)
- Motion: Enhanced Ken Burns (dramatic zoom/pan/rotate) on ALL scenes + Luma AI subtle animation on key scenes (0, 3)
- Never use generic/safe DALL-E prompts — always include specific emotional direction

When asked for PERFORMANCE INSIGHTS or RECOMMENDATIONS:
- fetch_and_update_analytics → get real view data
- get_performance_insights → find patterns
- get_ai_content_recommendation → suggest new topics based on what works

Self-improvement rules:
- After every 5 videos, automatically fetch analytics and report what is working
- Recommend doubling down on topics/hooks that get above-average views
- Flag topics that underperform so they can be replaced

If any tool errors, retry once intelligently before giving up.
Always end with the YouTube URL and script quality score."""


def _convert_tools_to_openai_format():
    """Convert Anthropic-style TOOLS list to OpenAI function calling format."""
    openai_tools = []
    for tool in TOOLS:
        openai_tools.append({
            "type": "function",
            "function": {
                "name":        tool["name"],
                "description": tool["description"],
                "parameters":  tool["input_schema"]
            }
        })
    return openai_tools


def _run_agent_claude(user_message: str, verbose: bool = True) -> str:
    """Run agent loop using Claude Haiku."""
    client   = _anthropic_client()
    messages = [{"role": "user", "content": user_message}]

    if verbose:
        log("🟣 Agent starting (Claude Haiku)...", "agent")

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=AGENT_SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = " ".join(
                block.text for block in response.content
                if hasattr(block, "text")
            )
            if verbose:
                log("Agent finished (Claude Haiku).", "agent")
            return final_text

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if verbose:
                        log(f"Calling tool: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}...)", "tool")
                    result_str = run_tool(block.name, block.input)
                    if verbose:
                        log(f"Tool result: {result_str[:200]}", "info")
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result_str
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "Agent loop ended unexpectedly."


def _run_agent_openai(user_message: str, verbose: bool = True) -> str:
    """Run agent loop using GPT-4o-mini (fallback when Claude credits exhausted)."""
    if verbose:
        log("🟢 Agent starting (GPT-4o-mini fallback)...", "agent")

    headers = _openai_headers()
    openai_tools = _convert_tools_to_openai_format()
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    while True:
        body = {
            "model":       "gpt-4o-mini",
            "max_tokens":  4096,
            "messages":    messages,
            "tools":       openai_tools,
            "tool_choice": "auto"
        }

        resp = requests.post("https://api.openai.com/v1/chat/completions",
                             headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        result  = resp.json()
        choice  = result["choices"][0]
        msg     = choice["message"]

        # Add assistant message to history
        messages.append(msg)

        # Check if done
        if choice["finish_reason"] == "stop":
            if verbose:
                log("Agent finished (GPT-4o-mini).", "agent")
            return msg.get("content", "")

        # Process tool calls
        if choice["finish_reason"] == "tool_calls" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except Exception:
                    fn_args = {}

                if verbose:
                    log(f"Calling tool: {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:120]}...)", "tool")

                result_str = run_tool(fn_name, fn_args)

                if verbose:
                    log(f"Tool result: {result_str[:200]}", "info")

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      result_str
                })
        else:
            break

    return "Agent loop ended unexpectedly."


def run_agent(user_message: str, verbose: bool = True) -> str:
    """Run agent with automatic fallback: Claude Haiku → GPT-4o-mini."""
    # Try Claude Haiku first
    try:
        return _run_agent_claude(user_message, verbose)
    except Exception as e:
        # ANY Claude failure → fallback to GPT-4o-mini
        log(f"⚠️ Claude error: {str(e)[:120]} — switching to GPT-4o-mini fallback...", "warn")
        try:
            return _run_agent_openai(user_message, verbose)
        except Exception as e2:
            log(f"GPT-4o-mini fallback also failed: {e2}", "error")
            raise e2


# ════════════════════════════════════════════════════════════════
#  RUN MODES
# ════════════════════════════════════════════════════════════════

def process_channel(channel_key):
    ch_name = YOUTUBE_CHANNELS.get(channel_key, {}).get("display_name", channel_key)
    log("Starting: " + channel_key, "step")
    topic = "unknown"
    try:
        msg = "Process the next pending video for the '" + channel_key + "' channel from Google Sheets. Complete end-to-end and confirm with YouTube URL."
        result = run_agent(msg, verbose=True)
        print(Fore.GREEN + "=" * 50)
        print("[" + channel_key + "] RESULT:")
        print(result)
        print("=" * 50 + Style.RESET_ALL)
        import re as _re
        url_m   = _re.search("https://youtube.com/shorts/[^ \n]+", result)
        top_m   = _re.search("[Tt]opic[: ]+[^\n]{10,80}", result)
        scr_m   = _re.search("([0-9]+)/10", result)
        yurl    = url_m.group(0) if url_m else "URL not found"
        top     = top_m.group(0) if top_m else "See result"
        score   = int(scr_m.group(1)) if scr_m else 0
        if url_m:
            notify_success(ch_name, top, yurl, score)
        else:
            notify_error(ch_name, top, "YouTube URL not found", "upload")
    except Exception as e:
        log("Pipeline error: " + str(e), "error")
        notify_error(ch_name, topic, str(e), "pipeline")


def run_all_channels():
    log("Running all channels sequentially (prevents API rate limit conflicts)...", "step")
    for ck in YOUTUBE_CHANNELS.keys():
        process_channel(ck)
    log("All channels done.", "success")


def mode_run():
    """Process one video per channel right now."""
    banner()
    log("MODE: Run Once — all channels", "step")
    run_all_channels()


# ── Best posting times per niche (research-backed, Philippines timezone GMT+8) ──
# Agent picks from these windows based on niche + day of week
OPTIMAL_POST_WINDOWS = {
    "nyorkies": {
        "weekday": ["07:00", "12:00", "19:00", "21:00"],
        "weekend": ["08:00", "11:00", "15:00", "20:00"],
        "reason":  "Animal/cute content peaks morning commute + evening wind-down"
    },
    "jpeezy": {
        "weekday": ["06:30", "12:30", "18:00", "21:30"],
        "weekend": ["09:00", "14:00", "19:00", "22:00"],
        "reason":  "Storytelling peaks lunch breaks + late evening reflection time"
    },
    }


def get_optimal_post_times() -> dict:
    """
    AI agent picks the best 3 posting slots for today across all channels.
    Uses day of week + niche data to pick non-overlapping times.
    Returns schedule dict: {channel_key: "HH:MM"}
    """
    log("Agent calculating optimal posting times for today...", "tool")
    today        = datetime.now()
    day_type     = "weekend" if today.weekday() >= 5 else "weekday"
    day_name     = today.strftime("%A")

    # Build candidate slots per channel
    candidates = {}
    for ch_key, windows in OPTIMAL_POST_WINDOWS.items():
        candidates[ch_key] = windows[day_type]

    # Ask Claude to pick the best non-overlapping schedule
    try:
        client = _anthropic_client()
        prompt = f"""You are a YouTube Shorts growth strategist for the Philippines (GMT+8).
Today is {day_name} ({day_type}).

Pick the single BEST posting time for each channel from their candidate slots.
Rules:
- No two channels should post within 90 minutes of each other
- Pick times when that niche audience is most active
- NyorkieTales (cute animals): audience = kids + families + animal lovers, peak morning + evening
- UntoldSelf (storytelling + AI money): audience = young adults 18-35, peak evening + late night

Candidates:
NyorkieTales: {candidates.get('nyorkies', [])}
UntoldSelf:   {candidates.get('jpeezy', [])}

Return ONLY valid JSON: {{"nyorkies": "HH:MM", "jpeezy": "HH:MM"}}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        raw      = resp.content[0].text.strip()
        schedule_times = json.loads(raw.replace("```json","").replace("```","").strip())
        log(f"AI-selected times: NyorkieTales={schedule_times.get('nyorkies')} | UntoldSelf={schedule_times.get('jpeezy')}", "success")
        return schedule_times

    except Exception as e:
        log(f"AI time picker failed ({e}) — using research-backed defaults", "warn")
        # Sensible defaults if AI call fails
        return {
            "nyorkies":  "08:00" if day_type == "weekend" else "07:00",
            "jpeezy": "20:00" if day_type == "weekend" else "18:00",
            
        }


def mode_schedule():
    """
    Smart 3-channel daily scheduler.
    Every day at midnight, Claude picks the optimal posting times for each channel
    based on niche, day of week, and audience behavior patterns.
    Channels post simultaneously in parallel threads.
    """
    banner()
    log("MODE: Smart Schedule — AI picks optimal times daily", "step")

    def schedule_todays_posts():
        """Called every day at midnight to set today's schedule."""
        schedule.clear("daily_posts")
        times = get_optimal_post_times()

        for channel_key, post_time in times.items():
            if channel_key not in YOUTUBE_CHANNELS:
                continue
            ch_name = YOUTUBE_CHANNELS[channel_key]["display_name"]
            schedule.every().day.at(post_time).do(
                process_channel, channel_key=channel_key
            ).tag("daily_posts")
            log(f"Scheduled {ch_name} → {post_time} today", "success")

    # Set up today's schedule immediately
    schedule_todays_posts()

    # Re-pick times every day at midnight
    schedule.every().day.at("00:01").do(schedule_todays_posts)

    log("Smart scheduler active. Posts daily at AI-optimized times.", "info")
    log("Press Ctrl+C to stop.", "info")

    # Show today's schedule
    print(f"\n{Fore.CYAN}Today's schedule:{Style.RESET_ALL}")
    for job in schedule.jobs:
        if "daily_posts" in (job.tags or set()):
            print(f"  {Fore.GREEN}▶ {job.next_run.strftime('%I:%M %p')}{Style.RESET_ALL}")

    while True:
        schedule.run_pending()
        time.sleep(30)


def mode_chat():
    """Interactive chat mode — talk to the agent like an AI assistant."""
    banner()
    log("MODE: Chat (type 'quit' to exit)", "step")
    print(f"""
{Fore.CYAN}You can say things like:
  → 'Process the next video'
  → 'How many pending topics do I have?'
  → 'Make a video about ChatGPT for the jpeezy channel'
  → 'What channels do I have?'
{Style.RESET_ALL}""")

    history = []
    client  = _anthropic_client()
    system  = """You are the Jpeeezy AI Video Factory assistant. You help manage a YouTube Shorts automation pipeline.
You have tools to process videos, check the content queue, and run the full pipeline.
Be concise, helpful, and action-oriented. If the user asks you to process a video, run the full pipeline autonomously."""

    while True:
        try:
            user_input = input(f"\n{Fore.YELLOW}You: {Style.RESET_ALL}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Fore.MAGENTA}Goodbye! 👋{Style.RESET_ALL}")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "bye"):
            print(f"\n{Fore.MAGENTA}Goodbye! 👋{Style.RESET_ALL}")
            break

        history.append({"role": "user", "content": user_input})

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=system,
                tools=TOOLS,
                messages=history
            )
            history.append({"role": "assistant", "content": response.content})

            # Handle tool calls in chat
            while response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log(f"🔧 {block.name}", "tool")
                        result_str = run_tool(block.name, block.input)
                        tool_results.append({
                            "type":        "tool_result",
                            "tool_use_id": block.id,
                            "content":     result_str
                        })

                history.append({"role": "user", "content": tool_results})
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=4096,
                    system=system,
                    tools=TOOLS,
                    messages=history
                )
                history.append({"role": "assistant", "content": response.content})

            # Print final response
            final = " ".join(
                block.text for block in response.content
                if hasattr(block, "text")
            )
            print(f"\n{Fore.MAGENTA}Agent: {Style.RESET_ALL}{final}")

        except Exception as e:
            log(f"Error: {e}", "error")


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Jpeeezy AI Video Factory — Agentic Workflow",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "mode",
        choices=["run", "schedule", "chat"],
        help=(
            "run      → process one video now\n"
            "schedule → run every 24 hours automatically\n"
            "chat     → interactive AI assistant mode"
        )
    )
    args = parser.parse_args()

    if args.mode == "run":
        mode_run()
    elif args.mode == "schedule":
        mode_schedule()
    elif args.mode == "chat":
        mode_chat()


if __name__ == "__main__":
    main()
