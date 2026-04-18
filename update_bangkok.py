#!/usr/bin/env python3
"""
Auto-updates bangkok-today.html with the latest Timeout Bangkok weekend picks.
Scheduled to run every Friday via Windows Task Scheduler.
"""

import re
import json
import sys
import requests
import anthropic
from datetime import datetime, timedelta
from pathlib import Path

HTML_FILE = Path(__file__).parent / "bangkok-today.html"
TIMEOUT_URL = "https://www.timeout.com/bangkok/things-to-do/the-best-things-to-do-in-bangkok-this-weekend"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

VALID_CATS = {"art", "music", "pop-up", "film", "market", "aquarium", "nature", "nightlife", "community"}

CAT_EMOJI = {
    "art": "🎨", "music": "🎵", "pop-up": "⭐", "film": "🎬",
    "market": "🛍", "aquarium": "🌊", "nature": "🌿", "nightlife": "🌙", "community": "🐾"
}

def fetch_page(url: str) -> str:
    print(f"Fetching {url} ...")
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def extract_activities(html: str) -> list[dict]:
    client = anthropic.Anthropic()
    print("Asking Claude to parse activities...")

    prompt = f"""You are parsing a Timeout Bangkok weekend activities article.
Extract every activity/event listed. Return ONLY a valid JSON array — no markdown, no explanation.

Each item must have exactly these keys:
  id        (integer, 1-based)
  title     (string, event name)
  cat       (string, exactly one of: art / music / pop-up / film / market / aquarium / nature / nightlife / community)
  e         (string, single emoji matching the category)
  loc       (string, venue + neighbourhood)
  lat       (number, Bangkok GPS latitude, e.g. 13.7469)
  lng       (number, Bangkok GPS longitude, e.g. 100.5316)
  time      (string, opening hours or time)
  until     (string, end date or "Ongoing")
  price     (string, e.g. "Free" or "฿300")
  free      (integer, 1 if free entry, else 0)
  desc      (string, one punchy sentence)
  img       (string, full image URL from the article, or "" if none found)

Category emoji guide: art=🎨 music=🎵 pop-up=⭐ film=🎬 market=🛍 aquarium=🌊 nature=🌿 nightlife=🌙 community=🐾

For lat/lng use your knowledge of Bangkok venues. If unsure, use the neighbourhood centre.

HTML content (truncated to first 80 000 chars):
{html[:80000]}
"""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    activities = json.loads(raw)

    # Sanitise
    for i, a in enumerate(activities, 1):
        a["id"] = i
        if a.get("cat") not in VALID_CATS:
            a["cat"] = "art"
        a["e"] = CAT_EMOJI.get(a["cat"], "🎨")
        a.setdefault("img", "")
        a["free"] = int(bool(a.get("free", 0)))

    print(f"  → {len(activities)} activities extracted")
    return activities


def weekend_label() -> str:
    today = datetime.now()
    # Next Friday (or today if Friday)
    days_ahead = (4 - today.weekday()) % 7
    friday = today + timedelta(days=days_ahead)
    sunday = friday + timedelta(days=2)
    return f"{friday.strftime('%b %-d')}–{sunday.strftime('%-d, %Y')}"


def update_html(activities: list[dict]) -> None:
    html = HTML_FILE.read_text(encoding="utf-8")

    # Replace ACTIVITIES array
    new_js = "var A = " + json.dumps(activities, ensure_ascii=False, separators=(", ", ":")) + ";"
    html, n = re.subn(r"var A = \[.*?\];", new_js, html, flags=re.DOTALL)
    if n == 0:
        raise ValueError("Could not find 'var A = [...]' in HTML file — pattern mismatch.")

    # Replace weekend date label in the subtitle
    label = weekend_label()
    html = re.sub(
        r"(18 picks from Timeout Bangkok · ).*",
        rf"\g<1>{len(activities)} picks · Timeout Bangkok · {label}",
        html
    )

    # Update filter pill count
    html = re.sub(r"All \d+", f"All {len(activities)}", html)

    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"  → {HTML_FILE} updated ({len(activities)} activities, dates: {label})")


def main():
    try:
        html = fetch_page(TIMEOUT_URL)
        activities = extract_activities(html)
        update_html(activities)
        print("Done ✓")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
