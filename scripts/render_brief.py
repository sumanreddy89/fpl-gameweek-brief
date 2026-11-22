#!/usr/bin/env python3
"""Render the gameweek brief as one consistent, phone-first HTML page.

The agent decides; this script designs. The agent writes its decisions to a small JSON
file (see SKILL.md, "Write the brief"), and the numbers (fixtures, form, xGI, the last
gameweek) come from the fpl_snapshot.py output, so they are never retyped by hand.

    python3 scripts/render_brief.py --snapshot /tmp/snap.json --brief /tmp/brief.json --out /tmp/brief.html

Standard library only. Anything the brief names that isn't in the snapshot is shown
as "not in data" rather than invented.
"""

import argparse
import html
import json
import re
import sys

CONF = {"strong": ("Strong", 3), "lean": ("Lean", 2), "coin flip": ("Coin flip", 1)}
VERDICT_CHIP = [("unlucky", "Unlucky", "luck"), ("poor form", "Poor form", "poor"),
                ("running hot", "Running hot", "hot"), ("in line", "In line", "even"),
                ("too few", "Few minutes", "even"), ("not judged", "", "")]
POS_ORDER = ["GK", "DEF", "MID", "FWD"]


def esc(v):
    return html.escape("" if v is None else str(v))


def fixture_parts(text):
    """'GW12: ARS (A) 5' -> ('ARS (A)', 5). Blank gameweeks and odd strings pass through."""
    m = re.match(r"GW\d+:\s*(.*?)\s+(\d)$", text or "")
    return (m.group(1), int(m.group(2))) if m else ((text or "").split(": ", 1)[-1], None)


def verdict_chip(verdict):
    v = (verdict or "").lower()
    for key, label, cls in VERDICT_CHIP:
        if v.startswith(key):
            return f'<span class="chip {cls}">{esc(label)}</span>' if label else ""
    return ""


def conf_badge(level):
    label, n = CONF.get((level or "").lower(), ("", 0))
    if not label:
        return ""
    dots = "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(3))
    return f'<span class="conf" title="Confidence: {esc(label)}"><span class="dots" aria-hidden="true">{dots}</span>{esc(label)}</span>'


class Players:
    """Look players up by name across the squad and the transfer candidates."""

    def __init__(self, snap):
        self.rows = list(snap.get("squad") or [])
        for group in (snap.get("candidates") or {}).values():
            self.rows += group or []

    def get(self, name):
        n = (name or "").strip().lower()
        for r in self.rows:
            if r.get("name", "").lower() == n:
                return r
        for r in self.rows:
            if n and n in r.get("name", "").lower():
                return r
        return None


def token(p, name, role, flagged):
    if not p:
        return (f'<div class="tok missing"><span class="shirt">?</span><b>{esc(name)}</b>'
                f'<small>not in data</small></div>')
    fx, fdr = fixture_parts((p.get("fixtures") or [""])[0])
    badge = '<span class="arm">C</span>' if role == "C" else '<span class="arm v">V</span>' if role == "V" else ""
    flag = '<span class="flagdot" title="Flagged in this brief"></span>' if flagged else ""
    return (f'<div class="tok">{badge}{flag}<span class="shirt">{esc(p.get("club"))}</span>'
            f'<b>{esc(p.get("name"))}</b><small><span class="fdr f{fdr or 0}">{esc(fdr or "–")}</span> {esc(fx)}</small>'
            + (f'<small class="fm">form {esc(p.get("form"))}</small>' if p.get("form") is not None else "") + '</div>')


