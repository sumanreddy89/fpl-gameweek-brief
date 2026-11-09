#!/usr/bin/env python3
"""Compact snapshot of an FPL team for a pre-deadline brief.

Pulls the public Fantasy Premier League endpoints and prints one small JSON
document with everything a gameweek brief needs: the next deadline, the squad
with form/price/injury news, recent minutes, set-piece roles, estimated selling
prices and upcoming fixtures, bank, an estimate of free transfers, chips,
blank/double gameweeks, and affordable transfer candidates per position.

The full bootstrap file is several MB, which is too big for most agent web
readers; this script exists so the agent only reads the part that matters.

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
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://fantasy.premierleague.com/api/"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit",
              "bboost": "Bench Boost", "3xc": "Triple Captain"}
DEFAULT_MAX_FREE_TRANSFERS = 5
DEFAULT_CLUB_LIMIT = 3
HIT_COST = 4
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3
# How a later fixture's FPL difficulty scales a player's expected points.
FDR_WEIGHT = {1: 1.25, 2: 1.1, 3: 1.0, 4: 0.85, 5: 0.7}


class FetchError(Exception):
    """An endpoint could not be read."""


class NotFound(FetchError):
    """The endpoint does not exist (404, or no saved file for it)."""


class Source:
    """Fetches an endpoint from the live API, or from saved JSON files."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.cache = {}

    def get(self, path):
        if path not in self.cache:
            self.cache[path] = self._read_file(path) if self.data_dir else self._fetch(path)
        return self.cache[path]

    def _read_file(self, path):
        name = path.strip("/").replace("/", "_") + ".json"
        try:
            with open(os.path.join(self.data_dir, name), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise NotFound(f"No saved file for {path}.") from None

    def _fetch(self, path):
        req = urllib.request.Request(
            BASE + path, headers={"User-Agent": "fpl-gameweek-brief/1.1"})
        problem = "unknown error"
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise NotFound(f"{path} was not found (HTTP 404).") from None
                problem = f"HTTP {e.code}"
                if e.code not in RETRY_STATUS:
                    break
            except (urllib.error.URLError, OSError) as e:
                problem = str(getattr(e, "reason", e))
            except ValueError:
                # FPL serves a non-JSON holding page while the game updates.
                problem = "the response was not JSON (the game may be updating)"
        raise FetchError(f"Could not read {path} from the FPL API: {problem}.")


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


def number(e, key):
    """A numeric API field as a float, or None if it's absent or blank."""
    value = e.get(key)
    return None if value in (None, "") else float(value)


def team_fixtures(team_id, gw, fixtures):
    """(opponent, is_home, difficulty) for each of a team's games in a gameweek."""
    out = []
    for f in fixtures:
        if f.get("event") != gw:
            continue
        if f["team_h"] == team_id:
            out.append((f["team_a"], True, f["team_h_difficulty"]))
        elif f["team_a"] == team_id:
            out.append((f["team_h"], False, f["team_a_difficulty"]))
    return out


def fixtures_for(team_id, gws, fixtures, teams):
    out = []
    for gw in gws:
        games = team_fixtures(team_id, gw, fixtures)
        if not games:
            out.append(f"GW{gw}: BLANK")
            continue
        parts = [f'{teams[opp]} ({"H" if home else "A"}) {fdr}' for opp, home, fdr in games]
        out.append(f"GW{gw}: " + " + ".join(parts))
    return out


def projected_points(e, gws, fixtures, last_gw):
    """A rough points total across the horizon, for ranking only.

    The next gameweek uses FPL's own ep_next. Later gameweeks use the average of
    form and points per game, scaled by share of minutes and fixture difficulty.
    Blanks score nothing and double gameweeks count both games.
    """
    total = number(e, "ep_next") or 0.0
    base = ((number(e, "form") or 0.0) + (number(e, "points_per_game") or 0.0)) / 2
    minutes_share = min(1.0, e["minutes"] / (90 * max(1, last_gw)))
    for gw in gws[1:]:
        for _, _, fdr in team_fixtures(e["team"], gw, fixtures):
            total += base * minutes_share * FDR_WEIGHT.get(fdr, 1.0)
    return round(total, 1)


def set_pieces(e):
    """Set-piece duties as {role: order in the club's pecking order}, or None."""
    roles = {"penalties": e.get("penalties_order"),
             "corners": e.get("corners_and_indirect_freekicks_order"),
             "free_kicks": e.get("direct_freekicks_order")}
    return {k: v for k, v in roles.items() if v} or None


def player_row(e, teams, fixtures, gws, last_gw):
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
        "news_added": e.get("news_added") if e["news"] else None,
        "form": float(e["form"]),
        "points_per_game": number(e, "points_per_game"),
        "ep_next": float(e["ep_next"] or 0),
        "projected_horizon": projected_points(e, gws, fixtures, last_gw),
        "total_points": e["total_points"],
        "minutes": e["minutes"],
        "starts": e.get("starts"),
        "xgi_per_90": number(e, "expected_goal_involvements_per_90"),
        "defensive_contribution_per_90": number(e, "defensive_contribution_per_90"),
        "set_pieces": set_pieces(e),
        "owned_pct": float(e["selected_by_percent"]),
        "transfers_in_gw": e["transfers_in_event"],
        "transfers_out_gw": e["transfers_out_event"],
        "fixtures": fixtures_for(e["team"], gws, fixtures, teams),
    }


