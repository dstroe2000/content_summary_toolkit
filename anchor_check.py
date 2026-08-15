#!/usr/bin/env python3
"""Flag drifted [HH:MM:SS] heading anchors in vault notes, against their subtitle.

Catches three mechanical defects seen in already-ingested notes:
  PAST-END      a heading claims [00:28:00] in a 20-minute video
  OUT-OF-ORDER  anchors that go backwards
  DRIFT         a heading claims [00:28:00] but its content is at [00:16:52]

DRIFT is triage, not a verdict: a topic restated in a recap can outscore its
first mention. Flags are for a human or an agent to adjudicate against the srt.

Usage:
    anchor_check.py <note.md> [<note.md> ...]
    anchor_check.py --selftest

Subtitles are looked up by note basename in SUBTITLE_DIR.
Exit code 1 if any note has findings.
"""
import re
import sys
import pathlib

SUBTITLE_DIR = pathlib.Path(
    "/Users/danielstroe/work/content_summary_toolkit/output/subtitle"
)
LEAD = 15      # a heading may be stated slightly before its topic starts
WINDOW = 75    # ...and the topic may run this long after
TOLERANCE = 90 # drift forgiven before we call it wrong
MIN_HITS = 2   # fewer distinct keyword hits than this = unverifiable, not wrong

STOP = set(
    "this that with what have from they them their your yours will just like "
    "into more than then when your about which some very much most other than "
    "does done here there where were been being over under also only such each "
    "these those because while after before both same want need make made goes "
    "part step case time thing things really actually going gonna okay yeah".split()
)

# Headings use [HH:MM:SS], but ingests also emit bare [MM:SS] — which the strict
# three-field pattern skipped entirely, hiding those anchors from every check.
TS = re.compile(r"\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]")
HEAD = re.compile(r"^#{1,6}\s+(.*)$")
FENCE = re.compile(r"^\s*```")
WORD = re.compile(r"[a-z][a-z0-9.\-]{3,}")


def to_secs(h, m, s):
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def fmt(sec):
    return f"[{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}]"


def keywords(text):
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


def load_subtitle(path):
    """-> (list[(secs, lowercased text)], duration_secs)"""
    lines = []
    for raw in path.read_text(errors="replace").splitlines():
        m = TS.match(raw.strip())
        if m:
            lines.append((to_secs(*m.groups()), raw[m.end():].strip().lower()))
    return lines, (lines[-1][0] if lines else 0)


def index_keywords(sub_lines):
    """keyword -> sorted list of seconds where it occurs."""
    idx = {}
    for sec, text in sub_lines:
        for w in keywords(text):
            idx.setdefault(w, []).append(sec)
    for w in idx:
        idx[w] = sorted(set(idx[w]))
    return idx


def score_at(kws, idx, t):
    """How many distinct keywords occur in the window anchored at t."""
    lo, hi = t - LEAD, t + WINDOW
    return sum(1 for w in kws if w in idx and any(lo <= s <= hi for s in idx[w]))


def best_window(kws, idx, duration, step=15, lo=0, hi=None):
    """Best-scoring window in [lo, hi]. Bounding it to the surrounding anchors is
    what keeps a repair from landing 'Framework 2' before 'Framework 1'."""
    hi = duration if hi is None else min(hi, duration)
    best_t, best_n = lo, 0
    for t in range(lo, hi + 1, step):
        n = score_at(kws, idx, t)
        if n > best_n:
            best_t, best_n = t, n
    return best_t, best_n


def note_anchors(text):
    """Anchored headings, outside code fences -> [(lineno, secs, heading, restart)].

    `restart` marks an anchor that opens a new timeline block. Some notes hold two
    independent summaries of the same video, so the second legitimately walks back to
    00:00:00; without this, whole-file monotonicity reports the whole block as
    OUT-OF-ORDER. An unanchored H1 is the block boundary — an H1 that carries its own
    timestamp is part of the timeline, not a new one.
    """
    out, in_fence, restart = [], False, False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = HEAD.match(line)
        if not h:
            continue
        m = TS.search(h.group(1))
        if not m:
            if line.startswith("# "):
                restart = True
            continue
        out.append((i, to_secs(*m.groups()), TS.sub("", h.group(1)).strip(), restart))
        restart = False
    return out



