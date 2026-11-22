# Changelog

What changed, newest first. Releases are tagged; the Claude app gets a change only when a new release ZIP is uploaded, while Claude Code and scheduled routines get `main` directly.

## v1.3 (22 Nov 2026)

**Scheduling and setup**
- `docs/SCHEDULING.md`: a ready-to-paste routine prompt, setup steps, how to tell it ran, and what happens when a deadline moves or a run is missed.
- `fpl_daily.py --calls-file`: skips a brief already written for the gameweek, and writes a late brief 1–6 hours before the deadline if the evening run was missed. Reports `brief_window_utc`.
- README: a table of what each install route gives (Claude app, Claude Code, scheduled routine).
- `--squad` accepts a pasted list (new lines or commas, with prices, clubs and numbering) and reports every name it can't match at once, with the closest names and ids.
- CI runs `ruff` alongside the tests.

**Evals** (#11)
- Skill evals on invented saved FPL data; `evals/README.md` explains them (#14).

**Track record** (#16, #17)
- `fpl_scorecard.py` scores past calls against real points: captain against the best starter, each transfer over three gameweeks, and whether the manager made it.
- `--record` keeps a call log; the brief records its call after publishing and shows a Track record table.

**Chip plan** (#15)
- `chip_plan` in the snapshot: every gameweek to the chip deadline with doubles, blanks, XI and bench difficulty, easy captain games, and unscheduled fixtures. Each player gets 4- and 6-gameweek fixture runs.
- The brief gives a provisional week for every remaining chip; the page shows them as a strip.

**Better decisions** (#12, #13, #14)
- The last gameweek is reviewed first: each blank is marked unlucky, poor form or running hot, from goals and assists against expected goal involvement.
- Rolling is the default transfer call. A move needs a named reason (red flag, poor form, clearly better), and the rules are checked in code.
- Team-news searches include the season and gameweek; one free expert source per blank.

**One design** (#12, #17)
- `render_brief.py` draws every brief the same way: your moves with confidence, the review, the XI on a pitch, form bars, chip plan, track record and sources. New README image.

## v1.2.1 (9 Nov 2026)
- The sample brief and image use real FPL data (#10).

## v1.2 (9 Nov 2026)
- Mini-league analysis leads with forward-looking gaps, shown as facts, plus an after-deadline view (#5–#7).
- README, sample brief, docs and image brought up to date (#4, #8, #9).

## v1.1.1 (9 Nov 2026)
- One daily routine instead of runs that schedule the next one (#3).

## v1.1 (9 Nov 2026)
- Mini-league pick analysis and daily price alerts (#2). Fix for the squad after a Free Hit, and the data the brief needs (#1).

## v1.0 (23 Oct 2026)
- First release: the skill and `fpl_snapshot.py`.
