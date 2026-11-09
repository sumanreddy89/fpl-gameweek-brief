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
HORIZON = 4
GOOD_RUN = 2.5
TOUGH_RUN = 3.5
MIN_RIVAL_SHARE = 0.2


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
    impact, split, recent, bench, gameweeks = {}, {}, {}, {}, []
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
                if pid in mine and mine[pid] == 0 and value < 0:
                    bench[pid] = bench.get(pid, 0.0) + value
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
    rival_lineups = [v for k, v in locked.items() if k != team_id]
    rival_starts, rival_captains = {}, {}
    for squad in rival_lineups:
        for p in squad:
            if p["multiplier"] > 0:
                rival_starts[p["element"]] = rival_starts.get(p["element"], 0.0) + 1 / len(rival_lineups)
            if p["is_captain"]:
                rival_captains[p["element"]] = rival_captains.get(p["element"], 0.0) + 1 / len(rival_lineups)
    my_lineup = {p["element"]: p["multiplier"] for p in locked.get(team_id, [])}
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
    positions = position_summary(impact, recent, by_id)
    return {
        "_recent": recent,
        "_bench": bench,
        "_rival_starts": rival_starts,
        "_rival_captains": rival_captains,
        "_my_lineup": my_lineup,
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
        "by_position": positions,
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


def average_cost(tables, count):
    totals = {}
    for table in tables:
        for pid, value in table.items():
            totals[pid] = totals.get(pid, 0.0) + value
    return {pid: value / count for pid, value in totals.items()}


def replaceable(row, squad, bank, club_limit):
    """Names of squad players one transfer could swap for this player."""
    counts = {}
    for s in squad:
        counts[s["club"]] = counts.get(s["club"], 0) + 1
    names = []
    for s in squad:
        if (s["pos"] == row["pos"] and s["selling_price"] is not None and bank is not None
                and row["price"] <= round(bank + s["selling_price"], 1)
                and (s["club"] == row["club"] or counts.get(row["club"], 0) < club_limit)):
            names.append(s["name"])
    return names


def fixture_run(team_id, gws, fixtures):
    """Difficulty of each coming game, and a plain label for the run."""
    difficulties = [fdr for gw in gws for _, _, fdr in snap.team_fixtures(team_id, gw, fixtures)]
    if not difficulties:
        return [], "no fixtures"
    average = sum(difficulties) / len(difficulties)
    label = "good run" if average <= GOOD_RUN else "tough run" if average >= TOUGH_RUN else "mixed run"
    return difficulties, label


def decisions(results, snapshot, boot, by_id, fixtures, top):
    """Lay out the gaps as facts: who rivals start, and the fixtures ahead.

    Rival lineups are as of the last deadline. For this gameweek, ordering uses
    FPL's own ep_next. For transfers, it uses how many rivals start the player.
    """
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    last_gw = snapshot["next_gameweek"] - 1
    final = max(ev["id"] for ev in boot["events"])
    gws = [g for g in range(last_gw + 1, last_gw + HORIZON + 1) if g <= final]
    count = len(results)
    starts = average_cost([r["_rival_starts"] for r in results], count)
    captains = average_cost([r["_rival_captains"] for r in results], count)
    bench = average_cost([r["_bench"] for r in results], count)
    recent = average_cost([r["_recent"] for r in results], count)
    my_lineup = results[0]["_my_lineup"]
    squad = snapshot["squad"]
    owned = {row["id"] for row in squad}
    limit = boot.get("game_settings", {}).get("squad_team_limit", snap.DEFAULT_CLUB_LIMIT)
    ep = lambda pid: snap.number(by_id[pid], "ep_next") or 0.0
    pct = lambda share: round(share * 100)

    def fact(pid):
        e = by_id[pid]
        row = snap.player_row(e, teams, fixtures, gws, last_gw)
        return {"player": row["name"], "position": row["pos"], "club": row["club"],
                "rivals_starting_pct": pct(starts.get(pid, 0.0)),
                "next_fixture": row["fixtures"][0] if row["fixtures"] else None,
                "form": row["form"], "status": row["status"]}

    known = [pid for pid in starts if pid in by_id]
    lacking = [pid for pid in known if pid not in owned and by_id[pid]["status"] == "a"
               and starts[pid] >= MIN_RIVAL_SHARE]
    benched = [pid for pid in known if pid in owned and my_lineup.get(pid, 0) == 0
               and starts[pid] >= MIN_RIVAL_SHARE]
    only_you = [pid for pid in owned if pid in by_id and my_lineup.get(pid, 0) > 0
                and starts.get(pid, 0.0) <= DIFFERENTIAL_SHARE]

    transfers = []
    for pid in lacking:
        row = snap.player_row(by_id[pid], teams, fixtures, gws, last_gw)
        run, label = fixture_run(by_id[pid]["team"], gws, fixtures)
        options = replaceable(row, squad, snapshot["bank"], limit)
        transfers.append((-starts[pid], sum(run) / len(run) if run else 9, {
            **fact(pid), "price": row["price"], "xgi_per_90": row["xgi_per_90"],
            "fixture_difficulty": run, "run": label,
            "affordable_with_one_transfer": bool(options), "can_replace": options}))
    transfers.sort(key=lambda t: t[:2])

    by_position = []
    for position in snap.POS.values():
        names = sorted((p for p in lacking if position_of(p, by_id) == position),
                       key=lambda p: -starts[p])
        by_position.append({"position": position,
                            "your_starters": sum(1 for p, m in my_lineup.items()
                                                 if m > 0 and position_of(p, by_id) == position),
                            "players_rivals_start_you_lack": [
                                {"player": by_id[p]["web_name"], "rivals_starting_pct": pct(starts[p])}
                                for p in names[:3]]})
    return {
        "basis": ("Facts from each manager's last public lineup, averaged across your compared "
                  "leagues. Rivals can change their teams before the deadline."),
        "this_gameweek": {
            "rivals_start_you_dont": [fact(p) for p in sorted(lacking, key=lambda p: -starts[p] * ep(p))[:top]],
            "you_bench_rivals_start": [fact(p) for p in sorted(benched, key=lambda p: -starts[p] * ep(p))],
            "you_start_rivals_dont": [fact(p) for p in sorted(only_you, key=ep, reverse=True)[:top]],
            "rival_captains": [{"player": by_id[p]["web_name"], "rivals_captaining_pct": pct(v)}
                               for p, v in sorted(captains.items(), key=lambda kv: -kv[1])[:3]
                               if p in by_id],
        },
        "transfer_gaps": [t[2] for t in transfers[:top]],
        "by_position": by_position,
        "context_last_5": {
            "costly_benchings": [
                {"player": name_of(pid, by_id), "avg_points_lost_per_league": round(value, 1)}
                for pid, value in sorted(bench.items(), key=lambda kv: kv[1])[:3]],
            "players_costing_most": [
                {"player": name_of(pid, by_id), "avg_points_lost_per_league": round(value, 1)}
                for pid, value in sorted(recent.items(), key=lambda kv: kv[1])[:3]],
        },
    }


def after_deadline(args, src):
    """Once lineups lock: how much each player's points move you against each league."""
    boot = src.get("bootstrap-static/")
    by_id = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    started = [ev["id"] for ev in boot["events"]
               if datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) <= now]
    if not started:
        return {"leagues": [], "note": "No deadline has passed yet."}
    gw = started[-1]
    try:
        entry = src.get(f"entry/{args.team_id}/")
    except snap.NotFound:
        raise SystemExit(f"FPL has no team with ID {args.team_id}.") from None
    fixtures = src.get("fixtures/")
    live = {e["id"]: e["stats"]["total_points"] for e in src.get(f"event/{gw}/live/")["elements"]}
    mine = picks_for(src, args.team_id, gw)
    if mine is None:
        return {"gameweek": gw, "leagues": [], "note": "Your lineup isn't public yet."}

    def row(pid, swing, rivals):
        e = by_id.get(pid, {})
        games = snap.team_fixtures(e.get("team"), gw, fixtures)
        started_pct = round(sum(1 for r in rivals if r.get(pid, 0) > 0) / len(rivals) * 100)
        return {"player": name_of(pid, by_id), "you": mine.get(pid, 0),
                "rivals_starting_pct": started_pct,
                "rivals_captaining_pct": round(sum(1 for r in rivals if r.get(pid, 0) >= 2)
                                               / len(rivals) * 100),
                "swing_per_point": round(swing, 2), "points_so_far": live.get(pid, 0),
                "fixture": [f'{teams[o]} ({"H" if h else "A"})' for o, h, _ in games]}

    out = []
    for league in select_leagues(args, entry):
        standing = src.get(f"leagues-classic/{league['id']}/standings/")["standings"]
        chips = {}
        rivals = []
        for result in standing["results"]:
            if result["entry"] == args.team_id:
                continue
            try:
                data = src.get(f"entry/{result['entry']}/event/{gw}/picks/")
            except snap.FetchError:
                continue
            rivals.append({p["element"]: p["multiplier"] for p in data["picks"]})
            if data.get("active_chip"):
                chip = snap.CHIP_NAMES.get(data["active_chip"], data["active_chip"])
                chips[chip] = chips.get(chip, 0) + 1
        if not rivals:
            continue
        swings = {pid: mine.get(pid, 0) - sum(r.get(pid, 0) for r in rivals) / len(rivals)
                  for pid in set(mine).union(*rivals)}
        ordered = sorted(swings, key=swings.get)
        out.append({"league": league["name"], "rank": league.get("entry_rank"),
                    "managers": league.get("rank_count"),
                    "want_to_score": [row(p, swings[p], rivals) for p in reversed(ordered[-args.top:])
                                      if swings[p] > 0],
                    "want_to_blank": [row(p, swings[p], rivals) for p in ordered[:args.top]
                                      if swings[p] < 0],
                    "rival_chips_this_gw": chips})
    return {"gameweek": gw,
            "note": ("swing_per_point is exact: each point the player scores moves you by this "
                     "much against the league's average."),
            "leagues": out}


