#!/usr/bin/env python3
"""
Auto Uploader — YouTube Shorts Upload Pipeline

Drop videos into channel folders → auto-generates titles & descriptions
→ uploads to the correct YouTube channel → moves to uploaded/

Usage:
    python auto_uploader.py              Upload all pending videos
    python auto_uploader.py --watch      Watch mode (continuous)
    python auto_uploader.py --dry-run    Preview without uploading
    python auto_uploader.py --list       Show pending & uploaded status
"""

import os
import sys

# Fix Windows terminal encoding for Unicode box-drawing characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import time
import shutil
import pickle
import argparse
import re
from pathlib import Path
from datetime import datetime

# ── Dependencies ─────────────────────────────────────────────
try:
    import requests
    from openai import OpenAI
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError as e:
    print(f"  Missing: {e}")
    print("  pip install requests openai google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# ── Credentials ──────────────────────────────────────────────
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "credentials", Path(__file__).parent / "credentials.py"
    )
    _creds = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_creds)
    OPENAI_API_KEY     = getattr(_creds, "OPENAI_API_KEY", "")
    TELEGRAM_BOT_TOKEN = getattr(_creds, "TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = getattr(_creds, "TELEGRAM_CHAT_ID", "")
except Exception:
    OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID   = ""


# ═══════════════════════════════════════════════════════════════
#  TERMINAL UI
# ═══════════════════════════════════════════════════════════════

# Colors
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
WHITE  = "\033[97m"
GRAY   = "\033[90m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
MAGENTA = "\033[95m"


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def out(msg: str, style: str = ""):
    """Print a styled line with timestamp."""
    print(f"  {GRAY}{_ts()}{RESET}  {style}{msg}{RESET}")


def header(text: str):
    """Print a section header."""
    w = 52
    print()
    print(f"  {CYAN}{'─' * w}{RESET}")
    print(f"  {CYAN}{BOLD}  {text}{RESET}")
    print(f"  {CYAN}{'─' * w}{RESET}")


def banner():
    print(f"""
  {CYAN}{BOLD}┌──────────────────────────────────────────────────┐{RESET}
  {CYAN}{BOLD}│{RESET}  {WHITE}{BOLD}AUTO UPLOADER{RESET}  {DIM}v2.0{RESET}                              {CYAN}{BOLD}│{RESET}
  {CYAN}{BOLD}│{RESET}  {DIM}YouTube Shorts · AI Metadata · Multi-Channel{RESET}    {CYAN}{BOLD}│{RESET}
  {CYAN}{BOLD}└──────────────────────────────────────────────────┘{RESET}
""")


def success(msg: str):
    out(f"{GREEN}✓{RESET} {msg}")


def warn(msg: str):
    out(f"{YELLOW}●{RESET} {msg}")


def error(msg: str):
    out(f"{RED}✗{RESET} {msg}")


def info(msg: str):
    out(f"{BLUE}→{RESET} {msg}")


def step(msg: str):
    out(f"{MAGENTA}▸{RESET} {msg}")


def progress_bar(current: int, total: int, width: int = 30) -> str:
    pct   = current / max(total, 1)
    filled = int(width * pct)
    bar   = f"{'█' * filled}{'░' * (width - filled)}"
    return f"{CYAN}{bar}{RESET} {WHITE}{int(pct * 100)}%{RESET}"


# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════

BASE_DIR    = Path(__file__).parent
VIDEOS_DIR  = BASE_DIR / "syllaby_videos"
UPLOADED_DIR = VIDEOS_DIR / "uploaded"
UPLOAD_LOG  = BASE_DIR / "upload_log.json"

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Channel mapping — folder name → YouTube channel config
CHANNELS = {
    "nyorkietales": {
        "name":        "NyorkieTales",
        "niche":       "cute animals, animal adventures, heartwarming animal stories",
        "tags":        ["shorts", "viral", "trending", "animals", "cuteanimals",
                        "funnyanimal", "animalstory", "pets", "wildlife", "adorable"],
        "hashtags":    "#Animals #CuteAnimals #AnimalStory #Pets #Wildlife #shorts #viral #trending",
        "credentials": str(BASE_DIR / "youtube_credentials_nyorkies.json"),
        "token":       str(BASE_DIR / "youtube_token_nyorkies.pickle"),
    },
    "untoldself": {
        "name":        "UntoldSelf2",
        "niche":       "emotional storytelling, personal growth, AI money-making strategies",
        "tags":        ["shorts", "viral", "trending", "storytelling", "motivation",
                        "lifelessons", "aitools", "makemoneyonline", "mindset", "inspiration"],
        "hashtags":    "#Storytelling #Motivation #LifeLessons #AITools #MakeMoneyOnline #shorts #viral #trending",
        "credentials": str(BASE_DIR / "youtube_credentials_jpeezy.json"),
        "token":       str(BASE_DIR / "youtube_token_jpeezy.pickle"),
    },
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ═══════════════════════════════════════════════════════════════
#  FOLDER SETUP
# ═══════════════════════════════════════════════════════════════

def ensure_folders():
    for folder in CHANNELS:
        (VIDEOS_DIR / folder).mkdir(parents=True, exist_ok=True)
        (UPLOADED_DIR / folder).mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
#  UPLOAD LOG
# ═══════════════════════════════════════════════════════════════

def load_log() -> list:
    if UPLOAD_LOG.exists():
        with open(UPLOAD_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(entries: list):
    with open(UPLOAD_LOG, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def already_uploaded(filepath: str, entries: list) -> bool:
    name = Path(filepath).name
    return any(e.get("filename") == name for e in entries)


# ═══════════════════════════════════════════════════════════════
#  AI METADATA (GPT-4o-mini — ~$0.0001/call)
# ═══════════════════════════════════════════════════════════════

def generate_metadata(filename: str, channel: str) -> dict:
    """Generate title, description, and hashtags from filename using AI."""
    ch = CHANNELS[channel]
    clean = re.sub(r"[_\-]+", " ", Path(filename).stem)
    clean = re.sub(r"^\d+\s*", "", clean)

    prompt = f"""Generate YouTube Shorts metadata for a video.

Channel: {ch['name']} | Niche: {ch['niche']}
Filename hint: {clean}

Return JSON only:
{{"title": "catchy title max 80 chars with emoji", "description": "2-3 sentence hook + CTA", "hashtags": "8-10 hashtags"}}"""

    try:
        client   = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=300,
        )
        text  = response.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {
                "title":       data.get("title", clean)[:100],
                "description": data.get("description", "") + "\n\n" + data.get("hashtags", ch["hashtags"]),
                "hashtags":    data.get("hashtags", ch["hashtags"]),
            }
    except Exception as e:
        warn(f"AI metadata failed: {e}")

    return {
        "title":       clean.title()[:100],
        "description": f"{clean.title()}\n\n{ch['hashtags']}",
        "hashtags":    ch["hashtags"],
    }


# ═══════════════════════════════════════════════════════════════
#  YOUTUBE AUTH
# ═══════════════════════════════════════════════════════════════

def get_youtube_creds(channel: str):
    ch         = CHANNELS[channel]
    token_path = ch["token"]
    creds_path = ch["credentials"]
    creds      = None

    if Path(token_path).exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            info(f"Refreshing token for {ch['name']}...")
            creds.refresh(Request())
        else:
            warn(f"First-time auth for {ch['name']} — browser will open")
            if not Path(creds_path).exists():
                raise FileNotFoundError(f"Missing {creds_path}")
            flow  = InstalledAppFlow.from_client_secrets_file(creds_path, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return creds


# ═══════════════════════════════════════════════════════════════
#  YOUTUBE UPLOAD
# ═══════════════════════════════════════════════════════════════

def upload_video(filepath: str, channel: str, title: str, description: str) -> dict:
    ch      = CHANNELS[channel]
    creds   = get_youtube_creds(channel)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        ch["tags"],
            "categoryId":  "22",
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
            "notifySubscribers":       True,
        },
    }

    step(f"Uploading → {ch['name']}")
    media   = MediaFileUpload(filepath, chunksize=1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"\r  {GRAY}{_ts()}{RESET}  {progress_bar(pct, 100)}", end="", flush=True)
    print()  # newline after progress

    vid_id  = response.get("id", "")
    vid_url = f"https://youtube.com/shorts/{vid_id}"
    success(f"Live at {vid_url}")

    return {"video_id": vid_id, "video_url": vid_url}


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM NOTIFICATION
# ═══════════════════════════════════════════════════════════════

def notify_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  SCAN & PROCESS
# ═══════════════════════════════════════════════════════════════

def scan_pending() -> list:
    log_entries = load_log()
    pending     = []

    for folder in CHANNELS:
        path = VIDEOS_DIR / folder
        if not path.exists():
            continue
        for f in sorted(path.iterdir()):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                if not already_uploaded(str(f), log_entries):
                    pending.append({
                        "filepath": str(f),
                        "filename": f.name,
                        "channel":  folder,
                        "size_mb":  round(f.stat().st_size / (1024 * 1024), 1),
                    })
    return pending


def process_video(video: dict, dry_run: bool = False) -> bool:
    ch = CHANNELS[video["channel"]]

    header(f"{video['filename']}")
    info(f"Channel: {ch['name']}  ·  Size: {video['size_mb']} MB")

    # 1 — Generate metadata
    step("Generating title & description with AI...")
    meta = generate_metadata(video["filename"], video["channel"])
    info(f"Title: {meta['title']}")

    if dry_run:
        warn("Dry run — skipping upload")
        return True

    # 2 — Upload
    try:
        result = upload_video(video["filepath"], video["channel"], meta["title"], meta["description"])
    except Exception as e:
        error(f"Upload failed: {e}")
        notify_telegram(f"❌ Upload failed: {video['filename']}\n{ch['name']}\n{str(e)[:200]}")
        return False

    # 3 — Move to uploaded/
    dest = UPLOADED_DIR / video["channel"] / video["filename"]
    try:
        shutil.move(video["filepath"], str(dest))
        info(f"Moved → uploaded/{video['channel']}/")
    except Exception as e:
        warn(f"Move failed: {e}")

    # 4 — Log
    entries = load_log()
    entries.append({
        "filename":    video["filename"],
        "channel":     video["channel"],
        "channel_name": ch["name"],
        "title":       meta["title"],
        "video_url":   result.get("video_url", ""),
        "video_id":    result.get("video_id", ""),
        "uploaded_at": datetime.now().isoformat(),
    })
    save_log(entries)

    # 5 — Notify
    notify_telegram(
        f"✅ <b>Uploaded!</b>\n"
        f"📺 {ch['name']}\n"
        f"📝 {meta['title']}\n"
        f"🔗 {result.get('video_url', '')}"
    )
    return True


# ═══════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════

def cmd_upload(dry_run: bool = False):
    ensure_folders()
    pending = scan_pending()

    if not pending:
        print()
        warn("No pending videos found")
        print()
        info("Drop videos into:")
        for name, ch in CHANNELS.items():
            print(f"           {CYAN}videos/{name}/{RESET}  →  {WHITE}{ch['name']}{RESET}")
        print()
        return

    header(f"Found {len(pending)} video(s)")
    for v in pending:
        info(f"{v['filename']}  →  {CHANNELS[v['channel']]['name']}")

    ok = 0
    fail = 0
    for v in pending:
        if process_video(v, dry_run=dry_run):
            ok += 1
        else:
            fail += 1
        if not dry_run and ok < len(pending):
            time.sleep(5)

    print()
    print(f"  {CYAN}{'─' * 52}{RESET}")
    success(f"Done — {GREEN}{ok} uploaded{RESET}, {RED if fail else GRAY}{fail} failed{RESET}")
    print(f"  {CYAN}{'─' * 52}{RESET}")
    print()


def cmd_watch(interval: int = 60):
    print()
    info(f"Watch mode — checking every {interval}s")
    warn("Press Ctrl+C to stop")
    print()

    ensure_folders()
    while True:
        try:
            pending = scan_pending()
            if pending:
                success(f"Found {len(pending)} new video(s)")
                for v in pending:
                    process_video(v)
                    time.sleep(5)
            else:
                out(f"{DIM}No new videos · waiting...{RESET}")
            time.sleep(interval)
        except KeyboardInterrupt:
            print()
            warn("Watch mode stopped")
            break
        except Exception as e:
            error(str(e))
            time.sleep(30)


def cmd_list():
    ensure_folders()
    pending    = scan_pending()
    log_entries = load_log()

    header("STATUS")

    if pending:
        print()
        success(f"{len(pending)} pending:")
        for v in pending:
            ch = CHANNELS[v["channel"]]
            print(f"           {WHITE}{v['filename']}{RESET}  {DIM}({v['size_mb']} MB){RESET}  →  {CYAN}{ch['name']}{RESET}")
    else:
        print()
        warn("No pending videos")

    if log_entries:
        print()
        success(f"{len(log_entries)} uploaded:")
        for e in log_entries[-10:]:
            date = e.get("uploaded_at", "")[:10]
            print(f"           {DIM}{date}{RESET}  {WHITE}{e['filename']}{RESET}  →  {CYAN}{e.get('channel_name', '')}{RESET}")
        if len(log_entries) > 10:
            out(f"{DIM}... and {len(log_entries) - 10} more{RESET}")

    print()
    info("Drop videos into:")
    for name, ch in CHANNELS.items():
        print(f"           {CYAN}videos/{name}/{RESET}  →  {WHITE}{ch['name']}{RESET}")
    print()


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Auto Uploader — YouTube Shorts Multi-Channel Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""{DIM}
  python auto_uploader.py              Upload all pending
  python auto_uploader.py --dry-run    Preview without uploading
  python auto_uploader.py --watch      Auto-upload on new files
  python auto_uploader.py --list       Show status{RESET}
""",
    )
    parser.add_argument("--watch",    action="store_true", help="Watch folders for new videos")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, don't upload")
    parser.add_argument("--list",     action="store_true", help="Show pending & uploaded status")

    args = parser.parse_args()

    banner()

    if args.list:
        cmd_list()
    elif args.watch:
        cmd_watch(interval=args.interval)
    else:
        cmd_upload(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
