"""Offline tests for render_brief.py. Run: python3 -m unittest discover -s tests

Synthetic data only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_brief as rb  # noqa: E402


def player(name, pos, club="T1", fixture="GW12: T2 (H) 2", recent=None, price=6.0):
    return {"name": name, "pos": pos, "club": club, "price": price, "fixtures": [fixture, "GW13: T3 (A) 4"],
            "recent": recent or {}}


def snap():
    striker = player("Striker", "FWD", recent={"underlying_last_4": {"xgi": 2.6, "goals_assists": 1, "verdict": "unlucky: chances are there, returns aren't"}})
    return {
        "team": {"name": "Test XI", "overall_points": 600, "overall_rank": 123456},
        "next_gameweek": 12, "bank": 1.5, "free_transfers_estimate": 1,
        "squad": [player("Keeper", "GK"), player("Back", "DEF"), player("Middle", "MID"), striker],
        "candidates": {"FWD": [player("Newboy", "FWD", club="T9", price=7.2)]},
        "last_gw_review": {"gw": 11, "captain": {"name": "Striker", "points": 2, "minutes": 90, "xgi": 1.08,
                                                  "form_verdict": "unlucky: chances are there, returns aren't"},
                           "blanks": [{"name": "Back", "points": 1, "minutes": 90, "xgi": 0.0, "form_verdict": "not judged"}]},
    }


class Render(unittest.TestCase):
    def test_agent_text_is_escaped(self):
        page = rb.render(snap(), {"headline": "<script>alert(1)</script>"})
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_unknown_player_is_marked_not_invented(self):
        page = rb.render(snap(), {"xi": ["Keeper", "Ghost"]})
        self.assertIn("Ghost", page)
        self.assertIn("not in data", page)

    def test_captain_review_uses_snapshot_numbers(self):
        page = rb.render(snap(), {})
        self.assertIn("Gameweek 11 review", page)
        self.assertIn("pts (×2 = 4)", page)
        self.assertIn("1.08", page)
        self.assertIn('class="chip luck"', page)

    def test_form_check_shows_chances_and_returns(self):
        page = rb.render(snap(), {"xi": ["Keeper", "Striker"]})
        self.assertIn("Form check", page)
        self.assertIn("2.6 / 1", page)

    def test_captain_and_vice_armbands_on_the_pitch(self):
        page = rb.render(snap(), {"xi": ["Keeper", "Middle", "Striker"], "captain": {"name": "Striker"}, "vice": {"name": "Middle"}})
        self.assertIn('<span class="arm">C</span>', page)
        self.assertIn('<span class="arm v">V</span>', page)

    def test_incoming_transfer_found_in_candidates(self):
        page = rb.render(snap(), {"transfers": [{"out": "Striker", "in": "Newboy", "bank_after": 0.3, "confidence": "lean"}]})
        self.assertIn("£7.2m · T9", page)
        self.assertIn("bank £0.3m after", page)

    def test_only_https_source_links(self):
        page = rb.render(snap(), {"sources": [{"label": "Bad", "url": "javascript:alert(1)"}, {"label": "Good", "url": "https://example.com"}]})
        self.assertNotIn("javascript:", page)
        self.assertIn('href="https://example.com"', page)

    def test_metrics_from_the_old_page_are_kept(self):
        # Regression (22 Nov 2026): the first version of the design dropped team value,
        # chips left, per-player form, the captain alternative and bench fixtures.
        s = snap()
        s["team_value"] = 102.8
        s["chips"] = [{"chip": "Free Hit", "available": True}, {"chip": "Wildcard", "available": False}]
        for p in s["squad"]:
            p["form"] = 6.3
        page = rb.render(s, {"xi": ["Keeper"], "bench": ["Back"], "captain_alt": {"name": "Middle"}})
        self.assertIn("£102.8m</b> team value", page)
        self.assertIn("Free Hit</b> chips left", page)
        self.assertIn("form 6.3", page)
        self.assertIn("Alt. captain", page)
        self.assertIn('<span class="bt"><i>1</i>Back <span class="fdr f2">', page)

    def test_rolling_comes_first_and_moves_become_optional(self):
        # Regression (GW11): the brief pushed a transfer every week; rolling must read as the call.
        page = rb.render(snap(), {"roll": "Roll the transfer", "transfers": [{"out": "Striker", "in": "Newboy"}]})
        self.assertLess(page.index("Roll the transfer"), page.index("Newboy"))
        self.assertIn('<span class="k">Optional</span>', page)
        self.assertIn(">Optional move</h2>", page)
        self.assertNotIn('<span class="k">Transfer</span><span class="v"><b>Striker', page)

    def test_empty_brief_still_renders_closing_line(self):
        page = rb.render({"team": {}, "next_gameweek": 1}, {})
        self.assertIn("Reply in a chat with what you want to go with", page)


if __name__ == "__main__":
    unittest.main()


class TransferRules(unittest.TestCase):
    """Regression for GW11 (22 Nov 2026): the brief and the sample recommended buying
    N.Jackson on returns alone. The rules in SKILL.md are checked in code."""

    def snap_with(self, in_verdict, out_verdict):
        s = snap()
        s["candidates"]["FWD"][0]["recent"] = {"underlying_last_4": {"verdict": in_verdict}}
        s["squad"][3]["recent"] = {"underlying_last_4": {"verdict": out_verdict}}
        return s

    def test_move_without_a_reason_is_flagged(self):
        problems = rb.check_transfers(snap(), {"transfers": [{"out": "Striker", "in": "Newboy"}]})
        self.assertIn("no reason", problems[0])

    def test_buying_a_player_running_hot_is_flagged(self):
        s = self.snap_with("running hot: returns well above chances", "in line with chances")
        problems = rb.check_transfers(s, {"transfers": [{"out": "Striker", "in": "Newboy", "reason": "clearly better"}]})
        self.assertTrue(any("ahead of his chances" in p for p in problems), problems)

    def test_selling_an_unlucky_player_is_flagged(self):
        s = self.snap_with("in line with chances", "unlucky: chances are there, returns aren't")
        problems = rb.check_transfers(s, {"transfers": [{"out": "Striker", "in": "Newboy", "reason": "poor form"}]})
        self.assertTrue(any("has the chances" in p for p in problems), problems)

    def test_a_red_flag_outranks_form(self):
        s = self.snap_with("running hot: returns well above chances", "unlucky: chances are there, returns aren't")
        self.assertEqual(rb.check_transfers(s, {"transfers": [{"out": "Striker", "in": "Newboy", "reason": "red flag"}]}), [])

    def test_problems_show_on_the_page(self):
        page = rb.render(snap(), {"transfers": [{"out": "Striker", "in": "Newboy"}]})
        self.assertIn("Rule check:", page)

    def test_example_decisions_follow_the_rules(self):
        import json
        with open(os.path.join(os.path.dirname(__file__), "..", "examples", "brief.json"), encoding="utf-8") as f:
            brief = json.load(f)
        self.assertTrue(brief.get("roll"), "the example should show rolling as the default call")
        self.assertEqual(rb.check_transfers(snap(), brief), [])

    def test_sample_brief_does_not_recommend_a_rejected_move(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "examples", "sample-brief.md"), encoding="utf-8") as f:
            text = f.read()
        rec = next(line for line in text.splitlines() if line.startswith("**Recommendation:"))
        self.assertIn("roll", rec.lower(), rec)
        self.assertNotIn("Calvert-Lewin → N.Jackson. Fairly strong call", text)
