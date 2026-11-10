"""Writes the saved-API data the skill evals run against. All clubs and players are invented.

    python3 tests/make_eval_fixture.py <out_dir>

The data is frozen at 2026-03-08 19:00 UTC: GW1-27 are finished and the GW28 deadline is
2026-03-10 11:00 UTC. The manager is team 4242 ("Sunday Tinkerers"), in one private league
with four rivals. The squad has one injured starter, one doubtful defender and a forward whose
minutes are falling, so a good brief has something to flag.
"""

import json
import os
import random
import sys
from datetime import datetime, timedelta

TEAM = 4242
DEADLINE = datetime(2026, 3, 10, 11, 0)  # GW28
NEXT_GW = 28
LAST_GW = NEXT_GW - 1

CLUBS = ["ASH", "BRK", "CDN", "DRV", "ELM", "FAL", "GRN", "HAR", "IRV", "KES"]

# (id, web_name, club index 1-10, position 1-4, price in tenths, extras)
PLAYERS = [
    # Manager's squad
    (1, "Okafor", 1, 1, 55, {}),
    (2, "Lindqvist", 6, 1, 40, {}),
    (3, "Mbeki", 1, 2, 60, {}),
    (4, "Varga", 2, 2, 55, {"status": "d", "chance_of_playing_next_round": 50,
                            "news": "Hamstring tightness - 50% chance of playing"}),
    (5, "Castell", 3, 2, 50, {}),
    (6, "Ruiz", 4, 2, 45, {}),
    (7, "Petrov", 7, 2, 40, {}),
    (8, "Haddad", 1, 3, 125, {"penalties_order": 1}),
    (9, "Novak", 2, 3, 85, {"status": "i", "chance_of_playing_next_round": 0,
                            "news": "Knee injury - expected back mid-April"}),
    (10, "Asante", 3, 3, 75, {"corners_and_indirect_freekicks_order": 1}),
    (11, "Moreau", 5, 3, 65, {}),
    (12, "Brennan", 8, 3, 50, {}),
    (13, "Kowalski", 4, 4, 140, {"penalties_order": 1}),
    (14, "Tanaka", 5, 4, 75, {}),
    (15, "Diallo", 9, 4, 60, {}),
    # Transfer targets and rivals' picks
    (20, "Esposito", 6, 3, 80, {"form": "7.8", "ep_next": "6.9", "selected_by_percent": "22.4",
                                "transfers_in_event": 180000,
                                "expected_goal_involvements_per_90": "0.62"}),
    (21, "Quinlan", 10, 3, 70, {"form": "6.5", "ep_next": "5.8",
                                "expected_goal_involvements_per_90": "0.48"}),
    (22, "Sorensen", 7, 3, 60, {"form": "5.9", "ep_next": "5.1",
                                "expected_goal_involvements_per_90": "0.41"}),
    (23, "Abara", 6, 2, 50, {"form": "6.2", "ep_next": "5.0",
                             "defensive_contribution_per_90": "9.4"}),
    (24, "Fontaine", 10, 2, 45, {"form": "5.0", "ep_next": "4.4"}),
    (25, "Halvorsen", 6, 4, 90, {"form": "7.1", "ep_next": "6.2", "penalties_order": 1,
                                 "expected_goal_involvements_per_90": "0.71"}),
    (26, "Ibarra", 10, 4, 65, {"form": "5.4", "ep_next": "4.9"}),
    (27, "Yilmaz", 7, 1, 45, {}),
    (28, "Grant", 9, 3, 55, {"status": "u", "news": "Left the club on loan"}),
    (29, "Weller", 8, 2, 40, {}),
    (30, "Nakamura", 3, 4, 55, {}),
]

