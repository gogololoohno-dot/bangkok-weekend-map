"""Registry. Adding a player = one module + one line here."""

from sources import antseed, chutes, engy, engy_emissions, gm, surplus

SOURCES = [chutes, surplus, engy, engy_emissions, antseed, gm]

PLAYERS = {
    "chutes":   {"label": "Chutes (SN64)",  "kind": "api"},
    "antseed":  {"label": "AntSeed",        "kind": "scrape"},
    "surplus":  {"label": "Surplus",        "kind": "scrape"},
    "engy":     {"label": "Engy (SN53)",    "kind": "scrape"},
    "gm":       {"label": "gm (SN28)",      "kind": "scrape"},
}