def select_leagues(args, entry):
    classic = entry.get("leagues", {}).get("classic", [])
    if args.league:
        return [l for l in classic if l["id"] in args.league]
    return [l for l in classic
            if l.get("league_type") == "x" and (l.get("rank_count") or 0) <= args.max_size]


def build(args, src):
    boot = src.get("bootstrap-static/")
    by_id = {e["id"]: e for e in boot["elements"]}
    try:
        entry = src.get(f"entry/{args.team_id}/")
    except snap.NotFound:
        raise SystemExit(f"FPL has no team with ID {args.team_id}.") from None
    leagues = select_leagues(args, entry)
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
    forward = ["--team-id", str(args.team_id)]
    if args.now:
        forward += ["--now", args.now]
    snapshot = snap.build_snapshot(snap.parse_args(forward), src)
    actions = decisions(results, snapshot, boot, by_id, src.get("fixtures/"), args.top)
    for result in results:
        result.pop("_recent")
        result.pop("_bench")
        result.pop("_rival_starts")
        result.pop("_rival_captains")
        result.pop("_my_lineup")
    return {"finished_gameweeks": [gws[0], gws[-1]],
            "best_league": results[0]["league"],
            "worst_league": results[-1]["league"],
            "note": ("Impacts are before hits and add up to points_vs_league_avg. Don't read a "
                     "single player's season total alone: use by_position for the net effect."),
            "decisions": actions,
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
    ap.add_argument("--after-deadline", action="store_true",
                    help="Show what to watch this gameweek, now that lineups are locked.")
    ap.add_argument("--data-dir")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    try:
        source = snap.Source(args.data_dir)
        out = after_deadline(args, source) if args.after_deadline else build(args, source)
    except snap.FetchError as e:
        raise SystemExit(str(e)) from None
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
