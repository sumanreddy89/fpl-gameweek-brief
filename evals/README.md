# Evals

These check that an agent following `SKILL.md` behaves the way the skill promises. The unit tests in `tests/` check the scripts. Each case gives an agent a prompt and saved FPL data, then graders read what the agent did and wrote.

All data is invented: `tests/make_eval_fixture.py` builds a saved copy of the FPL API with made-up clubs and players, and each case's `place-files.sh` puts it where the agent can read it. Nothing reaches the real FPL site.

## The cases

| Case | What it checks |
|---|---|
| `full-brief-injured-starter` | A full brief in the SKILL.md order: flags the injured, doubtful and rotation-risk players, transfer options with the bank sum, a valid XI and bench, captain and vice, the deadline in local time, no invented team news, and the closing line. |
| `midweek-transfer-already-made` | The manager has already made a transfer: the agent uses the updated squad, the manager's bank and one free transfer left. |
| `public-mini-league-writeup` | A public post from `fpl_leagues.py`: explains gains and losses by position and keeps rival team names out. |
| `unattended-missing-team-id` | No team ID and nobody to ask: the run stops and says so, without guessing an ID or inventing a squad. |

Each case folder has `case.yaml` (what a good outcome looks like), `prompt.md` (what the agent is asked), `place-files.sh` (sets up the data) and `graders/` (one file per check, graded by a model reading the run).

## Running them

From the repository root, with Claude Code installed:

```bash
claude plugin eval
```

`claude plugin eval --help` lists the options, such as running one case. Results land in `evals/results/<timestamp>/` as `aggregate-result.json` and a `report.html` you can open in a browser. The suite compares runs with and without the skill installed.

Each case runs a real agent, so a full run costs money and takes several minutes. Each run's cost and duration are recorded in its `aggregate-result.json`. The run saved in `evals/results/` (10 Nov 2026) was stopped before every case finished.

## What they don't check

They check format and rule-following, not whether the advice was right. Whether past briefs' calls worked out needs the actual points from the following gameweek, which these saved fixtures don't have.
