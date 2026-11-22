---
name: fpl-gameweek-brief
description: Preps a Fantasy Premier League team before a gameweek deadline, covering injury flags, transfers, captain, XI, bench and chips. Use for questions about an FPL team, transfers, captain or bench.

---

# FPL gameweek brief

Produce a short, sourced brief that helps one manager decide what to do before the next Fantasy Premier League deadline. The brief makes recommendations only. Never sign in to FPL, make transfers, change the captain or play a chip unless the manager asks for that specific change in the conversation and confirms it.

## Inputs

- **FPL team ID.** This is required. It's the number in the URL when the manager opens "Points" on the FPL site: `fantasy.premierleague.com/entry/<ID>/event/...`. If you don't have it and can ask, ask. In an unattended run without it, stop and say it's missing.
- **Time zone** for showing the deadline. If none is given, use UTC and say so.
- **Current squad**, optional. Public data shows the squad as it was locked at the last deadline (see Limits). If the manager has made transfers since then, use the names they give you, or a screenshot of their Pick Team screen.

## Step 1: Get the data

Run the bundled script. It reads the public FPL API and prints about 40 KB of JSON with only what the brief needs:

```bash
python3 scripts/fpl_snapshot.py --team-id <ID>
# after mid-week transfers:
python3 scripts/fpl_snapshot.py --team-id <ID> --squad "Raya,Gabriel,...,Haaland" --bank 1.5
```

With `--squad`, the script compares the names with the locked squad and takes those moves off the free transfers. It also estimates the bank if `--bank` is missing, so prefer the manager's own bank figure when they give one. Anything listed in `data_gaps` is missing: say so in the brief rather than guessing.

If the shell can't reach `fantasy.premierleague.com` (some sandboxes block it), use one of these fallbacks instead:
- A browser tool. Open any `fantasy.premierleague.com/api/...` URL, then `fetch()` the same endpoints from that page's context and reduce them the way the script does.
- Read smaller endpoints directly: `entry/<ID>/`, `entry/<ID>/history/`, `entry/<ID>/event/<GW>/picks/` and `fixtures/?event=<GW>`. Don't try to read all of `bootstrap-static/` through a web reader. It's several MB, and the reader will truncate it.

Do every calculation in code: hours to the deadline, bank after each transfer, and free transfers.

## Step 2: Check the deadline and team news

- Treat the deadline from the API as fixed. Convert it to the manager's time zone, and note any clock change between now and the deadline.
- Search for team news on every squad player who is flagged, in poor form or heavily sold, and on every transfer target. Use sources from the last three days: club press conferences, official club sites, and well-known FPL sites such as Fantasy Football Scout or Fantasy Football Hub. Record the date of each source.
- Put the season and the gameweek in every search (for example `Haaland injury news GW12 2026/27`, or the club and the opponent), and check each result's date. Searches without them return old seasons; if nothing from the last three days turns up, say so rather than using older news.
- For each player the review below marks as blanked or in `poor form`, look for one piece of expert analysis from the last week: a press-conference quote about role or fitness, or an FPL site's analysis (Fantasy Football Hub, Fantasy Football Scout). Use only what's free to read; never work around a paywall or a login. Name the source and date.
- Tell confirmed facts apart from speculation. A manager's quote is a fact. Reader comments and "rotation risk" chatter are not. Never present speculation as a reason without labelling it.

## Step 3: Decide

Start with the last gameweek, then work through the decisions in order.

0. **Last gameweek review.** `last_gw_review` gives the captain's points, minutes and xGI (expected goal involvement) and every starter who played and scored 2 or fewer. Each squad player's `recent.underlying_last_4` compares goals plus assists with xGI over the last four matches and gives a `verdict`. Use it to say, in one line each, why the captain and each blank happened:
   - `unlucky`: the chances were there. Usually hold, and keep the captaincy if the fixture is fine.
   - `poor form`: few chances for four matches. A sell candidate if the fixtures don't help; check team news for a role change or an injury first.
   - `running hot`: returns well above chances. Don't buy, or captain, on returns alone.
   - Goalkeepers and defenders aren't judged on xGI: a blank there is usually goals conceded, so look at the team's fixtures, not the player.
   Feed this into the transfers and captain below, and say when it changed a call.

