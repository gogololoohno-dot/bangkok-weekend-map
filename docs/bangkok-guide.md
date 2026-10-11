# Bangkok weekend guide

The static site uses `index.html`, `guide.js` and `guide.css`. Bangkok events and source health are embedded together in `index.html`. Other cities retain their existing collectors.

## Friday updates

Windows Task Scheduler task **BangkokWeekendUpdate** runs `uv run --with requests "C:\Users\punth\New folder\update_bangkok.py" --log` at 09:00 Asia/Bangkok on Friday, with Saturday and Sunday catch-up triggers. It uses the user's existing `OPENROUTER_API_KEY`. GitHub pushes trigger Vercel deployment. The laptop must be available for the scheduled job to run.

The Bangkok collector reads Time Out, BK Magazine's current roundup, Bangkok Art City, River City and Eventpop through the existing Jina Reader integration. Collection failures are displayed in source health; they are not reported as zero events. No paid scraping fallback is used for Bangkok. River City and Eventpop were unavailable during the initial validation on 11 October 2026. Ticketmelon and other booking links are also discovered through editorial listings.

The extraction service supplies source-backed names, dates and observed links, never coordinates. Validation rejects missing detail links, non-Bangkok events, invalid dates and events outside the Friday–Sunday edition. Ongoing places and exhibitions can carry forward, with their original check timestamps. Complete source failure or an empty edition leaves the previous file intact. Writes are atomic. Only `index.html` is committed by the scheduled job, so unrelated staged work is excluded.

Source extraction is imperfect: a published link is not proof that every extracted statement is correct. Ambiguous information remains empty and the linked source is visible. The updater does not claim live ticket inventory. Date-only listings expire at the end of their final Bangkok calendar day; explicitly supplied after-midnight end times take precedence.

## Venue corrections

Edit `bangkok_venues.json`. Each entry has a canonical name, aliases, neighborhood, coordinates, a verification date and an evidence URL. Set `verified: true` only after checking a venue-specific map location against that evidence. Prefer the place coordinates in an official map link, not its viewport centre. Street-wide events, citywide programmes and unknown meeting points remain unpinned. A named building pin does not identify its interior room; use the event's floor/entrance notes.

Aliases match exactly after punctuation/case normalization. Never use a whole mall as an alias for one tenant. Coordinates from event extraction are discarded. Venue corrections survive each refresh. Several events at the same coordinates share a pin, and the detail panel lists other events at the same venue.

## Validation and preview

Run `python -m unittest discover -s tests -p test_bangkok_pipeline.py -v` and `node --check guide.js`.

Refresh without publishing: `python update_bangkok.py --bangkok-only --force --no-push`.

Serve the checkout with `python -m http.server 8765 --bind 127.0.0.1`. Check combined category/day/budget/neighborhood filters, a saved event after reload, a share link, event/ticket/directions links, unconfirmed locations, marker positions at different zooms, mobile list/map switching, and other city tabs.

The interface uses browser storage for saved event IDs, so saves are local to a browser. Sharing uses a stable event ID in the URL fragment; links work while the event remains in the published edition. The Friday refresh is the collection boundary; finished events are hidden locally as time passes, and can be shown with Include finished.
