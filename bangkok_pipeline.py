"""Bangkok collection and validation. No model-generated map coordinates."""
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse
from html.parser import HTMLParser
import requests

BKK = timezone(timedelta(hours=7))
ROOT = Path(__file__).parent
SOURCES = [
    ("Time Out", "https://www.timeout.com/bangkok/things-to-do/the-best-things-to-do-in-bangkok-this-weekend"),
    ("BK Magazine", "https://www.bkmagazine.com/things-to-do/"),
    ("Bangkok Art City", "https://www.bangkokartcity.org/"),
    ("River City", "https://rivercitybangkok.com/whats-on/"),
    ("Eventpop", "https://www.eventpop.me/?locale=en"),
]


def normalize(value):
    return re.sub(r"[\W_]+", " ", str(value).casefold()).strip()


def safe_url(value):
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value)
    return value if parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username else ""


def observed_urls(content):
    return {html.unescape(u.rstrip(".,;")) for u in re.findall(r'https?://[^\s<>"\)\]]+', content)}


def date_value(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def weekend_window(now):
    # Sunday belongs to the weekend that started two days ago.
    friday = now.date() + timedelta(days=4 - now.weekday())
    return friday, friday + timedelta(days=2)


def in_weekend(event, now):
    friday, sunday = weekend_window(now)
    if event.get("kind") == "anytime":
        return True
    start, end = date_value(event.get("start_date")), date_value(event.get("end_date"))
    return bool(start and end and start <= sunday and end >= friday)


def apply_venue(event, venues):
    event.update(lat=None, lng=None, location_status="unconfirmed", maps_url="", location_evidence_url="")
    name = normalize(event.get("venue", ""))
    for key, venue in venues.items():
        names = [venue["name"]] + venue.get("aliases", [])
        if name not in [normalize(n) for n in names] and event.get("detail_url") not in venue.get("event_urls", []):
            continue
        event["venue_id"] = key
        event["venue"] = venue["name"]
        event["neighborhood"] = venue.get("neighborhood", event.get("neighborhood", ""))
        if venue.get("verified") and safe_url(venue.get("evidence_url", "")):
            lat, lng = venue.get("lat"), venue.get("lng")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and 13.5 <= lat <= 14 and 100.3 <= lng <= 100.95:
                event.update(lat=lat, lng=lng, location_status="verified",
                             location_evidence_url=venue["evidence_url"])
                event["maps_url"] = safe_url(venue.get("maps_url", ""))
        return event
    return event


def clean_event(raw, source, source_url, links, venues, now):
    if not isinstance(raw, dict):
        raise ValueError("Event must be an object")
    event = dict(raw)
    event["loc"] = event.get("loc") or event.get("venue")
    if event.get("event_name"):
        event["title"] = event["event_name"]
    for key in ("title", "venue", "loc", "desc"):
        if not isinstance(event.get(key), str) or not event[key].strip():
            raise ValueError("Missing " + key)
    detail = safe_url(event.get("detail_url", ""))
    if not detail or detail not in links or detail == source_url:
        raise ValueError("Missing observed event detail URL")
    if event.get("city", "").casefold() != "bangkok":
        raise ValueError("Not a Bangkok event")
    if event.get("kind") not in ("event", "exhibition", "anytime"):
        event["kind"] = "event"
    if event["kind"] != "anytime":
        start, end = date_value(event.get("start_date")), date_value(event.get("end_date"))
        if not start or not end or start > end:
            raise ValueError("Invalid event dates")
    if not in_weekend(event, now):
        raise ValueError("Outside this weekend")
    for key in ("official_url", "ticket_url", "img"):
        url = safe_url(event.get(key, ""))
        event[key] = url if url in links else ""
    for key in ("time", "until", "price", "neighborhood", "access", "booking", "language"):
        event[key] = str(event.get(key) or "")
    event["price"] = event["price"] or "Check event details"
    if not event["until"]:
        event["until"] = "Ongoing" if event["kind"] == "anytime" else event["start_date"] + " – " + event["end_date"]
    event["free"] = 1 if event.get("free") is True or event.get("free") == 1 else 0
    minimum = event.get("price_min")
    event["price_min"] = minimum if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and minimum >= 0 else None
    event["weekdays"] = [d for d in event.get("weekdays", []) if isinstance(d, int) and 0 <= d <= 6]
    event["period"] = event.get("period") if event.get("period") in ("day", "evening", "both") else "unknown"
    end_at = event.get("end_at")
    if end_at:
        parsed = datetime.fromisoformat(end_at)
        if parsed.tzinfo is None or parsed.date() < date_value(event["end_date"]):
            raise ValueError("Invalid end time")
    event["sources"] = [{"name": source, "url": source_url, "event_url": detail}]
    event["checked_at"] = now.isoformat(timespec="seconds")
    identity = normalize(event.get("event_name") or event["title"]) + "|" + normalize(event["venue"]) + "|" + str(event.get("start_date") or "anytime")
    event["id"] = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return apply_venue(event, venues)


def merge_events(events, previous=()):
    merged = []
    for event in events:
        match = None
        for other in merged:
            same_dates = (event.get("start_date"), event.get("end_date")) == (other.get("start_date"), other.get("end_date"))
            if event.get("kind") == other.get("kind") == "exhibition":
                same_dates = event.get("end_date") == other.get("end_date")
            same_venue = normalize(event["venue"]) == normalize(other["venue"]) or bool(event.get("venue_id") and event.get("venue_id") == other.get("venue_id"))
            same_link = event["detail_url"] == other["detail_url"]
            name = normalize(event.get("event_name") or event["title"])
            other_name = normalize(other.get("event_name") or other["title"])
            # Strip an appended calendar date, not artist or session names.
            date_suffix = r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d.*$"
            name = re.sub(date_suffix, "", name).strip()
            other_name = re.sub(date_suffix, "", other_name).strip()
            similarity = SequenceMatcher(None, name, other_name).ratio()
            contained = min(len(name), len(other_name)) >= 10 and (name in other_name or other_name in name)
            if same_link or (same_dates and same_venue and (similarity >= .8 or contained)):
                match = other
                break
        if match:
            match["sources"] = list({s["name"]: s for s in event["sources"] + match["sources"]}.values())
            for key in ("official_url", "ticket_url", "img", "access", "booking", "language"):
                if not match.get(key):
                    match[key] = event.get(key, "")
            if not match.get("ticket_url") and urlparse(event["detail_url"]).hostname in ("www.thaiticketmajor.com", "www.ticketmelon.com", "www.eventpop.me"):
                match["ticket_url"] = event["detail_url"]
        else:
            merged.append(event)
    old_by_link = {e.get("detail_url"): e for e in previous if e.get("detail_url")}
    old_by_id = {e["id"]: e for e in previous}
    for event in merged:
        old = old_by_link.get(event["detail_url"], old_by_id.get(event["id"], {}))
        event["id"] = old.get("id", event["id"])
        event["first_seen"] = old.get("first_seen", event["checked_at"])
    return merged


def read_previous(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(re.search(r"var A_BANGKOK = (\[.*?\]);", text, re.S)[1])


class PreviewParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "og:image":
            self.image = safe_url(attrs.get("content", ""))


def fill_previews(events, previous):
    """Images come from the linked event's public preview, not fuzzy guesses."""
    from concurrent.futures import ThreadPoolExecutor
    old_images = {e.get("detail_url"): e.get("img") for e in previous}
    def fill(event):
        if event.get("img"):
            return
        if old_images.get(event["detail_url"]):
            event["img"] = old_images[event["detail_url"]]
            return
        try:
            response = requests.get(event["detail_url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            parser = PreviewParser()
            parser.feed(response.text)
            event["img"] = parser.image
        except requests.RequestException:
            pass
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fill, events))


def collect(fetch, extract, previous, now=None):
    now = now or datetime.now(BKK)
    venues = json.loads((ROOT / "bangkok_venues.json").read_text(encoding="utf-8"))
    events, health = [], []
    for name, url in SOURCES:
        print("Bangkok source:", name, flush=True)
        try:
            content = fetch(url)
            links = observed_urls(content)
            # BK's category page links to the current weekly roundup.
            if name == "BK Magazine":
                candidates = re.findall(r'https://www\.bkmagazine\.com/things-to-do/[^\s)\]]*weekend[^\s)\]]*/', content)
                if not candidates:
                    raise ValueError("No weekly roundup found")
                url = candidates[0]
                content = fetch(url)
                links |= observed_urls(content)
            raw = extract(content, "bangkok", source=name)
            valid, rejected = [], []
            for item in raw:
                try:
                    valid.append(clean_event(item, name, url, links, venues, now))
                except (ValueError, TypeError) as exc:
                    rejected.append(str(exc))
            if not valid:
                raise ValueError("No valid weekend events: " + "; ".join(sorted(set(rejected))))
            events.extend(valid)
            health.append({"name": name, "url": url, "status": "ok", "count": len(valid), "rejected": len(rejected)})
        except Exception as exc:
            print("Source unavailable:", name, str(exc), flush=True)
            health.append({"name": name, "url": url, "status": "unavailable", "count": 0})
    if not any(s["status"] == "ok" for s in health):
        raise RuntimeError("All Bangkok sources failed; keeping previous edition")
    failed = {s["name"] for s in health if s["status"] != "ok"}
    for old in previous:
        # Carry ongoing items and valid items from a temporarily unavailable source.
        try:
            carry = old.get("kind") in ("exhibition", "anytime") or any(s["name"] in failed for s in old.get("sources", []))
            if carry and old.get("detail_url") and in_weekend(old, now):
                events.append(apply_venue(dict(old), venues))
        except ValueError:
            pass
    events = merge_events(events, previous)
    if not events:
        raise RuntimeError("Empty Bangkok edition; keeping previous edition")
    fill_previews(events, previous)
    metadata = {"updated_at": now.isoformat(timespec="seconds"), "sources": health,
                "weekend_start": weekend_window(now)[0].isoformat(),
                "weekend_end": weekend_window(now)[1].isoformat(),
                "unconfirmed_locations": sum(e["location_status"] != "verified" for e in events)}
    return events, metadata