def recent_matches(summary):
    """The last five matches, plus whether the player's minutes are falling."""
    rows = sorted(summary.get("history", []),
                  key=lambda r: (r.get("round", 0), r.get("kickoff_time") or ""))[-5:]
    minutes = [r.get("minutes", 0) for r in rows]
    trend = "not enough matches"
    if len(minutes) >= 4:
        recent = sum(minutes[-2:]) / 2
        earlier = sum(minutes[:-2]) / len(minutes[:-2])
        trend = "falling" if earlier >= 45 and recent <= 0.6 * earlier else "steady"
    return {"matches": [f'GW{r.get("round")}: {r.get("minutes", 0)} min, '
                        f'{r.get("total_points", 0)} pts' for r in rows],
            "minutes_trend": trend}


def selling_price(bought, now):
    """FPL's selling price in tenths: half of any profit, rounded down."""
    return bought + (now - bought) // 2 if now > bought else now


def purchase_prices(squad_ids, new_ids, by_id, transfers, free_hit_weeks):
    """Estimate what the manager paid for each player, in tenths of £m.

    Uses the most recent real purchase. Free Hit transfers are skipped because
    those squads revert. Players with no purchase came from the opening squad,
    at the season's start price. Moves made since the deadline aren't public,
    so those players are taken to be bought at today's price.
    """
    latest = {}
    for t in sorted(transfers, key=lambda t: t.get("time") or ""):
        if t["event"] not in free_hit_weeks:
            latest[t["element_in"]] = t["element_in_cost"]
    prices = {}
    for pid in squad_ids:
        e = by_id[pid]
        if pid in new_ids:
            prices[pid] = e["now_cost"]
        else:
            prices[pid] = latest.get(pid, e["now_cost"] - e["cost_change_start"])
    return prices


def replaceable_by(candidate, squad_ids, by_id, selling, bank, club_counts, club_limit):
    """Names of squad players this candidate could directly replace."""
    names = []
    for pid in squad_ids:
        out = by_id[pid]
        if out["element_type"] != candidate["element_type"]:
            continue
        if candidate["now_cost"] > bank + selling[pid]:
            continue
        if (candidate["team"] != out["team"]
                and club_counts.get(candidate["team"], 0) >= club_limit):
            continue
        names.append(out["web_name"])
    return names


def estimate_free_transfers(history, started_event, next_gw, cap=DEFAULT_MAX_FREE_TRANSFERS):
    """Replay the season under current rules: +1 per gameweek, capped,
    transfers on Wildcard/Free Hit weeks don't use any. An estimate only."""
    chip_weeks = {c["event"] for c in history.get("chips", [])
                  if c["name"] in ("wildcard", "freehit")}
    made = {c["event"]: c["event_transfers"] for c in history.get("current", [])}
    ft = 1  # available for the gameweek after the one you joined in
    for gw in range(started_event + 1, next_gw):
        used = 0 if gw in chip_weeks else made.get(gw, 0)
        ft = max(1, min(cap, ft - used + 1))
    return ft


def chips_status(bootstrap, history, next_gw):
    used = history.get("chips", [])
    status = []
    for c in bootstrap.get("chips", []):
        start, stop = c.get("start_event"), c.get("stop_event")
        if start is None or stop is None or not (start <= next_gw <= stop):
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


def free_hit_weeks(history):
    return {c["event"] for c in history.get("chips", []) if c["name"] == "freehit"}


def locked_squad(src, team_id, last_gw, fh_weeks):
    """(gameweek, picks) for the manager's real squad, or None if there isn't one.

    A Free Hit squad lasts one gameweek and then reverts, so its picks are
    skipped in favour of the gameweek before.
    """
    gw = last_gw
    while gw in fh_weeks:
        gw -= 1
    if gw < 1:
        return None
    try:
        return gw, src.get(f"entry/{team_id}/event/{gw}/picks/")
    except NotFound:
        return None


