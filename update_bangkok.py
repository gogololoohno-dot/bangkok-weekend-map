#!/usr/bin/env python3
"""
Auto-updates index.html with the latest Timeout weekend picks for
Bangkok, Singapore, Tokyo, and Hong Kong.
Scheduled to run every Friday via Windows Task Scheduler.
"""

import re
import json
import sys
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path

HTML_FILE = Path(__file__).parent / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

VALID_CATS = {"art", "music", "pop-up", "film", "market", "aquarium", "nature", "nightlife", "community"}

CAT_EMOJI = {
    "art": "🎨", "music": "🎵", "pop-up": "⭐", "film": "🎬",
    "market": "🛍", "aquarium": "🌊", "nature": "🌿", "nightlife": "🌙", "community": "🐾"
}

# ── City definitions ──────────────────────────────────────────────────────────
CITIES = {
    "bangkok": {
        "name":       "Bangkok, Thailand",
        "url":        "https://www.timeout.com/bangkok/things-to-do/the-best-things-to-do-in-bangkok-this-weekend",
        "var":        "A_BANGKOK",
        "label_var":  "LABEL_BANGKOK",
        "currency":   "฿",
        # Bounding box: lat_min, lat_max, lng_min, lng_max
        "bounds":     (13.50, 14.00, 100.30, 100.95),
    },
    "singapore": {
        "name":       "Singapore",
        "url":        "https://www.timeout.com/singapore/things-to-do/things-to-do-in-singapore-this-weekend",
        "var":        "A_SINGAPORE",
        "label_var":  "LABEL_SINGAPORE",
        "currency":   "S$",
        "bounds":     (1.15, 1.50, 103.60, 104.10),
    },
    "tokyo": {
        "name":       "Tokyo, Japan",
        "url":        "https://www.timeout.com/tokyo/things-to-do/things-to-do-in-tokyo-this-weekend",
        "var":        "A_TOKYO",
        "label_var":  "LABEL_TOKYO",
        "currency":   "¥",
        # Greater Tokyo metro area — Timeout Tokyo includes events in Yokohama,
        # Saitama, Ome, Hanno, etc. Box covers the full commuting region.
        "bounds":     (35.30, 35.95, 139.10, 140.10),
    },
    "hongkong": {
        "name":       "Hong Kong",
        "url":        "https://www.timeout.com/hong-kong/things-to-do/things-to-do-in-hong-kong-this-weekend",
        "var":        "A_HONGKONG",
        "label_var":  "LABEL_HONGKONG",
        "currency":   "HK$",
        "bounds":     (22.15, 22.55, 113.80, 114.45),
    },
}


def fetch_page(url: str) -> str:
    print(f"  Fetching {url} ...")
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def build_image_map(html: str) -> list[tuple[str, str]]:
    """Extract (alt_text, image_url) pairs from Timeout's <img> tags. Lazy-load
    aware (matches both src and data-src). Returns deduped list preserving order."""
    pattern = r'<img[^>]*(?:src|data-src)="(https://media\.timeout\.com/images/[^"]+)"[^>]*alt="([^"]+)"'
    seen = set()
    pairs = []
    for url, alt in re.findall(pattern, html):
        alt = alt.strip()
        if not alt or url in seen:
            continue
        seen.add(url)
        pairs.append((alt, url))
    return pairs


