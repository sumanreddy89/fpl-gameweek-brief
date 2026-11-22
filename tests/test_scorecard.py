"""Offline tests for fpl_scorecard.py. Run: python3 -m unittest discover -s tests

Synthetic players and clubs only."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fpl_scorecard as sc  # noqa: E402
from fpl_snapshot import Source  # noqa: E402

NOW = datetime(2026, 3, 20, tzinfo=timezone.utc)
TEAM = 9


def el(pid, name, owned="5.0"):
    return {"id": pid, "web_name": name, "first_name": "T", "second_name": name, "selected_by_percent": owned}


class Data:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.files = {
            "bootstrap-static": {
                "elements": [el(1, "Captain"), el(2, "Star"), el(3, "Sold"), el(4, "Bought"),
                             el(5, "Twin", "40.0"), el(6, "Twin", "1.0")],
                "events": [{"id": 1, "deadline_time": "2026-03-01T11:00:00Z", "finished": True},
                           {"id": 2, "deadline_time": "2026-03-08T11:00:00Z", "finished": True},
                           {"id": 3, "deadline_time": "2026-03-15T11:00:00Z", "finished": False},
                           {"id": 4, "deadline_time": "2026-03-29T11:00:00Z", "finished": False}]},
            f"entry_{TEAM}_transfers": [{"event": 2, "element_in": 4, "element_out": 3}],
        }
        pts = {1: [2, 3, 1], 2: [10, 2, 8], 3: [1, 9, 0], 4: [6, 1, 2], 5: [4, 4, 4], 6: [0, 0, 0]}
        for pid, ps in pts.items():
            self.files[f"element-summary_{pid}"] = {"history": [{"round": r, "total_points": p} for r, p in enumerate(ps, 1)]}
        for gw in (1, 2, 3):
            self.files[f"entry_{TEAM}_event_{gw}_picks"] = {"picks": [
                {"element": 1, "position": 1, "is_captain": True}, {"element": 2, "position": 2, "is_captain": False},
                {"element": 3, "position": 12, "is_captain": False}]}

    def source(self):
        for name, data in self.files.items():
            with open(os.path.join(self.dir, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f)
        return Source(self.dir)

    def close(self):
        shutil.rmtree(self.dir, True)


class Parse(unittest.TestCase):
    def test_reads_the_run_log_line(self):
        c = sc.parse_call("GW11 · Captain: Haaland · Transfer: Calvert-Lewin out, N.Jackson in (2nd: Gvardiol out, Van Hecke in) · hub rows delayed")
        self.assertEqual(c["gw"], 11)
        self.assertEqual(c["captain"], "Haaland")
        self.assertEqual(c["transfers"], [("Calvert-Lewin", "N.Jackson"), ("Gvardiol", "Van Hecke")])

    def test_roll_has_no_transfers(self):
        c = sc.parse_call("GW12 · Captain: Salah · Transfer: roll")
        self.assertEqual((c["captain"], c["transfers"]), ("Salah", []))

    def test_line_without_a_gameweek_is_ignored(self):
        self.assertIsNone(sc.parse_call("Captain: Salah"))


class Score(unittest.TestCase):
    def setUp(self):
        self.data = Data()

    def tearDown(self):
        self.data.close()

    def run_calls(self, *lines):
        return sc.score(self.data.source(), TEAM, [sc.parse_call(x) for x in lines], NOW)

    def test_captain_against_the_best_starter(self):
        cap = self.run_calls("GW1 · Captain: Captain · Transfer: roll")["calls"][0]["captain"]
        self.assertEqual((cap["recommended_points"], cap["best_in_xi"], cap["best_in_xi_points"]), (2, "Star", 10))
        self.assertEqual(cap["missed_vs_best"], 8)
        self.assertTrue(cap["followed"])

    def test_transfer_counts_three_weeks_and_whether_it_was_made(self):
        m = self.run_calls("GW2 · Captain: Captain · Transfer: Sold out, Bought in")["calls"][0]["transfers"][0]
        self.assertEqual(m["gameweeks"], "GW2-3")
        self.assertEqual((m["out_points"], m["in_points"], m["net"]), (9, 3, -6))
        self.assertTrue(m["made"])

    def test_unplayed_gameweek_is_not_scored_and_live_one_is_marked(self):
        out = self.run_calls("GW3 · Captain: Star · Transfer: roll", "GW4 · Captain: Star · Transfer: roll")
        g3, g4 = out["calls"]
        self.assertTrue(g3["in_progress"])
        self.assertEqual(g3["captain"]["recommended_points"], 8)
        self.assertFalse(g4["played"])
        self.assertEqual(out["summary"]["in_progress"], [3])

    def test_shared_name_takes_the_most_owned_player_and_says_so(self):
        m = self.run_calls("GW1 · Captain: Captain · Transfer: Sold out, Twin in")["calls"][0]["transfers"][0]
        self.assertEqual(m["in_points"], 12)  # Twin id 5, 40% owned
        self.assertIn("most-owned", m["note"])

    def test_summary_adds_up(self):
        s = self.run_calls("GW1 · Captain: Captain · Transfer: Sold out, Bought in",
                           "GW2 · Captain: Star · Transfer: roll")["summary"]
        self.assertEqual(s["captain_points"], 2 + 2)
        self.assertEqual(s["captain_best_possible"], 10 + 3)
        self.assertEqual(s["captain_hits"], 0)
        self.assertEqual((s["transfers_scored"], s["transfers_that_won"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