def check(note_path):
    note = pathlib.Path(note_path)
    sub = SUBTITLE_DIR / (note.stem + ".txt")
    if not sub.exists():
        return [f"SKIP  no subtitle at {sub}"]

    text = note.read_text(errors="replace")
    sub_lines, duration = load_subtitle(sub)
    if not sub_lines:
        return [f"SKIP  subtitle has no [HH:MM:SS] anchors: {sub}"]
    idx = index_keywords(sub_lines)

    findings = []
    anchors = note_anchors(text)

    prev = -1
    for lineno, sec, heading, restart in anchors:
        if restart:
            prev = -1          # new timeline block; ordering restarts here
        if sec > duration + 30:
            findings.append(
                f"L{lineno}  PAST-END {fmt(sec)} > video {fmt(duration)}  — {heading}"
            )
        if sec < prev:
            findings.append(f"L{lineno}  OUT-OF-ORDER {fmt(sec)} after {fmt(prev)}  — {heading}")
        prev = max(prev, sec)

        kws = keywords(heading)
        if len(kws) < MIN_HITS:
            continue
        here = score_at(kws, idx, sec)
        best_t, best_n = best_window(kws, idx, duration)
        if best_n < MIN_HITS:
            continue  # heading is paraphrase, not transcript wording — can't judge
        # margin, not just ">": a topic recapped later must not outvote its first mention
        if here + 2 <= best_n and abs(best_t - sec) > TOLERANCE:
            findings.append(
                f"L{lineno}  DRIFT claimed {fmt(sec)} (match {here}/{len(kws)}), "
                f"content at {fmt(best_t)} (match {best_n}/{len(kws)})  — {heading}"
            )

    # ponytail: detection only, no --fix. Tried auto-repair by best keyword window:
    # unbounded it put "Framework 2" before "Framework 1"; bounded to the neighbouring
    # anchors it collapsed Frameworks 1/2/3 onto one timestamp. Generic headings do not
    # localise by keyword. Repair is an agent pass against the srt.
    #
    # No chart-number check here either. Tried it; the transcript says "$1.32 at
    # peak" and the chart legitimately plots 132 cents, so string matching flags
    # correct unit conversions as fabrications. Judging that needs a model — it lives
    # in the tier-2 agent pass, not in this script.
    return findings or [f"OK    {len(anchors)} anchors, 0 findings"]


def selftest():
    idx = {"neural": [10, 12], "engine": [10, 14], "cooling": [600]}
    assert score_at({"neural", "engine"}, idx, 10) == 2
    assert score_at({"neural", "engine"}, idx, 600) == 0
    assert best_window({"cooling"}, idx, 700)[0] == 525  # earliest window covering 600

    md = "## [00:01:00] Real\n```mermaid\n## [00:09:09] fenced, ignored\n```\n"
    assert note_anchors(md) == [(1, 60, "Real", False)]
    assert note_anchors("### [04:58] Two-field\n") == [(1, 298, "Two-field", False)]

    # a second summary block restarting at 00:00 is not OUT-OF-ORDER
    two = "## [00:10:00] A\n# Second Summary\n## [00:00:30] B\n"
    assert [a[3] for a in note_anchors(two)] == [False, True]


    print("selftest ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        selftest()
        sys.exit(0)
    if not args:
        sys.exit(__doc__)
    bad = False
    for p in args:
        out = check(p)
        if all(l.startswith("OK") for l in out):
            continue          # quiet on clean notes; the vault is 21k files
        print(f"\n=== {pathlib.Path(p).name}")
        for line in out:
            print("  " + line)
            bad |= not line.startswith(("OK", "SKIP"))
    sys.exit(1 if bad else 0)
