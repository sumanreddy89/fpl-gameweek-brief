#!/usr/bin/env python3
"""Show how an FPL manager's picks did against their small private leagues.

For each player, impact = (your multiplier - the league's average multiplier) x
his points, summed over finished gameweeks. A player's multiplier is 0 on the
bench, 1 starting, 2 as captain and 3 with Triple Captain. Impacts add up to the
manager's exact gap to the league average, before hits. Each gameweek shows its
biggest upside and downside player. Season totals are netted by position, because
players in one position replace each other: Verbruggen over Raya is one decision.

Rival squads are public only after each deadline. Standard library only.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import fpl_snapshot as snap

DIFFERENTIAL_SHARE = 0.25
RIVAL_ONLY_SHARE = 0.4
RECENT_GAMEWEEKS = 5


def member_history(src, entry, gaps):
    try:
        return src.get(f"entry/{entry}/history/")
    except snap.FetchError:
        gaps.append(f"No history for entry {entry}.")
        return None


def picks_for(src, entry, gw):
    """{player: multiplier} for a gameweek, or None if the entry wasn't playing."""
    try:
        data = src.get(f"entry/{entry}/event/{gw}/picks/")
    except snap.FetchError:
        return None
    return {p["element"]: p["multiplier"] for p in data["picks"]}


def name_of(pid, by_id):
    return by_id[pid]["web_name"] if pid in by_id else f"id {pid}"


def position_of(pid, by_id):
    return snap.POS.get(by_id.get(pid, {}).get("element_type"), "?")


def ranked(impact, split, by_id, limit, reverse):
    """Top season-long edges, split into ownership and captaincy."""
    rows = sorted(impact.items(), key=lambda kv: kv[1], reverse=reverse)
    out = []
    for pid, value in rows[:limit]:
        if (value > 0) == reverse and value != 0:
            out.append({"player": name_of(pid, by_id), "points": round(value, 1),
                        "from_ownership": round(split[pid][0], 1),
                        "from_captaincy": round(split[pid][1], 1)})
    return out


def swing(pid, value, mine, others, points, by_id):
    """How one player moved the manager against the league in one gameweek."""
    average = sum(p.get(pid, 0) for p in others) / len(others)
    return {"player": name_of(pid, by_id), "position": position_of(pid, by_id),
            "points": round(value, 1), "your_multiplier": mine.get(pid, 0),
            "league_avg_multiplier": round(average, 2), "player_points": points.get(pid, 0)}


def gameweek_row(gw, values, mine, others, points, by_id):
    """A gameweek's gap to the league, with its biggest upside and downside player."""
    best = max(values, key=values.get)
    worst = min(values, key=values.get)
    return {"gw": gw, "vs_league_avg": round(sum(values.values()), 1),
            "biggest_upside": (swing(best, values[best], mine, others, points, by_id)
                               if values[best] > 0 else None),
            "biggest_downside": (swing(worst, values[worst], mine, others, points, by_id)
                                 if values[worst] < 0 else None)}


def position_summary(impact, recent, by_id):
    """Net by position, because players in one position replace each other."""
    out = []
    for position in list(snap.POS.values()):
        pids = [p for p in impact if position_of(p, by_id) == position]
        if not pids:
            continue
        top = max(pids, key=impact.get)
        low = min(pids, key=impact.get)
        out.append({"position": position,
                    "net": round(sum(impact[p] for p in pids), 1),
                    "last_5_net": round(sum(recent.get(p, 0.0) for p in pids), 1),
                    "biggest_gain": ({"player": name_of(top, by_id), "points": round(impact[top], 1)}
                                     if impact[top] > 0 else None),
                    "biggest_loss": ({"player": name_of(low, by_id), "points": round(impact[low], 1)}
                                     if impact[low] < 0 else None)})
    return out


