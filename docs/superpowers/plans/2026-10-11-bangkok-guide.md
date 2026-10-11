# Bangkok guide implementation plan

Approved scope: the reliable Bangkok guide proposed in this chat, including the quick browsing improvements. Preserve other cities and the Friday Windows scheduled task.

1. Add source-backed Bangkok extraction, stable event IDs, date validation, duplicate merging, a persistent venue registry and source health metadata. Never accept model-generated coordinates. Keep the previous edition if all sources fail or the result is empty. Test failure, duplicate, date and location cases offline.
2. Improve the existing static page: useful detail links, dates, source provenance, verified locations, search/day/budget/neighborhood filters, saved events, sharing and a mobile list/map toggle. Fix marker anchoring and use a bounded detail panel. Check desktop and mobile in a browser.
3. Refresh Bangkok from public source pages using the existing configured extraction service; review the resulting events and verify venue coordinates from source evidence. Add supplemental sources without changing the other city collectors.
4. Verify Python tests, JavaScript syntax, updater dry run, source link coverage and browser behavior. Commit only task files, integrate into the scheduled checkout, push and verify the Vercel production page.

Files: index.html, update_bangkok.py, bangkok_pipeline.py, bangkok_venues.json, tests/test_bangkok_pipeline.py, docs/bangkok-guide.md. Keep publication data embedded in index.html so a single atomic replacement contains both events and source health. The venue registry is checked in; unresolved venues remain visible in the list without a misleading map pin.

Acceptance: every published Bangkok event has an observed detail URL; every exact Bangkok pin comes from a verified venue record; more than one source contributes; Friday updates preserve corrections and report unavailable sources; other cities remain usable.
