#!/usr/bin/env python3
"""Compact snapshot of an FPL team for a pre-deadline brief.

Pulls the public Fantasy Premier League endpoints and prints one small JSON
document with everything a gameweek brief needs: the next deadline, the squad
with form/price/injury news and upcoming fixtures, bank, an estimate of free
transfers, chips, blank/double gameweeks, and top-projected candidates per
position.

The full bootstrap file is several MB, which is too big for most agent web
readers; this script exists so the agent only reads the ~20 KB that matters.

Standard library only. Examples:
    python3 fpl_snapshot.py --team-id 1234567
    python3 fpl_snapshot.py --team-id 1234567 --squad "Raya,Saka,Haaland,..."
    python3 fpl_snapshot.py --team-id 1234567 --data-dir ./saved_json   # offline

Public data shows a squad as it was locked at the LAST deadline. Transfers made
since then are private until the next deadline; pass --squad to override.
"""

import argparse
import json
import os
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone

BASE = "https://fantasy.premierleague.com/api/"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit",
              "bboost": "Bench Boost", "3xc": "Triple Captain"}
MAX_FREE_TRANSFERS = 5


class Source:
    """Fetches an endpoint from the live API, or from saved JSON files."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.cache = {}

    def get(self, path):
        if path in self.cache:
            return self.cache[path]
        if self.data_dir:
            name = path.strip("/").replace("/", "_") + ".json"
            with open(os.path.join(self.data_dir, name), encoding="utf-8") as f:
                data = json.load(f)
        else:
            req = urllib.request.Request(
                BASE + path, headers={"User-Agent": "fpl-gameweek-brief/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        self.cache[path] = data
        return data


FOLD = str.maketrans({"ø": "o", "Ø": "o", "ß": "ss", "æ": "ae", "Æ": "ae", "ł": "l",
                      "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "œ": "oe", "Œ": "oe"})
SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}


def norm(s):
    s = unicodedata.normalize("NFKD", s.translate(FOLD))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(".", "").strip()


def find_player(elements, name):
    """Match a player by web_name, then by full name; raise if ambiguous."""
    n = norm(name)
    exact = [e for e in elements if norm(e["web_name"]) == n]
    if len(exact) == 1:
        return exact[0]
    pool = exact or [e for e in elements
                     if n in norm(e["web_name"])
                     or n in norm(f'{e["first_name"]} {e["second_name"]}')]
    if len(pool) == 1:
        return pool[0]
    if not pool:
        raise SystemExit(f"No player matches '{name}'.")
    opts = ", ".join(f'{e["web_name"]} (id {e["id"]})' for e in pool[:6])
    raise SystemExit(f"'{name}' is ambiguous: {opts}. Use a fuller name or an id.")


def fixtures_for(team_id, gws, fixtures, teams):
    out = []
    for gw in gws:
        fs = [f for f in fixtures if f.get("event") == gw
              and team_id in (f["team_h"], f["team_a"])]
        if not fs:
            out.append(f"GW{gw}: BLANK")
            continue
        parts = []
        for f in fs:
            if f["team_h"] == team_id:
                parts.append(f'{teams[f["team_a"]]} (H) {f["team_h_difficulty"]}')
            else:
                parts.append(f'{teams[f["team_h"]]} (A) {f["team_a_difficulty"]}')
        out.append(f"GW{gw}: " + " + ".join(parts))
    return out


def player_row(e, teams, fixtures, gws):
    return {
        "id": e["id"],
        "name": e["web_name"],
        "club": teams[e["team"]],
        "pos": POS[e["element_type"]],
        "price": e["now_cost"] / 10,
        "price_change_this_gw": e["cost_change_event"] / 10,
        "status": e["status"],  # a=available d=doubtful i=injured s=suspended u=unavailable
        "chance_next": e["chance_of_playing_next_round"],
        "news": e["news"] or None,
        "form": float(e["form"]),
        "ep_next": float(e["ep_next"] or 0),
        "total_points": e["total_points"],
        "minutes": e["minutes"],
        "owned_pct": float(e["selected_by_percent"]),
        "transfers_in_gw": e["transfers_in_event"],
        "transfers_out_gw": e["transfers_out_event"],
        "fixtures": fixtures_for(e["team"], gws, fixtures, teams),
    }


def estimate_free_transfers(history, started_event, next_gw):
    """Replay the season under current rules: +1 per gameweek, capped at 5,
    transfers on Wildcard/Free Hit weeks don't use any. An estimate only."""
    chip_weeks = {c["event"] for c in history.get("chips", [])
                  if c["name"] in ("wildcard", "freehit")}
    made = {c["event"]: c["event_transfers"] for c in history.get("current", [])}
    ft = 1  # available for the gameweek after the one you joined in
    for gw in range(started_event + 1, next_gw):
        used = 0 if gw in chip_weeks else made.get(gw, 0)
        ft = max(1, min(MAX_FREE_TRANSFERS, ft - used + 1))
    return ft


def chips_status(bootstrap, history, next_gw):
    used = history.get("chips", [])
    status = []
    for c in bootstrap.get("chips", []):
        start, stop = c.get("start_event"), c.get("stop_event")
        if not (start <= next_gw <= stop):
            continue
        played = [u for u in used if u["name"] == c["name"] and start <= u["event"] <= stop]
        status.append({
            "chip": CHIP_NAMES.get(c["name"], c["name"]),
            "window": f"GW{start}-{stop}",
            "available": not played,
            "played_in": played[0]["event"] if played else None,
        })
    return status