def analyse_league(src, team_id, league, gws, live, by_id, boot, next_gw, top, gaps):
    standing = src.get(f"leagues-classic/{league['id']}/standings/")["standings"]
    if standing.get("has_next"):
        gaps.append(f"{league['name']}: only the top 50 managers were compared.")
    members = [r for r in standing["results"]]
    rivals = [r for r in members if r["entry"] != team_id]
    impact, split, recent, gameweeks = {}, {}, {}, []
    captaincy = 0.0
    recent_gws = set(gws[-RECENT_GAMEWEEKS:])
    for gw in gws:
        mine = picks_for(src, team_id, gw)
        if mine is None:
            continue
        others = [p for p in (picks_for(src, r["entry"], gw) for r in rivals) if p is not None]
        if not others:
            continue
        points = live[gw]
        values = {}
        for pid in set(mine).union(*others):
            scored = points.get(pid, 0)
            ownership = (min(mine.get(pid, 0), 1)
                         - sum(min(p.get(pid, 0), 1) for p in others) / len(others)) * scored
            armband = (max(mine.get(pid, 0) - 1, 0)
                       - sum(max(p.get(pid, 0) - 1, 0) for p in others) / len(others)) * scored
            value = ownership + armband
            values[pid] = value
            impact[pid] = impact.get(pid, 0.0) + value
            own_total, cap_total = split.get(pid, (0.0, 0.0))
            split[pid] = (own_total + ownership, cap_total + armband)
            captaincy += armband
            if gw in recent_gws:
                recent[pid] = recent.get(pid, 0.0) + value
        gameweeks.append(gameweek_row(gw, values, mine, others, points, by_id))

    history = {r["entry"]: member_history(src, r["entry"], gaps) for r in members}
    my_rank = next((r["rank"] for r in members if r["entry"] == team_id), None)

    # The squads to expect next, ignoring any Free Hit team that has reverted.
    locked = {}
    for r in members:
        h = history[r["entry"]]
        if h is None:
            continue
        found = snap.locked_squad(src, r["entry"], next_gw - 1, snap.free_hit_weeks(h))
        if found:
            locked[r["entry"]] = found[1]["picks"]
    mine_locked = {p["element"] for p in locked.get(team_id, [])}
    rival_squads = [v for k, v in locked.items() if k != team_id]
    owners, captains = {}, {}
    for squad in rival_squads:
        for p in squad:
            owners[p["element"]] = owners.get(p["element"], 0) + 1
            if p["is_captain"]:
                captains[p["element"]] = captains.get(p["element"], 0) + 1
    size = len(rival_squads)
    name = lambda pid: name_of(pid, by_id)
    rival_only = sorted(((n, p) for p, n in owners.items()
                         if p not in mine_locked and size and n / size >= RIVAL_ONLY_SHARE),
                        reverse=True)
    differentials = [name(p) for p in mine_locked
                     if size and owners.get(p, 0) / size <= DIFFERENTIAL_SHARE]
    above = []
    for r in members:
        if my_rank is not None and r["rank"] < my_rank and history[r["entry"]] is not None:
            left = [c["chip"] for c in snap.chips_status(boot, history[r["entry"]], next_gw)
                    if c["available"]]
            above.append({"team": r["entry_name"], "rank": r["rank"], "total": r["total"],
                          "chips_left": left})
    my_hits = sum(c.get("event_transfers_cost", 0)
                  for c in (history.get(team_id) or {}).get("current", []))
    rival_hits = [sum(c.get("event_transfers_cost", 0) for c in history[r["entry"]]["current"])
                  for r in rivals if history[r["entry"]] is not None]
    return {
        "league": league["name"],
        "id": league["id"],
        "managers": league.get("rank_count"),
        "rank": league.get("entry_rank"),
        "last_rank": league.get("entry_last_rank"),
        "gameweeks_compared": len(gameweeks),
        "points_vs_league_avg": round(sum(impact.values()), 1),
        "last_5_vs_league_avg": round(sum(recent.values()), 1),
        "captaincy_vs_league_avg": round(captaincy, 1),
        "hits_taken": my_hits,
        "avg_rival_hits": round(sum(rival_hits) / len(rival_hits), 1) if rival_hits else None,
        "by_gameweek": gameweeks,
        "by_position": position_summary(impact, recent, by_id),
        "best_picks": ranked(impact, split, by_id, top, True),
        "worst_picks": ranked(impact, split, by_id, top, False),
        "next_deadline": {
            "rivals_counted": size,
            "rivals_own_you_dont": [{"player": name(p), "rivals": n} for n, p in rival_only[:top]],
            "your_differentials": sorted(differentials),
            "rival_captains_last_gw": [{"player": name(p), "rivals": n} for p, n in
                                       sorted(captains.items(), key=lambda kv: -kv[1])[:3]],
            "managers_above_you": above,
        },
    }


def build(args, src):
    boot = src.get("bootstrap-static/")
    by_id = {e["id"]: e for e in boot["elements"]}
    try:
        entry = src.get(f"entry/{args.team_id}/")
    except snap.NotFound:
        raise SystemExit(f"FPL has no team with ID {args.team_id}.") from None
    classic = entry.get("leagues", {}).get("classic", [])
    if args.league:
        leagues = [l for l in classic if l["id"] in args.league]
    else:
        leagues = [l for l in classic
                   if l.get("league_type") == "x" and (l.get("rank_count") or 0) <= args.max_size]
    gws = [ev["id"] for ev in boot["events"] if ev.get("finished")]
    if args.from_gw:
        gws = [g for g in gws if g >= args.from_gw]
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    upcoming = [ev["id"] for ev in boot["events"]
                if datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) > now]
    if not upcoming:
        return {"season_over": True}
    if not gws or not leagues:
        return {"leagues": [], "note": "No finished gameweeks or no matching leagues."}
    live = {gw: {e["id"]: e["stats"]["total_points"]
                 for e in src.get(f"event/{gw}/live/")["elements"]} for gw in gws}
    gaps = []
    results = [analyse_league(src, args.team_id, l, gws, live, by_id, boot, upcoming[0],
                              args.top, gaps) for l in leagues]
    results.sort(key=lambda r: r["points_vs_league_avg"], reverse=True)
    return {"finished_gameweeks": [gws[0], gws[-1]],
            "best_league": results[0]["league"],
            "worst_league": results[-1]["league"],
            "note": ("Impacts are before hits and add up to points_vs_league_avg. Don't read a "
                     "single player's season total alone: use by_position for the net effect."),
            "leagues": results,
            "data_gaps": sorted(set(gaps)) or None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--league", type=int, action="append",
                    help="A classic league ID to compare. Repeat for more. Default: small private leagues.")
    ap.add_argument("--max-size", type=int, default=30, help="Largest private league to include.")
    ap.add_argument("--from-gw", type=int, help="First gameweek to compare.")
    ap.add_argument("--top", type=int, default=5, help="Players to list in each ranking.")
    ap.add_argument("--data-dir")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    try:
        out = build(args, snap.Source(args.data_dir))
    except snap.FetchError as e:
        raise SystemExit(str(e)) from None
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
