#!/usr/bin/env python3
"""Score past brief calls against what actually happened.

Each brief records one line like
    "GW11 · Captain: Haaland · Transfer: Calvert-Lewin out, N.Jackson in"
This script reads those lines, looks up the real points, and reports for each gameweek:
- the captain call: his points, the manager's actual captain, and the best-scoring player
  in the manager's starting XI that week (the hindsight pick);
- the transfer call: points for the player bought and the player sold over that gameweek
  and the next two that have been played, and whether the manager made the move.

    python3 scripts/fpl_scorecard.py --team-id 1234567 \\
        --call "GW11 · Captain: Haaland · Transfer: Calvert-Lewin out, N.Jackson in"

Standard library only. It reports facts; it doesn't grade the manager.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone

from fpl_snapshot import FetchError, Source, find_player

CALL = re.compile(r"GW\s*(?P<gw>\d+)")
CAPTAIN = re.compile(r"Captain:\s*(?P<name>[^·(]+?)\s*(?:·|\(|$)")
TRANSFER = re.compile(r"(?P<out>[^·,:()]+?)\s+out,\s*(?P<inn>[^·,()]+?)\s+in")
HORIZON = 3  # the transfer gameweek and the next two


def parse_call(text):
    """'GW11 · Captain: X · Transfer: A out, B in (2nd: C out, D in)' -> dict, or None."""
    m = CALL.search(text or "")
    if not m:
        return None
    cap = CAPTAIN.search(text)
    moves = [(t.group("out").strip(), t.group("inn").strip()) for t in TRANSFER.finditer(text)]
    return {"gw": int(m.group("gw")), "captain": cap.group("name").strip() if cap else None,
            "transfers": moves, "text": text}


def points_by_round(src, pid):
    out = {}
    for r in src.get(f"element-summary/{pid}/").get("history", []):
        out[r["round"]] = out.get(r["round"], 0) + r.get("total_points", 0)
    return out


def score(src, team_id, calls, now=None):
    boot = src.get("bootstrap-static/")
    elements = boot["elements"]
    by_id = {e["id"]: e for e in elements}
    now = now or datetime.now(timezone.utc)
    # A gameweek counts once its deadline has passed; "finished" says whether every match is done.
    started = {ev["id"]: bool(ev.get("finished")) for ev in boot["events"]
               if datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) < now}
    last_played = max(started) if started else 0
    try:
        transfers = src.get(f"entry/{team_id}/transfers/")
    except FetchError:
        transfers = None
    pts_cache = {}

    def pts(pid):
        if pid not in pts_cache:
            pts_cache[pid] = points_by_round(src, pid)
        return pts_cache[pid]

    def player(name):
        """Find a player; when a short name is shared (two Palmers), take the most-owned one
        and say so, because a brief names the player the manager would recognise."""
        try:
            return find_player(elements, name)
        except SystemExit as e:
            if "ambiguous" not in str(e):
                return {"error": str(e)}
            from fpl_snapshot import norm
            same = [x for x in elements if norm(x["web_name"]) == norm(name)] or \
                   [x for x in elements if norm(name) in norm(x["web_name"])]
            if not same:
                return {"error": str(e)}
            pick = max(same, key=lambda x: float(x.get("selected_by_percent") or 0))
            return dict(pick, matched_note=f"'{name}' matches {len(same)} players; scored the most-owned one ({by_id[pick['id']]['web_name']}, id {pick['id']}).")

    rows = []
    for c in sorted(calls, key=lambda c: c["gw"]):
        gw = c["gw"]
        row = {"gw": gw, "call": c["text"], "played": gw in started,
               "in_progress": gw in started and not started[gw]}
        if not row["played"]:
            rows.append(row)
            continue
        try:
            picks = src.get(f"entry/{team_id}/event/{gw}/picks/")["picks"]
        except FetchError:
            picks = []
        xi = [p for p in picks if p.get("position", 99) <= 11]
        actual_cap = next((p["element"] for p in picks if p.get("is_captain")), None)

        if c.get("captain"):
            p = player(c["captain"])
            cap = {"recommended": c["captain"]}
            if "error" in p:
                cap["error"] = p["error"]
            else:
                cap["recommended_points"] = pts(p["id"]).get(gw, 0)
                cap["followed"] = actual_cap == p["id"] if actual_cap else None
            if actual_cap:
                cap["actual"] = by_id[actual_cap]["web_name"]
                cap["actual_points"] = pts(actual_cap).get(gw, 0)
            if xi:
                best = max(xi, key=lambda q: pts(q["element"]).get(gw, 0))
                cap["best_in_xi"] = by_id[best["element"]]["web_name"]
                cap["best_in_xi_points"] = pts(best["element"]).get(gw, 0)
                if "recommended_points" in cap:
                    # What the captaincy cost against the hindsight pick (captain points count double).
                    cap["missed_vs_best"] = cap["best_in_xi_points"] - cap["recommended_points"]
            row["captain"] = cap

        moves = []
        window = [g for g in range(gw, gw + HORIZON) if g <= last_played]
        for out_name, in_name in c.get("transfers") or []:
            o, i = player(out_name), player(in_name)
            m = {"out": out_name, "in": in_name, "gameweeks": f"GW{window[0]}-{window[-1]}" if window else None}
            if "error" in o or "error" in i:
                m["error"] = o.get("error") or i.get("error")
            else:
                m["out_points"] = sum(pts(o["id"]).get(g, 0) for g in window)
                m["in_points"] = sum(pts(i["id"]).get(g, 0) for g in window)
                m["net"] = m["in_points"] - m["out_points"]
                notes = [x["matched_note"] for x in (o, i) if x.get("matched_note")]
                if notes:
                    m["note"] = " ".join(notes)
                if transfers is not None:
                    m["made"] = any(t["element_in"] == i["id"] and t["element_out"] == o["id"]
                                    and gw - 1 <= t["event"] <= gw for t in transfers)
            moves.append(m)
        if moves:
            row["transfers"] = moves
        rows.append(row)

    done = [r for r in rows if r.get("played")]
    caps = [r["captain"] for r in done if "missed_vs_best" in (r.get("captain") or {})]
    nets = [m["net"] for r in done for m in r.get("transfers", []) if "net" in m]
    return {
        "calls": rows,
        "summary": {
            "gameweeks_scored": len(done),
            "in_progress": [r["gw"] for r in done if r.get("in_progress")],
            "captain_points": sum(c["recommended_points"] for c in caps),
            "captain_best_possible": sum(c["best_in_xi_points"] for c in caps),
            "captain_hits": sum(1 for c in caps if c["missed_vs_best"] == 0),
            "transfer_net_points": sum(nets),
            "transfers_scored": len(nets),
            "transfers_that_won": sum(1 for n in nets if n > 0),
        },
        "note": ("Captain points are single (the armband doubles them). The best player in the XI "
                 "is hindsight, so missing him isn't always a mistake. Transfer points cover the "
                 f"move's gameweek and the next {HORIZON - 1} that have been played."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--call", action="append", default=[], help="one recorded call line; repeat for each gameweek")
    ap.add_argument("--data-dir", help="read saved API JSON instead of the live API (tests)")
    ap.add_argument("--now", help="ISO time to treat as now (tests)")
    args = ap.parse_args(argv)
    calls = [c for c in (parse_call(t) for t in args.call) if c]
    if not calls:
        raise SystemExit("No calls to score. Pass --call with lines like 'GW11 · Captain: X · Transfer: A out, B in'.")
    # When a gameweek has two recorded calls (a re-run), keep both: the page should show it.
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    try:
        out = score(Source(args.data_dir), args.team_id, calls, now)
    except FetchError as e:
        raise SystemExit(str(e))
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    sys.exit(main())