def render(snap, brief):
    players = Players(snap)
    team = snap.get("team") or {}
    gw = snap.get("next_gameweek")
    flagged = {(f.get("name") or "").lower() for f in brief.get("flags") or []}
    cap = (brief.get("captain") or {}).get("name", "").lower()
    vice = (brief.get("vice") or {}).get("name", "").lower()
    out = []
    a = out.append

    # ---- Header ----
    a('<header class="top"><div class="wrap">')
    a(f'<p class="eyebrow">{esc(team.get("name"))} · Gameweek {esc(gw)}</p>')
    a(f'<h1>{esc(brief.get("deadline_local") or snap.get("deadline_utc"))}</h1>')
    stats = [(team.get("overall_points"), "pts"),
             (f'{team["overall_rank"]:,}' if team.get("overall_rank") else None, "rank"),
             (f'£{snap["bank"]:.1f}m' if snap.get("bank") is not None else None, "bank"),
             (snap.get("free_transfers_estimate"), "free transfers (est.)"),
             (f'£{snap["team_value"]:.1f}m' if snap.get("team_value") else None, "team value")]
    left = [c["chip"] for c in snap.get("chips") or [] if c.get("available")]
    if snap.get("chips") is not None:
        stats.append((", ".join(left) if left else "none", "chips left"))
    a('<p class="statline">' + "".join(f'<span><b>{esc(v)}</b> {esc(l)}</span>' for v, l in stats if v is not None) + "</p>")
    if brief.get("written_note"):
        a(f'<p class="meta">{esc(brief["written_note"])}</p>')
    a("</div></header>")
    a('<main class="wrap">')

    # ---- Your moves ----
    a('<section class="moves" aria-labelledby="h-moves"><h2 id="h-moves">Your moves</h2>')
    if brief.get("headline"):
        a(f'<p class="headline">{esc(brief["headline"])}</p>')
    a('<ol class="decisions">')
    for t in brief.get("transfers") or []:
        a(f'<li><span class="k">Transfer</span><span class="v"><b>{esc(t.get("out"))}</b> <span class="arrow">→</span> <b>{esc(t.get("in"))}</b>'
          + (f' <span class="bank">bank £{float(t["bank_after"]):.1f}m after</span>' if t.get("bank_after") is not None else "")
          + f'</span>{conf_badge(t.get("confidence"))}</li>')
    if brief.get("roll"):
        a(f'<li><span class="k">Transfer</span><span class="v">{esc(brief["roll"])}</span>{conf_badge(brief.get("roll_confidence"))}</li>')
    for key, label in (("captain", "Captain"), ("vice", "Vice"), ("captain_alt", "Alt. captain")):
        c = brief.get(key) or {}
        if c.get("name"):
            a(f'<li><span class="k">{label}</span><span class="v"><b>{esc(c["name"])}</b>'
              + (f' <span class="why">{esc(c.get("why"))}</span>' if c.get("why") else "")
              + f'</span>{conf_badge(c.get("confidence"))}</li>')
    if brief.get("chip"):
        ch = brief["chip"]
        a(f'<li><span class="k">Chip</span><span class="v"><b>{esc(ch.get("call"))}</b>'
          + (f' <span class="why">{esc(ch.get("why"))}</span>' if ch.get("why") else "") + f'</span>{conf_badge(ch.get("confidence"))}</li>')
    a("</ol></section>")

    # ---- Last gameweek ----
    review = snap.get("last_gw_review")
    lg = brief.get("last_gw") or {}
    if review:
        a(f'<section aria-labelledby="h-last"><h2 id="h-last">Gameweek {esc(review.get("gw"))} review</h2>')
        c = review.get("captain")
        if c:
            xgi = c.get("xgi")
            pts = c.get("points")
            a('<div class="capcard">')
            a(f'<div class="capnum"><b>{esc(pts if pts is not None else "–")}</b><small>pts (×2 = {esc((pts or 0) * 2)})</small></div>')
            a(f'<div><p class="capname">Captain {esc(c.get("name"))} {verdict_chip(c.get("form_verdict"))}</p>')
            if xgi is not None:
                w = min(100, round(xgi / 2.0 * 100))
                a(f'<div class="xbar" role="img" aria-label="Expected goal involvement {xgi}"><span style="width:{w}%"></span></div>'
                  f'<p class="small">{esc(c.get("minutes"))} min · expected goal involvement <b>{xgi:.2f}</b></p>')
            if lg.get("captain_take"):
                a(f'<p>{esc(lg["captain_take"])}</p>')
            a("</div></div>")
        blanks = [b for b in review.get("blanks") or [] if not c or b.get("name") != c.get("name")]
        notes = {(n.get("name") or "").lower(): n.get("text") for n in lg.get("notes") or []}
        if blanks:
            a('<ul class="rows">')
            for b in blanks:
                xg = f' · xGI {b["xgi"]:.2f}' if b.get("xgi") is not None else ""
                a(f'<li><div class="r1"><b>{esc(b.get("name"))}</b> <span class="small">{esc(b.get("points"))} pts{esc(xg)}</span>{verdict_chip(b.get("form_verdict"))}</div>'
                  + (f'<p>{esc(notes[b["name"].lower()])}</p>' if notes.get(b.get("name", "").lower()) else "") + "</li>")
            a("</ul>")
        if lg.get("summary"):
            a(f'<p class="small">{esc(lg["summary"])}</p>')
        a("</section>")

    # ---- Pitch ----
    xi = brief.get("xi") or []
    if xi:
        rows = {k: [] for k in POS_ORDER}
        missing = []
        for name in xi:
            p = players.get(name)
            (rows[p["pos"]] if p and p.get("pos") in rows else missing).append((name, p))
        a(f'<section aria-labelledby="h-xi"><h2 id="h-xi">Starting XI'
          + (f' <span class="sub">{esc(brief.get("formation"))}</span>' if brief.get("formation") else "") + "</h2>")
        a('<div class="pitch" role="list" aria-label="Starting eleven by position">')
        for pos in reversed(POS_ORDER):
            if rows[pos]:
                a(f'<div class="line" role="listitem" aria-label="{pos}">')
                for name, p in rows[pos]:
                    role = "C" if name.lower() == cap else "V" if name.lower() == vice else ""
                    a(token(p, name, role, name.lower() in flagged))
                a("</div>")
        if missing:
            a('<div class="line">' + "".join(token(None, n, "", False) for n, _ in missing) + "</div>")
        a("</div>")
        bench = brief.get("bench") or []
        if bench:
            def bench_chip(i, n):
                p = players.get(n)
                fx, fdr = fixture_parts(((p or {}).get("fixtures") or [""])[0])
                extra = (f' <span class="fdr f{fdr or 0}">{esc(fdr or "–")}</span> <span class="small">{esc(fx)}</span>' if p else "")
                return f'<span class="bt"><i>{i}</i>{esc(n)}{extra}</span>'
            a('<div class="bench"><span class="k">Bench</span>' + "".join(
                bench_chip(i, n) for i, n in enumerate(bench, 1)) + "</div>")
        if brief.get("xi_note"):
            a(f'<p class="small">{esc(brief["xi_note"])}</p>')
        a("</section>")

    # ---- Form check: chances vs returns, last 4 ----
    attackers = []
    seen = set()
    for name in list(xi) + list(brief.get("bench") or []):
        p = players.get(name)
        if p and p.get("pos") in ("MID", "FWD") and p["name"] not in seen:
            u = (p.get("recent") or {}).get("underlying_last_4")
            if u:
                seen.add(p["name"])
                attackers.append((p, u))
    if attackers:
        top = max([u.get("xgi") or 0 for _, u in attackers] + [u.get("goals_assists") or 0 for _, u in attackers] + [1])
        a('<section aria-labelledby="h-form"><h2 id="h-form">Form check <span class="sub">last 4 matches</span></h2>')
        a('<p class="small legend"><span class="sw xg"></span> chances (xGI) <span class="sw ga"></span> goals + assists</p>')
        a('<ul class="form">')
        for p, u in attackers:
            xg, ga = u.get("xgi") or 0, u.get("goals_assists") or 0
            a(f'<li><span class="fn">{esc(p["name"])}</span>'
              f'<span class="bars" role="img" aria-label="xGI {xg}, goals plus assists {ga}">'
              f'<span class="b xg" style="width:{round(xg / top * 100)}%"></span>'
              f'<span class="b ga" style="width:{round(ga / top * 100)}%"></span></span>'
              f'<span class="fv">{xg:.1f} / {ga}</span>{verdict_chip(u.get("verdict"))}</li>')
        a("</ul></section>")

    # ---- Transfers detail ----
    if brief.get("transfers") or brief.get("transfer_note"):
        a('<section aria-labelledby="h-tr"><h2 id="h-tr">Transfers</h2>')
        for t in brief.get("transfers") or []:
            p = players.get(t.get("in"))
            fx = " · ".join("{} {}".format(*fixture_parts(f)) for f in (p or {}).get("fixtures", [])[:4])
            a(f'<article class="card"><p class="ct"><b>{esc(t.get("out"))}</b> → <b>{esc(t.get("in"))}</b>'
              + (f' <span class="small">£{p["price"]:.1f}m · {esc(p["club"])}</span>' if p else "") + f'{conf_badge(t.get("confidence"))}</p>'
              + (f'<p>{esc(t.get("why"))}</p>' if t.get("why") else "")
              + (f'<p class="small">Next: {esc(fx)}</p>' if fx else "")
              + (f'<p class="small">{esc(t.get("bank_math"))}</p>' if t.get("bank_math") else "") + "</article>")
        if brief.get("transfer_note"):
            a(f'<p class="small">{esc(brief["transfer_note"])}</p>')
        a("</section>")

    # ---- Flags, chips, price watch, leagues ----
    def bullets(title, hid, items, cls=""):
        if not items:
            return
        a(f'<section aria-labelledby="{hid}"><h2 id="{hid}">{esc(title)}</h2><ul class="rows {cls}">')
        for it in items:
            if isinstance(it, dict):
                a(f'<li><b>{esc(it.get("name"))}</b> {esc(it.get("text"))}</li>')
            else:
                a(f"<li>{esc(it)}</li>")
        a("</ul></section>")

    bullets("Squad flags", "h-flags", brief.get("flags"), "flags")
    if brief.get("chip") and brief["chip"].get("detail"):
        bullets("Chips", "h-chips", [brief["chip"]["detail"]])
    bullets("Price watch", "h-price", brief.get("price_watch"))
    bullets("Mini-leagues", "h-leagues", brief.get("leagues"))

    # ---- Confidence, sources, closing ----
    a('<section class="foot" aria-labelledby="h-src"><h2 id="h-src">Confidence and sources</h2>')
    if brief.get("confidence_note"):
        a(f"<p>{esc(brief['confidence_note'])}</p>")
    gaps = list(snap.get("data_gaps") or [])
    if gaps:
        a('<p class="small">Data gaps: ' + esc(" ".join(gaps)) + "</p>")
    srcs = brief.get("sources") or []
    if srcs:
        a('<ul class="src">')
        for s in srcs:
            label = esc(s.get("label"))
            url = s.get("url") or ""
            if url.startswith("https://"):
                label = f'<a href="{esc(url)}" target="_blank" rel="noopener">{label}</a>'
            a(f'<li>{label}' + (f' <span class="small">· {esc(s.get("date"))}</span>' if s.get("date") else "") + "</li>")
        a("</ul>")
    a("</section>")
    a('<p class="end">Reply in a chat with what you want to go with, and I\'ll help make the changes.</p>')
    a("</main>")

    title = f'{team.get("name") or "FPL"} GW{gw} Brief'
    return PAGE.replace("{{TITLE}}", esc(title)).replace("{{BODY}}", "\n".join(out))


