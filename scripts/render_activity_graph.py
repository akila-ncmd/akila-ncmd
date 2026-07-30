#!/usr/bin/env python3
"""Render the contribution activity graph as a self-contained SVG.

Replaces the github-readme-activity-graph.vercel.app embed. Two reasons:

1. That service prints no contribution values. It emits axis labels only and
   zero <title> nodes, so the counts were not readable and there was nothing
   for a tooltip to show even in principle.

2. Committing the result removes a third-party host from the page-view path.

ON HOVER
GitHub serves README images through its camo proxy inside an <img>, which
makes the SVG's internal DOM inert - no :hover, no <title> tooltips, no
script. Real hover is therefore impossible in a profile README no matter
which service renders the graph. So this card stays deliberately clean (no
per-point labels, --labels is opt-in) and links to docs/index.html, published
on GitHub Pages, where the same data IS hoverable. --data-out writes the JSON
that page reads.

Contribution data comes from github-contributions-api.jogruber.de, which needs
no auth. The GitHub GraphQL contributionsCollection query was not used on
purpose: the workflow note in profile-summary-cards.yml records that the
default GITHUB_TOKEN lacks the user-level scopes those queries need.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date

API = "https://github-contributions-api.jogruber.de/v4/{user}?y=last"

# Matches the README's red-on-near-black theme.
BG = "#0A0A0A"
ACCENT = "#FF0000"
POINT = "#ffffff"
LABEL = "#ffffff"

W, H = 1200, 420
PAD_L, PAD_R = 78, 34
PAD_T, PAD_B = 92, 62

RETRIES = 4
TIMEOUT = 20


def fetch_contributions(user: str) -> list[dict]:
    """Return the raw daily contribution list, retrying transient failures."""
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                API.format(user=user),
                headers={"User-Agent": f"{user}-profile-readme"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                payload = json.load(resp)
            days = payload.get("contributions")
            if not days:
                raise RuntimeError("response contained no contributions array")
            return days
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as err:
            last_err = err
            print(f"attempt {attempt}/{RETRIES} failed: {err}", file=sys.stderr)
    raise SystemExit(f"could not fetch contributions for {user}: {last_err}")


def recent(days: list[dict], window: int) -> list[dict]:
    """Last `window` days up to and including today, oldest first."""
    today = date.today().isoformat()
    past = [d for d in days if d["date"] <= today]
    if not past:
        raise SystemExit("no contribution days at or before today")
    return past[-window:]


def nice_ceiling(value: int) -> int:
    """Round an axis maximum up to something that divides evenly."""
    if value <= 5:
        return 5
    for step in (5, 10, 25, 50, 100, 250, 500):
        if value <= step * 7:
            return -(-value // step) * step
    return -(-value // 1000) * 1000


def build_svg(user_label: str, days: list[dict], labels: bool, hover_url: str | None) -> str:
    counts = [d["count"] for d in days]
    top = nice_ceiling(max(counts))

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    step = plot_w / (len(days) - 1) if len(days) > 1 else 0

    def x_at(i: int) -> float:
        return PAD_L + i * step

    def y_at(count: int) -> float:
        return PAD_T + plot_h - (count / top) * plot_h

    pts = [(x_at(i), y_at(c)) for i, c in enumerate(counts)]

    out: list[str] = []
    add = out.append

    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="{user_label} contribution graph, last {len(days)} days">'
    )
    add(
        "<style>"
        f".ttl{{font:700 22px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:{ACCENT}}}"
        f".ax{{font:700 12px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:{ACCENT}}}"
        f".val{{font:700 12px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:{LABEL}}}"
        f".cap{{font:600 11px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:{ACCENT};opacity:.65}}"
        "</style>"
    )

    # Opaque background so the card reads the same on GitHub light and dark.
    add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
    add(
        f'<text x="{W / 2:.1f}" y="42" class="ttl" text-anchor="middle">'
        f"{user_label}&#39;s Contribution Graph</text>"
    )

    # Horizontal gridlines + y axis ticks.
    rows = 5
    for r in range(rows + 1):
        val = round(top * r / rows)
        gy = y_at(val)
        add(
            f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" '
            f'stroke="{ACCENT}" stroke-opacity="0.18" stroke-width="1" '
            f'stroke-dasharray="3 4"/>'
        )
        add(
            f'<text x="{PAD_L - 12}" y="{gy + 4:.1f}" class="ax" '
            f'text-anchor="end">{val}</text>'
        )

    # Area fill under the line.
    area = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    base = PAD_T + plot_h
    add(
        f'<polygon points="{PAD_L:.1f},{base:.1f} {area} '
        f'{PAD_L + plot_w:.1f},{base:.1f}" fill="{ACCENT}" fill-opacity="0.14"/>'
    )

    # The line itself.
    add(
        f'<polyline points="{area}" fill="none" stroke="{ACCENT}" '
        f'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # Points, day labels, and the always-visible counts.
    for i, ((px, py), count) in enumerate(zip(pts, counts)):
        add(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.6" fill="{POINT}"/>')

        day = days[i]["date"][8:10].lstrip("0") or "0"
        add(
            f'<text x="{px:.1f}" y="{base + 22:.1f}" class="ax" '
            f'text-anchor="middle">{day}</text>'
        )

        if labels:
            # Nudge the label below the point when it would clip the title band.
            ly = py - 12 if py - 12 > PAD_T - 4 else py + 20
            add(
                f'<text x="{px:.1f}" y="{ly:.1f}" class="val" '
                f'text-anchor="middle">{count}</text>'
            )

    total = sum(counts)
    caption = f"Days &#183; {total} contributions in the last {len(days)} days"
    if hover_url:
        # Hover cannot fire inside a README (see module docstring), so point
        # readers at the page where it can.
        caption += " &#183; click for per-day values"
    add(
        f'<text x="{W / 2:.1f}" y="{H - 16}" class="cap" text-anchor="middle">'
        f"{caption}</text>"
    )
    add("</svg>")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--label", default=None, help="name shown in the title")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--labels",
        action="store_true",
        help="print each day's count on the graph (off by default - the "
        "README card is kept clean and links to the hover page instead)",
    )
    ap.add_argument(
        "--hover-url",
        default=None,
        help="if set, the caption invites the reader to click through",
    )
    ap.add_argument(
        "--data-out",
        default=None,
        help="also write the windowed data as JSON, for the hover page",
    )
    args = ap.parse_args()

    if args.days < 2:
        raise SystemExit("--days must be at least 2")

    days = recent(fetch_contributions(args.user), args.days)
    svg = build_svg(args.label or args.user, days, args.labels, args.hover_url)

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg + "\n")

    shown = sum(d["count"] for d in days)
    print(f"wrote {args.out}: {len(days)} days, {shown} contributions")

    if args.data_out:
        payload = {
            "user": args.user,
            "label": args.label or args.user,
            "generated": date.today().isoformat(),
            "total": shown,
            "days": [{"d": d["date"], "c": d["count"]} for d in days],
        }
        with open(args.data_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, separators=(",", ":"))
            fh.write("\n")
        print(f"wrote {args.data_out}: {len(days)} days")


if __name__ == "__main__":
    main()
