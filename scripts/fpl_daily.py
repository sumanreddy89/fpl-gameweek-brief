#!/usr/bin/env python3
"""Decide what a once-a-day FPL check should do, and print it as JSON.

Says whether today is the day to write the gameweek brief, and lists any price
changes the manager can act on before the next 00:00 UK update.

With --calls-file (the call log fpl_scorecard.py --record writes), it also skips a brief
that was already written for this gameweek, and catches up a missed one: if the evening
run didn't happen, a run between 1 and 6 hours before the deadline writes a late brief.
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta, timezone

import fpl_scorecard
import fpl_snapshot as snap

# Run once a day, so exactly one run lands in any 24-hour window.
BRIEF_MIN_HOURS = 6
BRIEF_MAX_HOURS = 30
AFTER_DEADLINE_HOURS = 24
# A missed evening run can still catch up this close to the deadline (needs the call log).
LATE_MIN_HOURS = 1
# FPL expects a change at 100. Slightly lower catches players a late surge tips over.
ALERT_PCT = 95
TARGETS_PER_POSITION = 3


def projected(row):
    outlook = row.get("price_outlook") or {}
    if outlook.get("locked_until"):
        return None
    return outlook.get("projected_next_update_pct")


def price_alerts(snapshot):
    alerts = []
    for row in snapshot["squad"]:
        pct = projected(row)
        sell, after = row.get("selling_price"), row.get("selling_price_after_fall")
        if pct is not None and pct <= -ALERT_PCT and sell is not None and after < sell:
            alerts.append({"type": "squad_falling", "player": row["name"], "club": row["club"],
                           "projected_pct": pct, "selling_price_now": sell,
                           "selling_price_after": after})
    for position, rows in snapshot["candidates"].items():
        for row in rows[:TARGETS_PER_POSITION]:
            pct = projected(row)
            if pct is not None and pct >= ALERT_PCT:
                alerts.append({"type": "target_rising", "player": row["name"], "club": row["club"],
                               "position": position, "projected_pct": pct, "price": row["price"],
                               "can_replace": row["can_replace"]})
    return alerts


def after_deadline_due(boot, now_text):
    """True on the first daily run after a deadline, once lineups are public."""
    now = (datetime.fromisoformat(now_text.replace("Z", "+00:00")) if now_text
           else datetime.now(timezone.utc))
    past = [datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00"))
            for ev in boot["events"]]
    past = [d for d in past if d <= now]
    return bool(past) and (now - max(past)).total_seconds() / 3600 <= AFTER_DEADLINE_HOURS


def written_for(path, gw):
    """True if the call log has a line for this gameweek, None if there's no log to check."""
    if not path:
        return None
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            return any((fpl_scorecard.parse_call(line) or {}).get("gw") == gw for line in f)
    except FileNotFoundError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--data-dir")
    ap.add_argument("--now")
    ap.add_argument("--calls-file", help="call log from fpl_scorecard.py --record: skip a brief already written, catch up a missed one")
    args = ap.parse_args(argv)

    forward = ["--team-id", str(args.team_id)]
    for flag, value in (("--data-dir", args.data_dir), ("--now", args.now)):
        if value:
            forward += [flag, value]
    try:
        source = snap.Source(args.data_dir)
        snapshot = snap.build_snapshot(snap.parse_args(forward), source)
    except snap.FetchError as e:
        raise SystemExit(str(e)) from None
    if snapshot.get("season_over"):
        out = {"season_over": True, "write_brief_today": False, "price_alerts": []}
    else:
        hours = snapshot["hours_to_deadline"]
        gw = snapshot["next_gameweek"]
        written = written_for(args.calls_file, gw)
        in_window = BRIEF_MIN_HOURS <= hours < BRIEF_MAX_HOURS
        late = written is False and LATE_MIN_HOURS <= hours < BRIEF_MIN_HOURS
        deadline = datetime.fromisoformat(snapshot["deadline_utc"])
        out = {"next_gameweek": gw,
               "deadline_utc": snapshot["deadline_utc"],
               "hours_to_deadline": hours,
               "write_brief_today": (in_window or late) and not written,
               "late_brief": late,
               "brief_already_written": written,
               # When a daily run should write the brief: any run in this window does.
               "brief_window_utc": [(deadline - timedelta(hours=BRIEF_MAX_HOURS)).isoformat(),
                                    (deadline - timedelta(hours=BRIEF_MIN_HOURS)).isoformat()],
               "after_deadline_view_due": after_deadline_due(source.get("bootstrap-static/"), args.now),
               "price_alerts": price_alerts(snapshot),
               "squad_source": snapshot["squad_source"],
               "data_gaps": snapshot["data_gaps"]}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