PAGE = """<title>{{TITLE}}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700;800&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
/* Layout: matchday programme. A floodlit header with the deadline, the decisions as one
   card, then the evidence: last gameweek, a chalk tactics board, form bars, detail. */
:root {
  --bg: #f3f4ef; --surface: #ffffff; --ink: #14201b; --muted: #5d6b64; --line: #dde2db;
  --night: #0f2a22; --night-ink: #eaf3ee; --night-muted: #a9c2b6;
  --accent: #157a55; --accent-soft: #dcefe6;
  --luck: #1d5fb8; --luck-soft: #e1ebf8; --poor: #b23a24; --poor-soft: #f8e3de; --hot: #9a6a00; --hot-soft: #f7edd2;
  --grass-1: #2f7d4f; --grass-2: #2a7247; --chalk: rgba(255,255,255,.55);
  --f1: #1f8a5b; --f2: #5cb87f; --f3: #c9ced0; --f4: #e0835e; --f5: #b23a24;
  --display: "Saira Condensed", "Arial Narrow", system-ui, sans-serif;
  --body: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0d1412; --surface: #16201c; --ink: #e5eee9; --muted: #98aaa1; --line: #26332d;
  --night: #0a1d17; --night-ink: #eaf3ee; --night-muted: #93b0a2;
  --accent: #4fc792; --accent-soft: #163428;
  --luck: #7fb0f2; --luck-soft: #17263c; --poor: #f09482; --poor-soft: #3a1c16; --hot: #e6c068; --hot-soft: #352a10;
  --grass-1: #23603d; --grass-2: #1f5737; --f3: #6e7a76; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0d1412; --surface: #16201c; --ink: #e5eee9; --muted: #98aaa1; --line: #26332d;
  --night: #0a1d17; --night-ink: #eaf3ee; --night-muted: #93b0a2;
  --accent: #4fc792; --accent-soft: #163428;
  --luck: #7fb0f2; --luck-soft: #17263c; --poor: #f09482; --poor-soft: #3a1c16; --hot: #e6c068; --hot-soft: #352a10;
  --grass-1: #23603d; --grass-2: #1f5737; --f3: #6e7a76; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }
.wrap { max-width: 680px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main.wrap { display: grid; gap: 30px; padding-block: 22px 48px; }
h1, h2 { font-family: var(--display); margin: 0; text-wrap: balance; }
h2 { font-size: 15px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; display: flex; align-items: baseline; gap: 8px; }
h2 .sub { font: 500 12px var(--body); letter-spacing: 0; text-transform: none; }
p { margin: 0 0 8px; }
.small { font-size: 13px; color: var(--muted); }
a { color: var(--accent); }
section { min-width: 0; }

.top { background: var(--night); color: var(--night-ink); padding-block: 22px 52px;
  background-image: radial-gradient(120% 90% at 85% -20%, rgba(255,255,255,.10), transparent 60%); }
.eyebrow { font: 600 12px var(--body); letter-spacing: .1em; text-transform: uppercase; color: var(--night-muted); margin: 0 0 6px; }
.top h1 { font-size: clamp(30px, 8vw, 40px); font-weight: 800; line-height: 1.02; letter-spacing: -.01em; }
.statline { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 12px 0 0; font-size: 13.5px; color: var(--night-muted); }
.statline b { color: var(--night-ink); font-family: var(--mono); font-weight: 500; font-variant-numeric: tabular-nums; }
.meta { font-size: 12.5px; color: var(--night-muted); margin: 8px 0 0; }

.moves { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-top: -34px; box-shadow: 0 10px 30px -18px rgba(0,0,0,.35); }
.headline { font-size: 17px; font-weight: 600; line-height: 1.4; margin-bottom: 12px; }
.decisions { list-style: none; margin: 0; padding: 0; display: grid; }
.decisions li { display: grid; grid-template-columns: 74px minmax(0,1fr) auto; gap: 4px 10px; align-items: baseline; padding: 10px 0; border-top: 1px solid var(--line); }
.decisions .k { font: 700 12px var(--display); letter-spacing: .12em; text-transform: uppercase; color: var(--accent); }
.decisions .v { min-width: 0; overflow-wrap: anywhere; }
.decisions .why { display: block; font-size: 13.5px; color: var(--muted); }
.arrow { color: var(--accent); font-weight: 700; }
.bank { font: 500 12px var(--mono); color: var(--muted); white-space: nowrap; }
.conf { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); white-space: nowrap; }
.dots { display: inline-flex; gap: 2px; }
.dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--line); }
.dots i.on { background: var(--accent); }
@media (max-width: 420px) { .decisions li { grid-template-columns: 66px minmax(0,1fr); } .decisions .conf { grid-column: 2; } }

.capcard { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px; margin-bottom: 10px; }
.capnum b { display: block; font: 800 44px/1 var(--display); font-variant-numeric: tabular-nums; }
.capnum small { font-size: 11.5px; color: var(--muted); }
.capname { font-weight: 600; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.xbar { height: 8px; border-radius: 99px; background: var(--line); overflow: hidden; margin: 4px 0 6px; max-width: 320px; }
.xbar span { display: block; height: 100%; background: var(--luck); border-radius: 99px; }

.chip { display: inline-block; font: 600 11.5px var(--body); padding: 1px 8px; border-radius: 99px; white-space: nowrap; }
.chip.luck { background: var(--luck-soft); color: var(--luck); }
.chip.poor { background: var(--poor-soft); color: var(--poor); }
.chip.hot { background: var(--hot-soft); color: var(--hot); }
.chip.even { background: var(--line); color: var(--muted); }

.rows { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.rows li { padding: 11px 14px; border-top: 1px solid var(--line); }
.rows li:first-child { border-top: 0; }
.rows .r1 { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.rows p { margin: 4px 0 0; font-size: 14px; }
.rows.flags li { border-left: 3px solid var(--hot); }

.pitch { border-radius: 14px; padding: 18px 8px; display: grid; gap: 16px;
  background:
    linear-gradient(var(--chalk), var(--chalk)) center 50% / 100% 1.5px no-repeat,
    radial-gradient(circle at 50% 50%, transparent 0 46px, var(--chalk) 46px 47.5px, transparent 48px),
    repeating-linear-gradient(180deg, var(--grass-1) 0 44px, var(--grass-2) 44px 88px); }
.line { display: flex; justify-content: center; gap: 6px; flex-wrap: wrap; }
.tok { position: relative; width: 84px; display: grid; justify-items: center; gap: 2px; text-align: center; color: #fff; }
.tok .shirt { width: 38px; height: 38px; border-radius: 50%; background: rgba(255,255,255,.95); color: #12261d; display: grid; place-items: center; font: 700 12px var(--display); letter-spacing: .04em; box-shadow: 0 2px 6px rgba(0,0,0,.25); }
.tok b { font-size: 12px; font-weight: 600; line-height: 1.2; background: rgba(8,25,18,.72); padding: 1px 6px; border-radius: 4px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tok small { font-size: 10.5px; color: rgba(255,255,255,.9); display: inline-flex; gap: 3px; align-items: center; white-space: nowrap; }
.tok .fm { font: 500 10px var(--mono); color: rgba(255,255,255,.8); }
.tok.missing .shirt { background: rgba(255,255,255,.4); }
.arm { position: absolute; top: -4px; left: calc(50% + 10px); width: 18px; height: 18px; border-radius: 50%; background: #111; color: #fff; font: 700 10px/18px var(--body); text-align: center; z-index: 1; border: 1.5px solid #fff; }
.arm.v { background: #fff; color: #111; border-color: #111; }
.flagdot { position: absolute; top: -2px; left: calc(50% - 22px); width: 10px; height: 10px; border-radius: 50%; background: #f2b12f; border: 1.5px solid #fff; }
.fdr { display: inline-block; min-width: 15px; padding: 0 3px; border-radius: 3px; font: 600 10px/14px var(--mono); color: #10201a; background: var(--f3); }
.fdr.f1 { background: var(--f1); color: #fff; } .fdr.f2 { background: var(--f2); } .fdr.f4 { background: var(--f4); } .fdr.f5 { background: var(--f5); color: #fff; }
.bench { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 10px 0 6px; font-size: 13.5px; }
.bench .k { font: 700 12px var(--display); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-right: 4px; }
.bt { background: var(--surface); border: 1px solid var(--line); border-radius: 99px; padding: 2px 10px 2px 4px; display: inline-flex; gap: 6px; align-items: center; }
.bt i { font: 500 11px var(--mono); font-style: normal; width: 18px; height: 18px; border-radius: 50%; background: var(--line); display: grid; place-items: center; }

.legend { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.sw { width: 12px; height: 8px; border-radius: 2px; display: inline-block; }
.sw.xg, .b.xg { background: var(--luck); } .sw.ga, .b.ga { background: var(--accent); }
.form { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.form li { display: grid; grid-template-columns: 96px minmax(0,1fr) 56px auto; gap: 10px; align-items: center; font-size: 14px; }
.fn { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bars { display: grid; gap: 3px; }
.b { display: block; height: 7px; border-radius: 99px; min-width: 2px; }
.fv { font: 500 12px var(--mono); color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
@media (max-width: 420px) { .form li { grid-template-columns: 80px minmax(0,1fr) 48px; } .form .chip { grid-column: 2 / -1; justify-self: start; } }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; }
.card .ct { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
.card .conf { margin-left: auto; }
.foot p { font-size: 14px; }
.src { margin: 6px 0 0; padding-left: 18px; font-size: 13.5px; }
.end { font-weight: 600; border-top: 1px solid var(--line); padding-top: 16px; }
</style>
<header></header>
{{BODY}}
"""
PAGE = PAGE.replace("<header></header>\n", "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.snapshot, encoding="utf-8") as f:
        snap = json.load(f)
    with open(args.brief, encoding="utf-8") as f:
        brief = json.load(f)
    page = render(snap, brief)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {args.out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
