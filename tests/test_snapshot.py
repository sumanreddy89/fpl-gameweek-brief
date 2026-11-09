"""Offline tests for fpl_snapshot.py. Run: python3 -m unittest discover -s tests

All data here is synthetic: invented players on invented clubs.
"""

import atexit
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fpl_snapshot as fpl  # noqa: E402

NOW = "2026-03-01T00:00:00Z"
TEAM = 77
SQUAD_IDS = list(range(1, 16))
SHAPE = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3


def player(pid, kind, team, cost=50, **extra):
    row = {
        "id": pid, "web_name": f"Player{pid}", "first_name": "Test", "second_name": f"P{pid}",
        "team": team, "element_type": kind, "now_cost": cost, "cost_change_start": 0,
        "cost_change_event": 0, "status": "a", "chance_of_playing_next_round": None,
        "news": "", "news_added": None, "form": "3.0", "points_per_game": "3.0",
        "ep_next": "3.0", "total_points": 30, "minutes": 900, "starts": 10,
        "selected_by_percent": "5.0", "transfers_in_event": 0, "transfers_out_event": 0,
        "expected_goal_involvements_per_90": "0.2", "defensive_contribution_per_90": "1.0",
        "penalties_order": None, "corners_and_indirect_freekicks_order": None,
        "direct_freekicks_order": None,
    }
    row.update(extra)
    return row


def picks(ids, bank=5, value=1000):
    return {
        "entry_history": {"bank": bank, "value": value},
        "picks": [{"element": pid, "position": n, "is_captain": n == 1, "is_vice_captain": n == 2}
                  for n, pid in enumerate(ids, 1)],
    }


class Scenario:
    """Writes a saved-API directory and runs the script against it."""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, self.dir, True)
        # Teams 1-5 hold the squad, 3 players each.
        self.elements = [player(pid, SHAPE[pid - 1], (pid - 1) % 5 + 1) for pid in SQUAD_IDS]
        self.fixtures = []
        for gw in range(10, 14):  # 10 is the next gameweek
            self.fixtures += [
                {"event": gw, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3},
                {"event": gw, "team_h": 3, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3},
                {"event": gw, "team_h": 5, "team_a": 6, "team_h_difficulty": 3, "team_a_difficulty": 3},
            ]
        self.history = {"current": [{"event": g, "event_transfers": 1} for g in range(1, 10)],
                        "chips": []}
        self.entry = {"name": "Test XI", "started_event": 1, "summary_overall_points": 500,
                      "summary_overall_rank": 1000, "last_deadline_bank": 5,
                      "last_deadline_value": 1000}
        self.transfers = []
        self.picks = {9: picks(SQUAD_IDS)}
        self.summaries = {}

    def write(self):
        boot = {
            "teams": [{"id": t, "short_name": f"T{t}"} for t in range(1, 7)],
            "elements": self.elements,
            "events": [{"id": g, "deadline_time": f"2026-{2 if g < 10 else 3:02d}-{g:02d}T11:00:00Z"}
                       for g in range(1, 14)],
            "chips": [{"name": "wildcard", "start_event": 2, "stop_event": 19}],
            "game_settings": {"squad_team_limit": 3, "max_extra_free_transfers": 4},
        }
        files = {"bootstrap-static": boot, "fixtures": self.fixtures,
                 f"entry_{TEAM}": self.entry, f"entry_{TEAM}_history": self.history,
                 f"entry_{TEAM}_transfers": self.transfers}
        for gw, data in self.picks.items():
            files[f"entry_{TEAM}_event_{gw}_picks"] = data
        for pid, data in self.summaries.items():
            files[f"element-summary_{pid}"] = data
        for name, data in files.items():
            with open(os.path.join(self.dir, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f)

    def run(self, *extra, team=TEAM):
        self.write()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fpl.main(["--team-id", str(team), "--data-dir", self.dir, "--now", NOW, *extra])
        return json.loads(out.getvalue())

    def add_candidate(self, pid, kind, team, cost=50, **extra):
        self.elements.append(player(pid, kind, team, cost, **extra))


def squad_arg(replace=None):
    replace = replace or {}
    return ",".join(str(replace.get(pid, pid)) for pid in SQUAD_IDS)


class FreeHit(unittest.TestCase):
    def test_uses_squad_from_before_the_free_hit(self):
        s = Scenario()
        s.history["chips"] = [{"name": "freehit", "event": 9}]
        s.elements += [player(100 + i, SHAPE[i], 6) for i in range(15)]
        s.picks[9] = picks([100 + i for i in range(15)], bank=0)
        s.picks[8] = picks(SQUAD_IDS, bank=12)
        out = s.run()
        self.assertEqual([r["id"] for r in out["squad"]], SQUAD_IDS)
        self.assertEqual(out["bank"], 1.2)
        self.assertIn("GW8", out["squad_source"])

    def test_free_hit_purchases_do_not_set_purchase_price(self):
        s = Scenario()
        s.history["chips"] = [{"name": "freehit", "event": 5}]
        s.elements[0]["now_cost"] = 60
        s.elements[0]["cost_change_start"] = 10
        s.transfers = [{"element_in": 1, "element_in_cost": 58, "event": 5, "time": "2026-01-01"}]
        out = s.run()
        self.assertEqual(out["squad"][0]["selling_price"], 5.5)  # bought 5.0, now 6.0


class Errors(unittest.TestCase):
    def test_unknown_team_gives_a_clear_message(self):
        with self.assertRaises(SystemExit) as caught:
            Scenario().run(team=123)
        self.assertIn("no team with ID 123", str(caught.exception))

    def test_late_joiner_is_asked_for_squad(self):
        s = Scenario()
        s.entry["started_event"] = 10
        s.picks = {}
        with self.assertRaises(SystemExit) as caught:
            s.run()
        self.assertIn("--squad", str(caught.exception))

    def test_late_joiner_with_squad_has_unlimited_transfers(self):
        s = Scenario()
        s.entry["started_event"] = 10
        s.picks = {}
        out = s.run("--squad", squad_arg(), "--bank", "2.0")
        self.assertIsNone(out["free_transfers_estimate"])
        self.assertIn("unlimited", out["squad_note"])
        self.assertEqual(out["bank"], 2.0)

    def test_missing_match_history_is_reported_not_fatal(self):
        out = Scenario().run()
        self.assertIsNone(out["squad"][0]["recent"])
        self.assertIn("No recent-match data", " ".join(out["data_gaps"]))


class Retries(unittest.TestCase):
    @staticmethod
    def http_error(code):
        return urllib.error.HTTPError("u", code, "x", {}, None)

    def test_retries_a_503_then_succeeds(self):
        response = io.BytesIO(b'{"ok": true}')
        with mock.patch("urllib.request.urlopen", side_effect=[self.http_error(503), response]), \
                mock.patch("time.sleep") as sleep:
            self.assertEqual(fpl.Source().get("x/"), {"ok": True})
        sleep.assert_called_once()

    def test_404_is_not_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(404)) as call:
            with self.assertRaises(fpl.NotFound):
                fpl.Source().get("x/")
        self.assertEqual(call.call_count, 1)

    def test_gives_up_with_a_readable_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(503)), \
                mock.patch("time.sleep"):
            with self.assertRaisesRegex(fpl.FetchError, "HTTP 503"):
                fpl.Source().get("x/")