1. **Red flags.** List anyone injured, suspended, doubtful (75% or lower), with a blank gameweek, or whose `recent.minutes_trend` is `falling`. Check the reason for falling minutes in team news before calling it a problem, because a short injury or a suspension also shows up this way.
2. **Transfers.** Give one to three options that fit the bank and the free transfers. Start from `candidates`: they're already limited to players one transfer can afford, and `can_replace` names who could make way while staying within the budget and the 3-per-club limit. Bank afterwards = `bank` + the outgoing player's `selling_price` − the incoming player's `price`. For each option, give who goes out, who comes in, the bank afterwards and a one-line reason (fixtures over the next 3–4 gameweeks, form, `xgi_per_90`, minutes, `set_pieces`, and `defensive_contribution_per_90` for defenders and deeper midfielders). Respect the 15-man shape (2 GK, 5 DEF, 5 MID, 3 FWD). `projected_horizon` is a rough sort order, so never quote it as a forecast. For a two-transfer move that funds a premium, re-run with `--all-prices`.
   - **Rolling is the default.** A free transfer doesn't have to be used, and a banked one gives more choice later. Recommend a move only when one of these holds, and name which:
     1. A red flag from step 1: injured, suspended, doubtful, a blank gameweek, or minutes falling for a reason team news confirms.
     2. The outgoing player is in `poor form` on `underlying_last_4` and the next 3–4 fixtures don't help.
     3. The incoming player is clearly better on chances (xGI, minutes, set pieces) over the next 3–4 fixtures, not just on recent points, and the gain is worth more than the flexibility of a banked transfer.
   - Never sell a player whose verdict is `unlucky` on a blank run alone, and never buy one who is `running hot` on returns alone. In GW11 the brief sold Calvert-Lewin for N.Jackson, who was running hot, and Calvert-Lewin scored twice that week.
   - When no move meets the bar, recommend rolling and say what would change that (a press-conference update, a price move). Show the best option anyway, marked as optional. Only if 5 transfers are already banked is an unused one wasted: then say so and use it.
   - A hit (−4) needs a clear case: an injured starter with no cover, or a strong double gameweek.
   - `selling_price` is an estimate, because FPL keeps half of any profit and the script works this out from the public transfer log. If a move is within £0.2m of the budget, tell the manager to check the exact figure in the app.
