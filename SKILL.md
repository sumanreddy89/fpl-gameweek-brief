---
name: fpl-gameweek-brief
description: Preps a Fantasy Premier League team before a gameweek deadline: injury flags, transfers, captain, XI, bench and chips. Use for questions about an FPL team, transfers, captain or bench.
---

# FPL gameweek brief

Produce a short, sourced brief that helps one manager decide what to do before the next Fantasy Premier League deadline. The brief makes recommendations only. Never sign in to FPL, make transfers, change the captain or play a chip unless the manager asks for that specific change in the conversation and confirms it.

## Inputs

- **FPL team ID.** This is required. It's the number in the URL when the manager opens "Points" on the FPL site: `fantasy.premierleague.com/entry/<ID>/event/...`. If you don't have it and can ask, ask. In an unattended run without it, stop and say it's missing.
- **Time zone** for showing the deadline. If none is given, use UTC and say so.
- **Current squad**, optional. Public data shows the squad as it was locked at the last deadline (see Limits). If the manager has made transfers since then, use the names they give you, or a screenshot of their Pick Team screen.

## Step 1: Get the data

Run the bundled script. It reads the public FPL API and prints about 20 KB of JSON with only what the brief needs:

```bash
python3 scripts/fpl_snapshot.py --team-id <ID>
# after mid-week transfers:
python3 scripts/fpl_snapshot.py --team-id <ID> --squad "Raya,Gabriel,...,Haaland" --bank 1.5
```

If the shell can't reach `fantasy.premierleague.com` (some sandboxes block it), use one of these fallbacks instead:
- A browser tool. Open any `fantasy.premierleague.com/api/...` URL, then `fetch()` the same endpoints from that page's context and reduce them the way the script does.
- Read smaller endpoints directly: `entry/<ID>/`, `entry/<ID>/history/`, `entry/<ID>/event/<GW>/picks/` and `fixtures/?event=<GW>`. Don't try to read all of `bootstrap-static/` through a web reader. It's several MB, and the reader will truncate it.

Do every calculation in code: hours to the deadline, bank after each transfer, and free transfers.

## Step 2: Check the deadline and team news

- Treat the deadline from the API as fixed. Convert it to the manager's time zone, and note any clock change between now and the deadline.
- Search for team news on every squad player who is flagged, in poor form or heavily sold, and on every transfer target. Use sources from the last three days: club press conferences, official club sites, and well-known FPL sites such as Fantasy Football Scout or Fantasy Football Hub. Record the date of each source.
- Tell confirmed facts apart from speculation. A manager's quote is a fact. Reader comments and "rotation risk" chatter are not. Never present speculation as a reason without labelling it.

## Step 3: Decide

Work through these in order.

1. **Red flags.** List anyone injured, suspended, doubtful (75% or lower), with a blank gameweek, or whose minutes are shrinking.
2. **Transfers.** Give one to three options that fit the bank and the free transfers. For each, give who goes out, who comes in, the bank afterwards and a one-line reason (fixtures over the next 3–4 gameweeks, form, minutes, set pieces). Respect the 3-per-club limit and the 15-man shape (2 GK, 5 DEF, 5 MID, 3 FWD).
   - Say whether rolling the transfer is better. If 5 transfers are already banked, an unused one is wasted, so say so.
   - A hit (−4) needs a clear case: an injured starter with no cover, or a strong double gameweek.
   - Selling price can be below the current price after a rise, because FPL keeps half of any profit. Tell the manager to check the exact bank figure in the app.
3. **Captain and vice-captain.** Give one pick each and one alternative. Weigh fixture, form, penalties, nailed minutes and FPL's `ep_next`. The vice-captain should be someone who is very likely to start.
4. **Starting XI and bench.** Choose a valid formation (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD). Order the bench by who is most likely to be needed and to score, so that each substitute can legally replace the starters most likely to miss out.
5. **Chips.** Say which chips are still available in this half-season window, and whether this gameweek is a good time for one. Bench Boost and Triple Captain suit double gameweeks, and Free Hit suits blanks. Most weeks the answer is to hold.
6. **Price watch.** Name the players being heavily bought or sold, among the squad and the targets.

Also look at both sides of any match where the squad has players on both teams, or several defenders on one team. Correlated outcomes are worth one line.

## Step 4: Write the brief

Keep it short enough to read on a phone. Use these sections, in this order:

1. The deadline in local time, plus points, rank, bank and free transfers
2. Squad flags
3. Transfers, with a one-line recommendation
4. Captain and vice-captain
5. The XI as a table (player, club, fixture with its difficulty, form), then the bench in order
6. Chips
7. Price watch
8. Sources, with dates

Label your confidence honestly. Say which calls are strong and which are close to a coin flip, and name any player you couldn't get data for. End with an invitation to reply with what they want to go with.

If the environment can publish a page or document, deliver the brief that way. Otherwise reply with it directly.

## Limits

- **The public squad lags behind.** FPL publishes a team's picks only after each deadline, so transfers made since the last deadline don't show up without the manager's login. Always say which squad source the brief used.
- **Free transfers are an estimate.** The script replays the season under the current rules: +1 each gameweek, a maximum of 5, and Wildcard and Free Hit weeks don't use any. Special rule changes, such as a mid-season top-up, can make it wrong. Tell the manager to check the number on their Transfers screen.
- **The API is unofficial.** These endpoints aren't documented, and their fields can change between seasons. If a field is missing, say so rather than guessing.

## Scheduling (optional)

To get the brief before every gameweek, schedule one run for 24 hours before the next deadline. At the end of each run, schedule the following one, so the chain follows irregular midweek rounds and rescheduled fixtures. Each run should do two things:
- Check the deadline again first, and reschedule itself if the deadline has moved.
- Schedule the next run before writing the brief, so a failed brief doesn't break the chain. The brief should also say when the next one is due.