class SquadOverride(unittest.TestCase):
    def test_transfer_reduces_free_transfers_and_updates_bank(self):
        s = Scenario()
        s.add_candidate(50, 4, 6, cost=52)  # replaces Player15 (cost 50)
        out = s.run("--squad", squad_arg({15: 50}))
        self.assertEqual(out["free_transfers_estimate"], 0)
        self.assertEqual(out["bank"], 0.3)  # 0.5 + 5.0 - 5.2
        self.assertEqual(out["transfers_since_deadline"], ["Player50"])
        self.assertIsNone(out["hit_cost_already_taken"])

    def test_extra_transfers_show_the_hit(self):
        s = Scenario()
        s.add_candidate(50, 4, 6)
        s.add_candidate(51, 4, 6)
        out = s.run("--squad", squad_arg({15: 50, 14: 51}))
        self.assertEqual(out["hit_cost_already_taken"], 4)

    def test_explicit_bank_wins(self):
        s = Scenario()
        s.add_candidate(50, 4, 6)
        out = s.run("--squad", squad_arg({15: 50}), "--bank", "9.9")
        self.assertEqual((out["bank"], out["bank_source"]), (9.9, "--bank"))

    def test_rejects_wrong_shape(self):
        s = Scenario()
        s.add_candidate(50, 1, 6)
        with self.assertRaises(SystemExit):
            s.run("--squad", squad_arg({15: 50}))


class SellingPrice(unittest.TestCase):
    def test_keeps_half_of_profit_rounded_down(self):
        self.assertEqual(fpl.selling_price(50, 53), 51)
        self.assertEqual(fpl.selling_price(50, 54), 52)

    def test_price_fall_is_taken_in_full(self):
        self.assertEqual(fpl.selling_price(50, 47), 47)

    def test_latest_purchase_counts(self):
        by_id = {1: player(1, 3, 1, cost=70)}
        log = [{"element_in": 1, "element_in_cost": 60, "event": 2, "time": "2026-01-01"},
               {"element_in": 1, "element_in_cost": 66, "event": 8, "time": "2026-02-01"}]
        self.assertEqual(fpl.purchase_prices([1], set(), by_id, log, set()), {1: 66})