3. **Captain and vice-captain.** Give one pick each and one alternative. Weigh fixture, form, `set_pieces` (`penalties: 1` means first choice), recent minutes and FPL's `ep_next`. The vice-captain should be someone who is very likely to start.
4. **Starting XI and bench.** Choose a valid formation (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD). Order the bench by who is most likely to be needed and to score, so that each substitute can legally replace the starters most likely to miss out.
5. **Chips: a plan to the deadline, not just this week.** Chips left unused at the end of their window are lost, so give a provisional week for every remaining chip, using `chip_plan` (each gameweek up to the last chip deadline: doubles and blanks, games for the XI and the bench, average difficulty, squad blanks and doubles, and `captain_options`, the squad's easy games):
   - **Double and blank gameweeks first.** Bench Boost and Triple Captain suit a double gameweek for your players; Free Hit suits a week when several of your starters blank. Clubs in `unscheduled_fixtures` are the likeliest to get a double later, so say if waiting could pay.
   - **With no doubles or blanks before the deadline,** time chips on fixtures: Triple Captain on the week your best captain has his easiest home game (check `captain_options` and his minutes); Bench Boost on the week the whole 15 has the easiest fixtures (low `bench_avg_fdr` as well as `xi_avg_fdr`, all 15 likely to play); Free Hit on the week your XI's fixtures are hardest, or keep it for a blank if one is announced.
   - Don't stack two chips in one week, and leave a week of slack before the deadline in case a fixture moves.
   - Say whether this gameweek is the week for one. Most weeks it isn't. If the plan changed since last week, say why (a new double, an injury to the planned captain).
   - In the decisions file, put each chip in `chip_plan` with its gameweek, the player or reason (`on`), a one-line `why` and a confidence. The page draws the weeks as a strip.
6. **Price watch.** Use `price_outlook` for the squad and the targets. A `projected_next_update_pct` of 100 or more (or −100 or less) means FPL expects a change at the next 00:00 UK update, though it's a guide and not a guarantee.
7. **Mini-leagues.** If the manager wants league insight, run `python3 scripts/fpl_leagues.py --team-id <ID>`. Report the league where their picks did best and worst. For the latest gameweeks, use `by_gameweek` to name the player who gave the biggest upside and the biggest downside in that gameweek. Use `by_position` to say where the manager is really gaining or losing ground. Don't present one player's season total as a gain or loss on its own, because players in one position replace each other: `Verbruggen +26, Raya -34` is one goalkeeper decision worth -8. Lead the section with `decisions`, and show the facts rather than a score. For the coming gameweek, use `this_gameweek`: who rivals start and the manager doesn't, who the manager benches and rivals start, the manager's differentials, and rival captains. For transfers, use `transfer_gaps`: how many rivals start the player, the difficulty of each coming fixture and a plain run label. Check these against form, minutes and team news before recommending a move, and say that rival lineups are from the last deadline. `context_last_5` is history, so use it only as context. Use `last_5_vs_league_avg` for recent form, then say which players and captains to watch before the deadline. `points_vs_league_avg` is before hits. Rival team names are private to the manager, so don't put them anywhere public.

Also look at both sides of any match where the squad has players on both teams, or several defenders on one team. Correlated outcomes are worth one line.

## Step 4: Write the brief

If the environment can run scripts and publish a page, render it with the bundled design instead of writing HTML yourself. Save the snapshot output to a file, write your decisions as JSON with the Write tool (shape in `examples/brief.json`), then run:

```bash
python3 scripts/render_brief.py --snapshot /tmp/snap.json --brief /tmp/brief.json --out /tmp/brief.html
```

and publish `/tmp/brief.html`. The renderer takes fixtures, form, xGI and the last gameweek from the snapshot, so don't retype numbers in the JSON. Give each decision a confidence of `strong`, `lean` or `coin flip`, and give each transfer a `reason`: `red flag`, `poor form` or `clearly better` (the three reasons in Step 3). The renderer checks the transfer rules and prints any break as a "Rule check" line on the page and on stderr: change the call rather than publish with one. Players it can't find are shown as "not in data": fix the name rather than leaving it. If the renderer fails, write the page yourself with the same sections.

Keep it short enough to read on a phone. Use these sections, in this order:

1. The deadline in local time, plus points, rank, bank and free transfers
2. Your moves: transfers, captain, vice and chip, each with a confidence
3. Last gameweek review: the captain and each blank, bad luck or bad form
4. Squad flags
5. The XI by position (the renderer draws a pitch), then the bench in order
6. Form check: chances against returns for the attackers
7. Transfers in detail, with the bank sums
8. Chips and price watch
9. Mini-leagues, if the manager is in small private leagues: where rivals have an edge, then the gameweek and position views
10. Confidence and sources, with dates

Label your confidence honestly. Say which calls are strong and which are close to a coin flip, and name any player you couldn't get data for. End with: "Reply with what you want to go with, and I'll help make the changes."

If the environment can publish a page or document, deliver the brief that way. Otherwise reply with it directly.

## Daily check

`python3 scripts/fpl_daily.py --team-id <ID>` is cheap to run every evening. `write_brief_today` is true on the last evening at least 6 hours before the deadline. `after_deadline_view_due` is true on the first run after a deadline: run `python3 scripts/fpl_leagues.py --team-id <ID> --after-deadline` and tell the manager who they want to score and to blank in each league. `swing_per_point` is exact, because lineups are locked. `price_alerts` lists only moves the manager can act on before tonight's update: a squad player whose fall would cut their selling price, or a top transfer target about to rise. If there are no alerts and no brief is due, stay silent.

## Limits

- **The public squad lags behind.** FPL publishes a team's picks only after each deadline, so transfers made since the last deadline don't show up without the manager's login. Always say which squad source the brief used. After a Free Hit, the script uses the squad from the gameweek before it, because the Free Hit team reverts.
- **Free transfers are an estimate.** The script replays the season under the current rules: +1 each gameweek, a maximum of 5, and Wildcard and Free Hit weeks don't use any. Special rule changes, such as a mid-season top-up, can make it wrong. Tell the manager to check the number on their Transfers screen.
- **The API is unofficial.** These endpoints aren't documented, and their fields can change between seasons. If a field is missing, say so rather than guessing.

## Scheduling (optional)

To get the brief automatically, use one recurring routine that runs once every evening and calls the daily check above. Write the brief only when `write_brief_today` is true, and send the after-deadline note only when `after_deadline_view_due` is true. Don't have a run create the next run: unattended runs stop for approval when they create a task, which can hold up the brief for hours.