def blank_double(fixtures, teams, gws):
    notes = []
    for gw in gws:
        count = {t: 0 for t in teams}
        for f in fixtures:
            if f.get("event") == gw:
                count[f["team_h"]] += 1
                count[f["team_a"]] += 1
        blanks = [teams[t] for t, n in count.items() if n == 0]
        doubles = [teams[t] for t, n in count.items() if n > 1]
        if blanks or doubles:
            notes.append({"gw": gw, "blank": blanks, "double": doubles})
    return notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--squad", help="Comma-separated names (or ids) of the current 15, "
                    "to override the public squad after mid-week transfers.")
    ap.add_argument("--bank", type=float, help="Current bank in £m, if --squad changed it.")
    ap.add_argument("--candidates", type=int, default=6, help="Candidates per position.")
    ap.add_argument("--horizon", type=int, default=4, help="Gameweeks of fixtures to show.")
    ap.add_argument("--min-minutes", type=int, default=450,
                    help="Minimum season minutes for a transfer candidate (default 450, about 5 full games).")
    ap.add_argument("--data-dir", help="Read saved JSON instead of the live API.")
    ap.add_argument("--now", help="Override the current time (ISO 8601), for testing.")
    args = ap.parse_args()

    src = Source(args.data_dir)
    boot = src.get("bootstrap-static/")
    fixtures = src.get("fixtures/")
    entry = src.get(f"entry/{args.team_id}/")
    history = src.get(f"entry/{args.team_id}/history/")

    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    elements = boot["elements"]
    by_id = {e["id"]: e for e in elements}

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    upcoming = [ev for ev in boot["events"]
                if datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) > now]
    if not upcoming:
        print(json.dumps({"season_over": True}))
        return
    nxt = upcoming[0]
    next_gw = nxt["id"]
    deadline = datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    last_gw = next_gw - 1
    gws = [g for g in range(next_gw, next_gw + args.horizon)
           if g <= max(ev["id"] for ev in boot["events"])]

    note = None
    if args.squad:
        ids = []
        for token in [t.strip() for t in args.squad.split(",") if t.strip()]:
            ids.append(int(token) if token.isdigit() else find_player(elements, token)["id"])
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise SystemExit(f"Unknown player ids: {unknown}.")
        if len(set(ids)) != 15:
            raise SystemExit(f"--squad needs 15 different players; got {len(set(ids))}.")
        shape = {p: 0 for p in SHAPE}
        for i in ids:
            shape[POS[by_id[i]["element_type"]]] += 1
        if shape != SHAPE:
            got = ", ".join(f"{n} {p}" for p, n in shape.items())
            raise SystemExit(f"--squad must be 2 GK, 5 DEF, 5 MID, 3 FWD; got {got}.")
        squad_src = "manual (--squad)"
        captain = vice = None
        order = ids
    else:
        if last_gw < 1:
            raise SystemExit("No gameweek has locked yet; pass --squad.")
        picks = src.get(f"entry/{args.team_id}/event/{last_gw}/picks/")
        order = [p["element"] for p in sorted(picks["picks"], key=lambda p: p["position"])]
        captain = next((p["element"] for p in picks["picks"] if p["is_captain"]), None)
        vice = next((p["element"] for p in picks["picks"] if p["is_vice_captain"]), None)
        squad_src = f"public picks locked at GW{last_gw} deadline"
        note = ("Transfers made since the last deadline are not visible here. "
                "Ask the manager, or re-run with --squad.")

    squad = []
    for i, pid in enumerate(order, 1):
        row = player_row(by_id[pid], teams, fixtures, gws)
        row["slot"] = i if not args.squad else None
        row["role"] = ("captain" if pid == captain else
                       "vice" if pid == vice else None)
        squad.append(row)

    owned = set(order)
    candidates = {}
    for pt, label in POS.items():
        pool = [e for e in elements if e["element_type"] == pt and e["id"] not in owned
                and e["status"] == "a" and e["minutes"] >= args.min_minutes]
        pool.sort(key=lambda e: float(e["ep_next"] or 0), reverse=True)
        candidates[label] = [player_row(e, teams, fixtures, gws) for e in pool[:args.candidates]]

    club_counts = {}
    for row in squad:
        club_counts[row["club"]] = club_counts.get(row["club"], 0) + 1

    last_bank = entry.get("last_deadline_bank")
    out = {
        "team": {"id": args.team_id, "name": entry.get("name"),
                 "overall_points": entry.get("summary_overall_points"),
                 "overall_rank": entry.get("summary_overall_rank")},
        "next_gameweek": next_gw,
        "deadline_utc": deadline.isoformat(),
        "hours_to_deadline": round((deadline - now).total_seconds() / 3600, 1),
        "squad_source": squad_src,
        "squad_note": note,
        "bank": args.bank if args.bank is not None else (last_bank / 10 if last_bank is not None else None),
        "team_value": (entry.get("last_deadline_value") or 0) / 10 or None,
        "free_transfers_estimate": estimate_free_transfers(
            history, entry.get("started_event", 1), next_gw),
        "chips": chips_status(boot, history, next_gw),
        "blank_double_gws": blank_double(fixtures, teams, gws),
        "clubs_at_limit": [c for c, n in club_counts.items() if n >= 3],
        "squad": squad,
        "candidates": candidates,
        "fdr_key": "Fixture number is FPL difficulty, 1 easy to 5 hard.",
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
