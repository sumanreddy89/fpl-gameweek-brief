# Running the brief on a schedule

One routine that runs every evening does everything: it writes the brief on the last evening before a deadline, sends a short note after the deadline, and stays quiet otherwise unless a price change is worth acting on tonight.

## Set it up (Claude Code routines)

1. Open **claude.ai/code/routines** and create a routine.
2. **Repository:** attach `sumanreddy89/fpl-gameweek-brief` (or your fork). Each run then uses the latest `SKILL.md` and scripts from `main`, so updates reach you without re-uploading anything.
3. **Network:** allow `fantasy.premierleague.com`. Without it the scripts can't read FPL, and the brief falls back to a thinner version without price alerts or mini-leagues.
4. **Schedule:** once a day, in the evening, for example `0 19 * * *` (19:00 UTC). Once a day matters: the brief is due in a 24-hour window (6 to 30 hours before the deadline), so exactly one daily run lands in it.
5. **Prompt:** paste the one below and fill in the two values at the top.
6. Turn on push notifications for the routine if you want the key picks on your phone.

## The prompt

```text
FPL daily check. My FPL team ID is <TEAM_ID>. My time zone is <TIME_ZONE, e.g. Europe/London>.

The repository fpl-gameweek-brief is attached. Work from its checkout (the folder with SKILL.md) and read SKILL.md first; follow it. Use the repository read-only: never edit, commit, push or open pull requests.

Every run:
1. Run `python3 scripts/fpl_daily.py --team-id <TEAM_ID>` and read write_brief_today, after_deadline_view_due and price_alerts.
2. If price_alerts isn't empty, send one push notification naming each player and what to consider before 00:00 UK time. FPL's predictor is a guide, not a guarantee.
3. If after_deadline_view_due is true, run `python3 scripts/fpl_leagues.py --team-id <TEAM_ID> --after-deadline`, publish a short page with who I want to score and to blank in each league, and send a push with the main swings.
4. If write_brief_today is true, write the brief as SKILL.md describes (snapshot, review, decisions JSON, render_brief.py), publish the page, and send a push with the key picks. If late_brief is true, say at the top that it's a late brief.
5. Otherwise end the run with one line saying when the next brief is due (brief_window_utc), in my time zone.

Rules: this runs unattended, so don't ask questions; make the reasonable call and note it. Never sign in to FPL or change my team. Never create, update or run scheduled tasks. Write pages with the Write tool, not with heredocs in Bash.
```

## How to tell it ran

- **Every evening leaves a run** in the routine's history on claude.ai/code/routines. Open the latest one: it ends with one line, such as "No brief tonight: the GW12 deadline is 40 hours away; the brief is due tomorrow evening."
- **On brief nights** you get a page and a push notification.
- **To see when the next brief is due,** run `python3 scripts/fpl_daily.py --team-id <TEAM_ID>` yourself: `brief_window_utc` is the window in which a run writes it.
- **If an evening shows no run at all,** the scheduler skipped it. Check that the routine is enabled; the next evening's run carries on normally.

## Deadline changes and missed runs

The daily check reads the deadline fresh every run, so a moved deadline is picked up automatically.

A run that doesn't happen (a skipped evening) would normally mean no brief that week. If the runs can keep a call log between them (`fpl_scorecard.py --record`, see SKILL.md), pass it with `--calls-file`: the check then skips a brief already written for that gameweek, and a run between 1 and 6 hours before the deadline writes a late brief instead of nothing. A routine's sandbox starts fresh each run, so the log has to live somewhere the next run can read, such as a notes page in a connected app; without one, the brief still works but has no track record or catch-up.

## Don't

- **Don't have a run schedule the next run.** An unattended run that creates a task stops for approval, which can hold the brief up for hours.
- **Don't rely on a skill uploaded to your Claude account for the scripts.** A routine should attach the repository instead.
