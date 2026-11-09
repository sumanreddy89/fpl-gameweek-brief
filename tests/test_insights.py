"""Offline tests for fpl_leagues.py and fpl_daily.py, on invented data."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fpl_daily  # noqa: E402
import fpl_leagues  # noqa: E402
from test_snapshot import NOW, TEAM, Scenario, player  # noqa: E402


def run(module, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        module.main(list(argv))
    return json.loads(out.getvalue())


class LeagueData(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def save(self, name, data):
        with open(os.path.join(self.dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    @staticmethod
    def picks(multipliers):
        return {"picks": [{"element": p, "multiplier": m, "position": i,
                           "is_captain": m == 2, "is_vice_captain": False}
                          for i, (p, m) in enumerate(multipliers.items(), 1)]}

    def build(self, chips=None, mine=None):
        kinds = {1: 1, 2: 4, 3: 1}
        names = {i: player(i, kinds[i], i, web_name=f"P{i}") for i in kinds}
        self.save("bootstrap-static", {
            "elements": list(names.values()),
            "teams": [{"id": t, "short_name": f"T{t}"} for t in (1, 2, 3)],
            "events": [{"id": 1, "finished": True, "deadline_time": "2026-01-01T11:00:00Z"},
                       {"id": 2, "finished": False, "deadline_time": "2026-04-01T11:00:00Z"}],
            "chips": [{"name": "bboost", "start_event": 1, "stop_event": 19}]})
        self.save(f"entry_{TEAM}", {"leagues": {"classic": [
            {"id": 9, "name": "Friends", "league_type": "x", "rank_count": 3,
             "entry_rank": 2, "entry_last_rank": 3},
            {"id": 8, "name": "Huge", "league_type": "x", "rank_count": 5000}]}})
        self.save("leagues-classic_9_standings", {"standings": {"has_next": False, "results": [
            {"entry": 200, "rank": 1, "entry_name": "Top", "total": 20},
            {"entry": TEAM, "rank": 2, "entry_name": "Me", "total": 16},
            {"entry": 300, "rank": 3, "entry_name": "Low", "total": 2}]}})
        self.save("event_1_live", {"elements": [
            {"id": 1, "stats": {"total_points": 10}},
            {"id": 2, "stats": {"total_points": 2}},
            {"id": 3, "stats": {"total_points": 4}}]})
        self.save("fixtures", [])
        self.save(f"entry_{TEAM}_transfers", [])
        for entry, squad in ((TEAM, mine or {1: 2}), (200, {1: 2, 3: 1}), (300, {2: 1})):
            self.save(f"entry_{entry}_event_1_picks", self.picks(squad))
            self.save(f"entry_{entry}_history", {
                "current": [{"event": 1, "event_transfers": 0,
                             "event_transfers_cost": 4 if entry == TEAM else 0}],
                "chips": chips.get(entry, []) if chips else []})

    def result(self):
        return run(fpl_leagues, "--team-id", str(TEAM), "--data-dir", self.dir, "--now", NOW)

    def test_impacts_add_up_to_the_gap(self):
        self.build()
        league = self.result()["leagues"][0]
        # Me 20. Rivals 24 and 2, average 13.
        self.assertEqual(league["points_vs_league_avg"], 7.0)
        self.assertEqual(league["best_picks"], [{"player": "P1", "points": 10.0,
                                                 "from_ownership": 5.0, "from_captaincy": 5.0}])

    def test_each_gameweek_names_its_biggest_swings(self):
        self.build()
        row = self.result()["leagues"][0]["by_gameweek"][0]
        self.assertEqual((row["gw"], row["vs_league_avg"]), (1, 7.0))
        self.assertEqual(row["biggest_upside"], {
            "player": "P1", "position": "GK", "points": 10.0, "your_multiplier": 2,
            "league_avg_multiplier": 1.0, "player_points": 10})
        self.assertEqual(row["biggest_downside"]["player"], "P3")
        self.assertEqual(row["biggest_downside"]["points"], -2.0)

    def test_positions_net_out_players_who_replace_each_other(self):
        self.build()
        positions = {p["position"]: p for p in self.result()["leagues"][0]["by_position"]}
        self.assertEqual(positions["GK"]["net"], 8.0)
        self.assertEqual(positions["GK"]["biggest_gain"], {"player": "P1", "points": 10.0})
        self.assertEqual(positions["GK"]["biggest_loss"], {"player": "P3", "points": -2.0})
        self.assertEqual(positions["FWD"]["net"], -1.0)

    def test_captaincy_is_split_out(self):
        self.build()
        self.assertEqual(self.result()["leagues"][0]["captaincy_vs_league_avg"], 5.0)

    def test_decisions_chase_the_weakest_position(self):
        self.build()
        actions = self.result()["decisions"]
        self.assertEqual(actions["focus_position"], "FWD")
        self.assertEqual([c["player"] for c in actions["chase"]], ["P2"])
        self.assertEqual(actions["chase"][0]["expected_gap_next_gws"], -1.5)
        self.assertEqual(actions["chase"][0]["rivals_starting_pct"], 50)
        self.assertEqual(actions["chase"][0]["avg_points_lost_per_league_last_5"], -1.0)
        self.assertFalse(actions["chase"][0]["affordable_with_one_transfer"])

    def test_benching_a_player_rivals_started_is_flagged(self):
        self.build(mine={1: 2, 3: 0})
        costly = self.result()["decisions"]["costly_benchings"]
        self.assertEqual(costly, [{"player": "P3", "avg_points_lost_per_league_last_5": -2.0}])

    def test_big_private_leagues_are_skipped(self):
        self.build()
        self.assertEqual([l["id"] for l in self.result()["leagues"]], [9])

    def test_rivals_above_show_chips_left(self):
        self.build(chips={200: [{"name": "bboost", "event": 1}]})
        above = self.result()["leagues"][0]["next_deadline"]["managers_above_you"]
        self.assertEqual(above, [{"team": "Top", "rank": 1, "total": 20, "chips_left": []}])

    def test_hits_are_separate(self):
        self.build()
        league = self.result()["leagues"][0]
        self.assertEqual((league["hits_taken"], league["avg_rival_hits"]), (4, 0.0))


def outlook(pct):
    return {"price_change_percent": str(pct), "price_change_locked_until": None,
            "price_change_projections": [{"offset": 0, "projected_percent": str(pct)}]}


class Daily(unittest.TestCase):
    def check(self, scenario, now=NOW):
        scenario.write()
        return run(fpl_daily, "--team-id", str(TEAM), "--data-dir", scenario.dir, "--now", now)

    def test_brief_due_on_the_last_evening(self):
        self.assertTrue(self.check(Scenario(), "2026-03-09T19:00:00Z")["write_brief_today"])

    def test_no_brief_two_days_out(self):
        self.assertFalse(self.check(Scenario(), "2026-03-08T19:00:00Z")["write_brief_today"])

    def test_no_brief_right_before_the_deadline(self):
        self.assertFalse(self.check(Scenario(), "2026-03-10T08:00:00Z")["write_brief_today"])

    def test_falling_squad_player_alerts_when_it_costs_money(self):
        s = Scenario()
        s.elements[0].update(outlook(-101))
        alerts = self.check(s)["price_alerts"]
        self.assertEqual([(a["type"], a["player"]) for a in alerts],
                         [("squad_falling", "Player1")])

    def test_fall_that_keeps_selling_price_stays_quiet(self):
        s = Scenario()
        # Bought 5.0, now 5.3: sells 5.1, and still 5.1 after a fall to 5.2.
        s.elements[0].update(outlook(-101), now_cost=53, cost_change_start=3)
        self.assertEqual(self.check(s)["price_alerts"], [])

    def test_top_target_rising_alerts(self):
        s = Scenario()
        s.add_candidate(50, 4, 6, cost=52, **outlook(102))
        alerts = self.check(s)["price_alerts"]
        self.assertEqual([(a["type"], a["player"]) for a in alerts],
                         [("target_rising", "Player50")])

    def test_quiet_when_nothing_is_close(self):
        s = Scenario()
        s.elements[0].update(outlook(-50))
        self.assertEqual(self.check(s)["price_alerts"], [])

    def test_locked_player_stays_quiet(self):
        s = Scenario()
        s.elements[0].update(outlook(-101), price_change_locked_until="2026-03-02T00:00:00Z")
        self.assertEqual(self.check(s)["price_alerts"], [])


if __name__ == "__main__":
    unittest.main()
