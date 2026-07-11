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


def fetch_with_jina(url: str) -> str:
    """Primary: scrape a page via Jina Reader and return clean markdown.
    Free tier, no API key needed. Jina runs headless browser in the cloud,
    handles JS rendering and anti-bot protections."""
    print("  Fetching via Jina Reader...")
    resp = requests.get(
        f"https://r.jina.ai/{url}",
        headers={"Accept": "text/markdown"},
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.text
    if not text or len(text) < 500:
        raise RuntimeError(f"Jina returned too little content ({len(text)} chars)")
    # Jina wraps response in markdown with a header footer. The actual
    # article content starts after the first `---` or at the "Markdown Content:" line.
    # Strip the Jina header metadata (Title, URL Source, Published Time markers).
    for sep in ("\n---\n", "Markdown Content:\n\n"):
        idx = text.find(sep)
        if idx != -1:
            text = text[idx + len(sep):]
            break
    text = text.strip()
    print(f"  → {len(text)} chars of clean markdown")
    return text


def fetch_with_agentcash_firecrawl(url: str) -> str:
    """Fallback: scrape via AgentCash CLI → Firecrawl x402 endpoint.
    Uses npx agentcash to handle the x402 payment handshake automatically."""
    import subprocess
    import json as _json
    print("  Fetching via AgentCash + Firecrawl...")
    body = _json.dumps({"url": url, "formats": ["markdown"], "onlyMainContent": True})
    result = subprocess.run(
        ["npx", "agentcash", "fetch", "POST",
         "https://enrichx402.com/api/firecrawl/scrape",
         "--body", body],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AgentCash Firecrawl failed (code={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    data = _json.loads(result.stdout)
    markdown = data.get("data", {}).get("markdown", "")
    if not markdown:
        raise RuntimeError("AgentCash Firecrawl returned empty markdown")
    print(f"  → {len(markdown)} chars via AgentCash")
    return markdown


def extract_activities(content: str, city_key: str, source: str = "Timeout") -> list[dict]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set.")
    city = CITIES[city_key]
    print(f"  Asking DeepSeek to parse activities for {city['name']}...")

    prompt = f"""Parse {source} weekend activities for {city['name']}.

Return ONLY a JSON array of ALL events in the article (10-25 items). No markdown, no explanation.

Each item:
  id (int, 1-based)
  title (string, short event name)
  cat (string: art/music/pop-up/film/market/aquarium/nature/nightlife/community)
  e (string, emoji: 🎨🎵⭐🎬🛍🌊🌿🌙🐾)
  loc (string, "Venue, Neighbourhood")
  lat (number), lng (number) — real GPS of venue, within {city['bounds']}
  time (string), until (string, "Until ..." or "Ongoing"), price (string)
  free (int, 1 if free else 0)
  desc (string, one punchy sentence)
  img (string, image URL or "")

Content:
{content}
"""

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek/deepseek-v4-flash",
            "max_tokens": 16384,
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
    weekday = today.weekday()  # Mon=0 ... Sun=6, Sat=5
    # Days to the Saturday of THIS weekend
    if weekday <= 5:  # Mon–Sat: Saturday is ahead or today
        days_to_saturday = 5 - weekday
    else:  # Sunday: Saturday was yesterday
        days_to_saturday = -1
    saturday = today + timedelta(days=days_to_saturday)
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


def get_events_for_city(city_key: str, url: str) -> list[dict]:
    """Hybrid: Jina Reader primary → AgentCash Firecrawl fallback on failure or <5 events."""
    try:
        md = fetch_with_jina(url)
        activities = extract_activities(md, city_key, source="Timeout")
        if len(activities) >= 5:
            return activities
        print(f"  Only {len(activities)} events — too few, trying AgentCash Firecrawl...")
    except Exception as e:
        print(f"  Jina failed: {e}")
        print("  Falling back to AgentCash Firecrawl...")
    md = fetch_with_agentcash_firecrawl(url)
    return extract_activities(md, city_key, source="Timeout")


def main():
    label = weekend_label()
    print(f"Weekend label: {label}\n")

    failed = []
    city_keys = list(CITIES.keys())
    for i, city_key in enumerate(city_keys):
        print(f"── {CITIES[city_key]['name']} ──────────────────────────")
        try:
            # Get images from raw HTML (fast HTTP GET, no LLM)
            html = fetch_page(CITIES[city_key]["url"])
            img_map = build_image_map(html)
            # Get events via hybrid pipeline
            activities = get_events_for_city(city_key, CITIES[city_key]["url"])
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
