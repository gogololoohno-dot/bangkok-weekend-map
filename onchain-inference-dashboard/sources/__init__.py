"""Registry. Adding a player = one module + one line here."""

from sources import antseed, blockrun, chutes, engy, engy_emissions, gm, surplus

SOURCES = [chutes, blockrun, surplus, engy, engy_emissions, antseed, gm]

PLAYERS = {
    "chutes":   {"label": "Chutes (SN64)",  "kind": "api"},
    "antseed":  {"label": "AntSeed",        "kind": "scrape"},
    "surplus":  {"label": "Surplus",        "kind": "scrape"},
    "engy":     {"label": "Engy (SN53)",    "kind": "scrape"},
    "gm":       {"label": "gm (SN28)",      "kind": "scrape"},
    "blockrun": {"label": "BlockRun",       "kind": "api"},
}