class FreeTransfers(unittest.TestCase):
    def test_banks_up_to_the_cap(self):
        history = {"current": [], "chips": []}
        self.assertEqual(fpl.estimate_free_transfers(history, 1, 20), 5)

    def test_free_hit_week_uses_none(self):
        history = {"current": [{"event": 3, "event_transfers": 9}],
                   "chips": [{"name": "freehit", "event": 3}]}
        self.assertEqual(fpl.estimate_free_transfers(history, 1, 5), 4)

    def test_hits_floor_at_one(self):
        history = {"current": [{"event": 2, "event_transfers": 5}], "chips": []}
        self.assertEqual(fpl.estimate_free_transfers(history, 1, 3), 1)

    def test_cap_comes_from_game_settings(self):
        s = Scenario()
        s.history["current"] = []
        self.assertEqual(s.run()["free_transfers_estimate"], 5)


class Candidates(unittest.TestCase):
    def test_unaffordable_player_is_left_out(self):
        s = Scenario()
        s.add_candidate(50, 4, 6, cost=140, ep_next="15.0")
        s.add_candidate(51, 4, 6, cost=50)
        ids = [c["id"] for c in s.run()["candidates"]["FWD"]]
        self.assertEqual(ids, [51])

    def test_all_prices_keeps_them(self):
        s = Scenario()
        s.add_candidate(50, 4, 6, cost=140, ep_next="15.0")
        ids = [c["id"] for c in s.run("--all-prices")["candidates"]["FWD"]]
        self.assertEqual(ids, [50])

    def test_full_club_is_only_replaceable_from_within(self):
        s = Scenario()
        s.add_candidate(50, 3, 1)  # club 1 already has three players
        row = s.run()["candidates"]["MID"][0]
        self.assertEqual(row["can_replace"], ["Player11"])  # the club-1 midfielder

    def test_ranking_rewards_later_fixtures(self):
        s = Scenario()
        s.add_candidate(50, 4, 6)
        s.add_candidate(51, 4, 7)
        s.fixtures = [f for f in s.fixtures if f["team_a"] != 6 or f["event"] == 10]
        for gw in range(11, 14):
            s.fixtures.append({"event": gw, "team_h": 7, "team_a": 8,
                               "team_h_difficulty": 2, "team_a_difficulty": 4})
        fixtures = s.fixtures
        rows = [fpl.projected_points(e, list(range(10, 14)), fixtures, 9) for e in s.elements[-2:]]
        self.assertGreater(rows[1], rows[0])

    def test_blank_scores_less_than_a_game(self):
        e = player(1, 3, 1)
        played = [{"event": 11, "team_h": 1, "team_a": 2,
                   "team_h_difficulty": 3, "team_a_difficulty": 3}]
        self.assertGreater(fpl.projected_points(e, [10, 11], played, 9),
                           fpl.projected_points(e, [10, 11], [], 9))


class RecentMatches(unittest.TestCase):
    @staticmethod
    def summary(minutes):
        return {"history": [{"round": n, "minutes": m, "total_points": 2}
                            for n, m in enumerate(minutes, 1)]}

    def test_falling_minutes_are_flagged(self):
        self.assertEqual(fpl.recent_matches(self.summary([90, 90, 90, 30, 20]))["minutes_trend"],
                         "falling")

    def test_steady_starter(self):
        self.assertEqual(fpl.recent_matches(self.summary([90, 90, 85, 90, 80]))["minutes_trend"],
                         "steady")

    def test_only_last_five_are_kept(self):
        self.assertEqual(len(fpl.recent_matches(self.summary([90] * 9))["matches"]), 5)

    def test_short_history_makes_no_claim(self):
        self.assertEqual(fpl.recent_matches(self.summary([90, 10]))["minutes_trend"],
                         "not enough matches")


class Rows(unittest.TestCase):
    def test_set_pieces_are_passed_through(self):
        s = Scenario()
        s.elements[0]["penalties_order"] = 1
        self.assertEqual(s.run()["squad"][0]["set_pieces"], {"penalties": 1})

    def test_new_fields_may_be_absent(self):
        s = Scenario()
        del s.elements[0]["expected_goal_involvements_per_90"]
        self.assertIsNone(s.run()["squad"][0]["xgi_per_90"])


if __name__ == "__main__":
    unittest.main()