# GW28 fixtures (home, away, home difficulty, away difficulty); GW29-31 follow in rotation.
ROUNDS = [
    [(1, 10, 2, 4), (2, 6, 4, 3), (3, 9, 2, 3), (4, 8, 2, 3), (5, 7, 3, 3)],
    [(6, 1, 4, 2), (7, 2, 3, 3), (8, 3, 3, 3), (9, 4, 3, 2), (10, 5, 3, 3)],
    [(1, 3, 3, 4), (2, 4, 3, 3), (5, 6, 4, 2), (7, 9, 2, 2), (8, 10, 3, 2)],
    [(3, 2, 3, 3), (4, 1, 4, 3), (6, 7, 2, 4), (9, 8, 3, 3), (10, 5, 2, 3)],
]

SQUAD = list(range(1, 16))
MY_LINEUP = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 2, 15, 7, 12]  # first 11 start
RIVALS = {
    501: ("Back of the Net", [1, 3, 23, 5, 6, 8, 20, 10, 25, 13, 14, 2, 30, 7, 12], 20),
    502: ("Wing and a Prayer", [27, 3, 23, 24, 6, 8, 20, 21, 25, 13, 26, 2, 15, 29, 22], 25),
    503: ("Expected Goals FC", [1, 23, 5, 24, 7, 8, 20, 22, 11, 13, 25, 27, 26, 29, 12], 8),
    504: ("Laces Out", [2, 3, 4, 6, 29, 8, 9, 21, 10, 13, 14, 27, 15, 7, 12], 13),
}


def element(pid, name, club, pos, price, extra):
    row = {
        "id": pid, "web_name": name, "first_name": "", "second_name": name,
        "team": club, "element_type": pos, "now_cost": price, "cost_change_start": 2,
        "cost_change_event": 0, "status": "a", "chance_of_playing_next_round": None,
        "news": "", "news_added": "2026-03-07T09:00:00Z" if extra.get("news") else None,
        "form": "4.0", "points_per_game": "4.1", "ep_next": "4.0", "total_points": 110,
        "minutes": 2100, "starts": 24, "selected_by_percent": "8.0",
        "transfers_in_event": 20000, "transfers_out_event": 15000,
        "expected_goal_involvements_per_90": "0.25", "defensive_contribution_per_90": "4.0",
        "penalties_order": None, "corners_and_indirect_freekicks_order": None,
        "direct_freekicks_order": None,
    }
    row.update(extra)
    if pid == 9:
        row.update(form="0.0", ep_next="0.0", transfers_out_event=210000)
    if pid == 13:
        row.update(form="8.2", ep_next="7.4", selected_by_percent="48.0")
    if pid == 8:
        row.update(form="6.9", ep_next="6.6", selected_by_percent="35.0")
    return row


def points(rng, pid, gw):
    if pid == 9 and gw >= 26:
        return 0, 0
    if pid == 14 and gw >= 25:
        return (25, 1) if gw % 2 else (12, 1)
    return 90, rng.choice([1, 2, 2, 2, 3, 5, 6, 8, 9, 13])


def picks(lineup, captain_idx=9, bank=15):
    return {
        "active_chip": None,
        "entry_history": {"event": LAST_GW, "bank": bank, "value": 1012},
        "picks": [{"element": p, "position": i, "multiplier": (2 if i - 1 == captain_idx else 1) if i <= 11 else 0,
                   "is_captain": i - 1 == captain_idx, "is_vice_captain": i - 1 == 5}
                  for i, p in enumerate(lineup, 1)],
    }


