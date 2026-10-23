# FPL Gameweek Brief

An agent skill that prepares a Fantasy Premier League brief before each gameweek deadline. Give it your FPL team ID. It returns:

- **Squad flags:** injuries, suspensions, doubts and players losing minutes, each with a dated source
- **Transfer options:** one to three moves that fit your bank and free transfers, plus whether to roll or take a hit
- **Captain and vice-captain picks,** with one alternative
- **A starting XI and bench order** that works with the auto-sub rules
- **Chip timing and a price-change watch**

The skill only recommends. It never signs in to FPL or changes your team.

## What's inside

```
fpl-gameweek-brief/
├── SKILL.md                 # instructions the agent follows
└── scripts/
    └── fpl_snapshot.py      # pulls and trims the public FPL data (Python 3, standard library only)
```

`fpl_snapshot.py` exists because FPL's main data file is several megabytes, which is too big for most agents to read whole. The script cuts it down to about 20 KB: your squad, fixtures, chips, an estimate of your free transfers, blank and double gameweeks, and the top-projected players in each position.

```bash
python3 scripts/fpl_snapshot.py --team-id 1234567
```

Useful options:

| Option | What it does |
|---|---|
| `--squad "Raya,Saka,..."` | Uses these 15 players instead of the public squad, which is needed after mid-week transfers |
| `--bank 1.5` | Sets the bank (in £m) to go with `--squad` |
| `--horizon 4` | How many gameweeks of fixtures to show |
| `--candidates 6` | How many transfer candidates to list per position |
| `--min-minutes 450` | Leaves out candidates with fewer season minutes than this, so one big game doesn't top the list |
| `--data-dir DIR` | Reads saved JSON files instead of the live API, for offline testing |

## Install

The skill uses the open Agent Skills layout: a folder containing a `SKILL.md`.

- **Claude:** upload the folder as a skill in Settings → Capabilities, or copy it into `~/.claude/skills/` for Claude Code.
- **Other agents** that support the same format: put the folder wherever that agent loads skills from.

Then ask something like *"Prep my FPL team for the next gameweek. My team ID is 1234567."*

## Finding your team ID

Open the FPL website, go to **Points**, and copy the number from the address bar:
`fantasy.premierleague.com/entry/`**`1234567`**`/event/8`

## Limits

- **Recent transfers aren't visible.** FPL only publishes a squad after each deadline, so transfers made since the last one won't appear. Tell the agent your current 15 players, or share a screenshot of your Pick Team screen.
- **Free transfers are an estimate,** based on the current rules (+1 each gameweek, a maximum of 5, and none used on Wildcard or Free Hit weeks). Check the number in the app.
- **Some sandboxes block the FPL site.** The skill falls back to a browser tool or to smaller endpoints when that happens.

## Disclaimer

This is an unofficial, fan-made project. It is not affiliated with or endorsed by the Premier League or Fantasy Premier League. It uses undocumented public endpoints, which can change without notice. It reads data at run time for your own personal use, and this repository does not redistribute any FPL data. Check Fantasy Premier League's terms and conditions, linked from the FPL site, before using it for anything beyond managing your own team.

## License

MIT, see [LICENSE](LICENSE).