def _tokenize(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def fill_missing_images(activities: list[dict], img_map: list[tuple[str, str]]) -> int:
    """Fuzzy-match activity titles against alt text to fill blank img fields.
    Returns the number of entries filled."""
    filled = 0
    for a in activities:
        if a.get("img"):
            continue
        title_toks = _tokenize(a.get("title", "")) | _tokenize(a.get("loc", ""))
        if not title_toks:
            continue
        best_score = 0
        best_url = ""
        for alt, url in img_map:
            score = len(title_toks & _tokenize(alt))
            if score > best_score:
                best_score = score
                best_url = url
        # Require at least 2 overlapping content words to avoid spurious matches.
        if best_score >= 2:
            a["img"] = best_url
            filled += 1
    return filled


def extract_activities(html: str, city_key: str) -> list[dict]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set.")
    city = CITIES[city_key]
    print(f"  Asking DeepSeek to parse activities for {city['name']}...")

    prompt = f"""You are parsing a Timeout weekend activities article for {city['name']}.
Find EVERY event/activity listed in the article — typically 15 to 25 items.
Do NOT skip events. Do NOT stop early. The article contains many short event blurbs
each starting with a verb-led headline like "Wander…", "Lose yourself…", "Watch…".

Return ONLY a valid JSON array — no markdown, no explanation, no preamble.

Each item must have exactly these keys:
  id        (integer, 1-based)
  title     (string, short event name — strip the verb-led intro if any)
  cat       (string, exactly one of: art / music / pop-up / film / market / aquarium / nature / nightlife / community)
  e         (string, single emoji matching the category)
  loc       (string, "Venue, Neighbourhood")
  lat       (number, GPS latitude for the actual venue in {city['name']})
  lng       (number, GPS longitude for the actual venue in {city['name']})
  time      (string, opening hours or time)
  until     (string, end date like "Until May 31" or "Ongoing")
  price     (string, e.g. "Free" or "{city['currency']}300")
  free      (integer, 1 if free entry, else 0)
  desc      (string, one punchy sentence — what makes it worth going)
  img       (string, full image URL from the article, or "" if none found)

Category emoji guide: art=🎨 music=🎵 pop-up=⭐ film=🎬 market=🛍 aquarium=🌊 nature=🌿 nightlife=🌙 community=🐾

CRITICAL — coordinate accuracy:
For lat/lng use real GPS coordinates of the actual venue. Wrong pins make the map useless.
If a venue spans multiple locations, use the primary or anchor venue.
Bounding box for sanity: lat {city['bounds'][0]}–{city['bounds'][1]}, lng {city['bounds'][2]}–{city['bounds'][3]}

HTML content from Timeout (truncated to first 80 000 chars):
{html[:80000]}
"""

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek/deepseek-v4-flash",
            "max_tokens": 12000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
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


def audit_coordinates(city_key: str, activities: list[dict]) -> None:
    """Warn about coordinates outside the city bounding box."""
    city = CITIES[city_key]
    lat_min, lat_max, lng_min, lng_max = city["bounds"]
    bad = []
    for a in activities:
        lat, lng = a.get("lat", 0), a.get("lng", 0)
        if not (lat_min <= lat <= lat_max and lng_min <= lng <= lng_max):
            bad.append(f"    ⚠ id={a['id']} '{a['title']}': lat={lat}, lng={lng}")
    if bad:
        print(f"  → COORDINATE AUDIT: {len(bad)} suspect pin(s) in {city['name']}:")
        for b in bad:
            print(b)
    else:
        print(f"  → Coordinate audit: all {len(activities)} pins within {city['name']} bounds ✓")


def weekend_label() -> str:
    today = datetime.now()
    days_ahead = (5 - today.weekday()) % 7 or 7
    saturday = today + timedelta(days=days_ahead)
    sunday = saturday + timedelta(days=1)
    return f"{saturday.strftime('%b')} {saturday.day}–{sunday.day}, {sunday.year}"


def update_html_city(city_key: str, activities: list[dict], label: str) -> None:
    """Replace one city's data array and label variable in index.html."""
    city = CITIES[city_key]
    html = HTML_FILE.read_text(encoding="utf-8")

    # Replace var A_CITYKEY = [...];
    var_name = city["var"]
    new_js = f"var {var_name} = " + json.dumps(activities, ensure_ascii=False, separators=(", ", ":")) + ";"
    html, n = re.subn(rf"var {var_name} = \[.*?\];", new_js, html, flags=re.DOTALL)
    if n == 0:
        raise ValueError(f"Could not find 'var {var_name} = [...]' in HTML — pattern mismatch.")

    # Replace var LABEL_CITYKEY = "...";
    label_var = city["label_var"]
    html, n = re.subn(
        rf'var {label_var} = "[^"]*";',
        f'var {label_var} = "{label}";',
        html
    )
    if n == 0:
        raise ValueError(f"Could not find 'var {label_var} = \"...\"' in HTML — pattern mismatch.")

    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"  → {city_key} updated in HTML ({len(activities)} activities, {label})")


def git_push(label: str) -> None:
    import subprocess
    repo = HTML_FILE.parent
    cmds = [
        ["git", "add", "index.html"],
        ["git", "commit", "-m", f"Auto-update: weekend picks {label} (all cities)"],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        print(result.stdout.strip() or result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
    print("  → Pushed to GitHub → Vercel will redeploy automatically")


def main():
    label = weekend_label()
    print(f"Weekend label: {label}\n")

    failed = []
    city_keys = list(CITIES.keys())
    for i, city_key in enumerate(city_keys):
        print(f"── {CITIES[city_key]['name']} ──────────────────────────")
        try:
            html = fetch_page(CITIES[city_key]["url"])
            activities = extract_activities(html, city_key)
            img_map = build_image_map(html)
            filled = fill_missing_images(activities, img_map)
            missing = sum(1 for a in activities if not a.get("img"))
            print(f"  → Image fallback: filled {filled}, still missing {missing} (pool: {len(img_map)} alt-tagged images)")
            audit_coordinates(city_key, activities)
            update_html_city(city_key, activities, label)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            failed.append(city_key)
        print()
        # Brief pause between cities to avoid API rate limits
        if i < len(city_keys) - 1:
            import time
            time.sleep(5)

    if len(failed) == len(CITIES):
        print("All cities failed — not pushing.", file=sys.stderr)
        sys.exit(1)

    if failed:
        print(f"Note: {len(failed)} city/cities failed but others succeeded — pushing partial update.")
        print(f"  Failed: {', '.join(failed)}")

    git_push(label)
    print("\nDone ✓")


if __name__ == "__main__":
    main()