def main(out):
    rng = random.Random(28)
    os.makedirs(out, exist_ok=True)
    files = {}
    elements = [element(*p) for p in PLAYERS]
    files["bootstrap-static"] = {
        "teams": [{"id": i, "short_name": c, "name": c} for i, c in enumerate(CLUBS, 1)],
        "elements": elements,
        "events": [{"id": g, "finished": g <= LAST_GW,
                    "deadline_time": (DEADLINE + timedelta(weeks=g - NEXT_GW)).strftime("%Y-%m-%dT%H:%M:%SZ")}
                   for g in range(1, 39)],
        "chips": [{"name": n, "start_event": s, "stop_event": e}
                  for n in ("wildcard", "freehit", "bboost", "3xc")
                  for s, e in ((1, 19), (20, 38))],
        "game_settings": {"squad_team_limit": 3, "max_extra_free_transfers": 4},
    }
    fixtures = []
    for offset, rnd in enumerate(ROUNDS):
        for h, a, hd, ad in rnd:
            fixtures.append({"event": NEXT_GW + offset, "team_h": h, "team_a": a,
                             "team_h_difficulty": hd, "team_a_difficulty": ad, "finished": False,
                             "kickoff_time": f"2026-03-{14 + 7 * offset:02d}T15:00:00Z"})
    files["fixtures"] = fixtures

    history_rows = {}
    for gw in range(1, NEXT_GW):
        live = []
        for p in PLAYERS:
            mins, pts = points(rng, p[0], gw)
            live.append({"id": p[0], "stats": {"total_points": pts, "minutes": mins}})
            history_rows.setdefault(p[0], []).append(
                {"round": gw, "minutes": mins, "total_points": pts,
                 "kickoff_time": f"2026-01-01T15:00:00Z"})
        files[f"event_{gw}_live"] = {"elements": live}
    for pid, rows in history_rows.items():
        files[f"element-summary_{pid}"] = {"history": rows}

    files[f"entry_{TEAM}"] = {
        "id": TEAM, "name": "Sunday Tinkerers", "started_event": 1,
        "summary_overall_points": 1432, "summary_overall_rank": 412880,
        "last_deadline_bank": 15, "last_deadline_value": 1012,
        "leagues": {"classic": [
            {"id": 77001, "name": "Office League", "league_type": "x", "rank_count": 5,
             "entry_rank": 3, "entry_last_rank": 2},
            {"id": 314, "name": "Overall", "league_type": "s", "rank_count": 9000000}]},
    }
    current = [{"event": g, "event_transfers": 1,
                "event_transfers_cost": 0, "points": 50, "total_points": 50 * g, "rank": 400000,
                "bank": 15, "value": 1012} for g in range(1, NEXT_GW)]
    files[f"entry_{TEAM}_history"] = {"current": current,
                                      "chips": [{"name": "wildcard", "event": 9, "time": "2025-10-20"}]}
    files[f"entry_{TEAM}_transfers"] = [
        {"element_in": 14, "element_in_cost": 72, "element_out": 30, "element_out_cost": 55,
         "event": 21, "time": "2026-01-24T10:00:00Z"},
        {"element_in": 9, "element_in_cost": 82, "element_out": 21, "element_out_cost": 68,
         "event": 24, "time": "2026-02-14T10:00:00Z"},
    ]

    standings = [(501, "Back of the Net", 1501), (502, "Wing and a Prayer", 1466),
                 (TEAM, "Sunday Tinkerers", 1432), (503, "Expected Goals FC", 1410),
                 (504, "Laces Out", 1388)]
    files["leagues-classic_77001_standings"] = {"standings": {"has_next": False, "results": [
        {"entry": e, "rank": r, "entry_name": n, "player_name": f"Manager {e}", "total": t}
        for r, (e, n, t) in enumerate(standings, 1)]}}

    for gw in range(1, NEXT_GW):
        files[f"entry_{TEAM}_event_{gw}_picks"] = picks(MY_LINEUP)
    for entry, (name, lineup, cap) in RIVALS.items():
        captain_idx = lineup.index(cap) if cap in lineup[:11] else 9
        for gw in range(1, NEXT_GW):
            files[f"entry_{entry}_event_{gw}_picks"] = picks(lineup, captain_idx, bank=5)
        files[f"entry_{entry}_history"] = {
            "current": [{"event": g, "event_transfers": 1, "event_transfers_cost": 4 if g == 25 and entry == 502 else 0}
                        for g in range(1, NEXT_GW)],
            "chips": [{"name": "wildcard", "event": 8}] + ([{"name": "bboost", "event": 22}] if entry == 501 else [])}

    for name, data in files.items():
        with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fpl-data")