def parse_squad(text, elements, by_id):
    ids = []
    for token in [t.strip() for t in text.split(",") if t.strip()]:
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
    return ids


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--squad", help="Comma-separated names (or ids) of the current 15, "
                    "to override the public squad after mid-week transfers.")
    ap.add_argument("--bank", type=float, help="Current bank in £m. Overrides the estimate.")
    ap.add_argument("--candidates", type=int, default=6, help="Candidates per position.")
    ap.add_argument("--horizon", type=int, default=4, help="Gameweeks of fixtures to show.")
    ap.add_argument("--min-minutes", type=int, default=450,
                    help="Minimum season minutes for a transfer candidate (default 450, about 5 full games).")
    ap.add_argument("--all-prices", action="store_true",
                    help="List candidates even if one transfer can't afford them.")
    ap.add_argument("--data-dir", help="Read saved JSON instead of the live API.")
    ap.add_argument("--now", help="Override the current time (ISO 8601), for testing.")
    return ap.parse_args(argv)


def build_snapshot(args, src):
    boot = src.get("bootstrap-static/")
    fixtures = src.get("fixtures/")
    try:
        entry = src.get(f"entry/{args.team_id}/")
    except NotFound:
        raise SystemExit(f"FPL has no team with ID {args.team_id}. Check the number in the "
                         "address bar on the Points page.") from None
    history = src.get(f"entry/{args.team_id}/history/")

    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    elements = boot["elements"]
    by_id = {e["id"]: e for e in elements}
    settings = boot.get("game_settings", {})
    club_limit = settings.get("squad_team_limit", DEFAULT_CLUB_LIMIT)
    extra = settings.get("max_extra_free_transfers")
    max_ft = extra + 1 if extra is not None else DEFAULT_MAX_FREE_TRANSFERS

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    upcoming = [ev for ev in boot["events"]
                if datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00")) > now]
    if not upcoming:
        return {"season_over": True}
    nxt = upcoming[0]
    next_gw = nxt["id"]
    deadline = datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
    last_gw = next_gw - 1
    final_gw = max(ev["id"] for ev in boot["events"])
    gws = [g for g in range(next_gw, next_gw + args.horizon) if g <= final_gw]

    data_gaps = []
    fh_weeks = free_hit_weeks(history)
    started = entry.get("started_event", 1)
    locked = locked_squad(src, args.team_id, last_gw, fh_weeks) if last_gw >= 1 else None

    locked_ids, locked_history, captain, vice = [], {}, None, None
    if locked:
        locked_gw, picks = locked
        ordered = sorted(picks["picks"], key=lambda p: p["position"])
        locked_ids = [p["element"] for p in ordered]
        locked_history = picks.get("entry_history") or {}
        captain = next((p["element"] for p in ordered if p["is_captain"]), None)
        vice = next((p["element"] for p in ordered if p["is_vice_captain"]), None)

    notes = []
    if args.squad:
        order = parse_squad(args.squad, elements, by_id)
        captain = vice = None
        squad_src = "manual (--squad)"
    elif locked:
        order = locked_ids
        squad_src = f"public picks locked at GW{locked_gw} deadline"
        if locked_gw != last_gw:
            squad_src += f" (GW{last_gw} was a Free Hit, and that squad has reverted)"
            notes.append(f"The GW{last_gw} Free Hit squad was ignored because it reverted.")
        notes.append("Transfers made since the last deadline are not visible here. "
                     "Ask the manager, or re-run with --squad.")
    else:
        raise SystemExit(f"Team {args.team_id} has no public squad yet (it started in "
                         f"GW{started}). Pass its 15 players with --squad.")

    # Transfers since the deadline, only knowable when --squad is given.
    locked_set = set(locked_ids)
    new_ids = set(order) - locked_set if locked else set()
    sold_ids = locked_set - set(order) if locked else set()
    if args.squad and not locked:
        data_gaps.append("No locked squad to compare --squad with, so transfers since the "
                         "deadline are unknown.")

    # Selling prices need the transfer log.
    try:
        transfers = src.get(f"entry/{args.team_id}/transfers/")
    except FetchError:
        transfers = None
        data_gaps.append("Transfer log unavailable, so selling prices are unknown.")
    selling = {}
    if transfers is not None and (locked or not args.squad):
        ids = list(set(order) | sold_ids)
        bought = purchase_prices(ids, new_ids, by_id, transfers, fh_weeks)
        selling = {i: selling_price(bought[i], by_id[i]["now_cost"]) for i in ids}

    # Bank in tenths of £m: --bank, else the locked bank adjusted for known moves.
    locked_bank = locked_history.get("bank", entry.get("last_deadline_bank") if locked else None)
    if args.bank is not None:
        bank = round(args.bank * 10)
        bank_src = "--bank"
    elif not args.squad:
        bank = locked_bank
        bank_src = "public data at the last deadline"
    elif locked_bank is not None and selling:
        bank = (locked_bank + sum(selling[i] for i in sold_ids)
                - sum(by_id[i]["now_cost"] for i in new_ids))
        bank_src = "estimated from the locked bank and the --squad changes"
    else:
        bank = None
        bank_src = None
        data_gaps.append("Bank unknown. Pass --bank.")

    # Free transfers, less any made since the deadline.
    ft_estimate = estimate_free_transfers(history, started, next_gw, max_ft)
    made_since = len(new_ids)
    hit_cost = max(0, made_since - ft_estimate) * HIT_COST
    if started >= next_gw:
        ft_estimate = None
        notes.append("This team hasn't reached its first deadline, so transfers are unlimited.")
        hit_cost = 0
    elif ft_estimate is not None:
        ft_estimate = max(0, ft_estimate - made_since)

    # One recent-match lookup per squad player.
    squad = []
    missing_history = []
    for i, pid in enumerate(order, 1):
        row = player_row(by_id[pid], teams, fixtures, gws, last_gw)
        row["slot"] = i if not args.squad else None
        row["role"] = ("captain" if pid == captain else
                       "vice" if pid == vice else None)
        row["selling_price"] = selling[pid] / 10 if pid in selling else None
        try:
            row["recent"] = recent_matches(src.get(f"element-summary/{pid}/"))
        except FetchError:
            row["recent"] = None
            missing_history.append(row["name"])
        squad.append(row)
    if missing_history:
        data_gaps.append("No recent-match data for: " + ", ".join(missing_history) + ".")

    club_counts = {}
    for pid in order:
        team = by_id[pid]["team"]
        club_counts[team] = club_counts.get(team, 0) + 1

    # Candidates that one transfer could actually bring in, best projection first.
    budget_known = bank is not None and all(pid in selling for pid in order)
    apply_budget = budget_known and not args.all_prices
    if not apply_budget and not args.all_prices:
        data_gaps.append("Bank or selling prices unknown, so candidates are not "
                         "filtered by affordability.")
    owned = set(order)
    candidates = {}
    for pt, label in POS.items():
        pool = [e for e in elements if e["element_type"] == pt and e["id"] not in owned
                and e["status"] == "a" and e["minutes"] >= args.min_minutes]
        pool.sort(key=lambda e: projected_points(e, gws, fixtures, last_gw), reverse=True)
        chosen = []
        for e in pool:
            options = None
            if budget_known:
                options = replaceable_by(e, order, by_id, selling, bank, club_counts, club_limit)
                if apply_budget and not options:
                    continue
            row = player_row(e, teams, fixtures, gws, last_gw)
            row["can_replace"] = options
            chosen.append(row)
            if len(chosen) == args.candidates:
                break
        candidates[label] = chosen

    if args.bank is not None:
        bank_out = args.bank
    else:
        bank_out = bank / 10 if bank is not None else None
    value = locked_history.get("value", entry.get("last_deadline_value"))
    return {
        "team": {"id": args.team_id, "name": entry.get("name"),
                 "overall_points": entry.get("summary_overall_points"),
                 "overall_rank": entry.get("summary_overall_rank")},
        "next_gameweek": next_gw,
        "deadline_utc": deadline.isoformat(),
        "hours_to_deadline": round((deadline - now).total_seconds() / 3600, 1),
        "squad_source": squad_src,
        "squad_note": " ".join(notes) or None,
        "bank": bank_out,
        "bank_source": bank_src,
        "team_value": (value or 0) / 10 or None,
        "free_transfers_estimate": ft_estimate,
        "transfers_since_deadline": sorted(by_id[i]["web_name"] for i in new_ids) or None,
        "hit_cost_already_taken": hit_cost or None,
        "chips": chips_status(boot, history, next_gw),
        "blank_double_gws": blank_double(fixtures, teams, gws),
        "clubs_at_limit": [teams[t] for t, n in club_counts.items() if n >= club_limit],
        "squad": squad,
        "candidates": candidates,
        "data_gaps": data_gaps or None,
        "fdr_key": "Fixture number is FPL difficulty, 1 easy to 5 hard.",
        "projection_key": "projected_horizon is a rough ranking heuristic, not a forecast.",
    }


def main(argv=None):
    args = parse_args(argv)
    try:
        out = build_snapshot(args, Source(args.data_dir))
    except FetchError as e:
        raise SystemExit(str(e)) from None
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
