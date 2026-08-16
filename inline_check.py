#!/usr/bin/env python3
"""Flag (and mechanically repair) drifted [HH:MM:SS] timestamps that sit INLINE.

anchor_check.py only sees heading anchors. Ingests also stamp bullets and prose,
and those stamps drift the same way — but nothing checked them. This does.

The lever is the two-sided bracket: an inline stamp must fall between its
enclosing heading's anchor and the next heading's anchor. Heading anchors were
repaired in vault commit 78e3d698 and are trusted here. That bracket turns most
repairs from a guess into arithmetic: reinterpret the field shift, keep the
reading that lands inside the bracket, and only that reading.

Usage:
    inline_check.py --scan <note.md> ...        report broken inline stamps
    inline_check.py --fix  <note.md> ...        apply mechanical repairs in place
    inline_check.py --selftest
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from anchor_check import (  # noqa: E402
    TS, HEAD, FENCE, TOLERANCE, MIN_HITS, to_secs, fmt, load_subtitle,
    note_anchors, subtitle_for, keywords, index_keywords, score_at, best_window,
)

SLACK = 30      # a stamp may sit slightly outside its bracket and still be right
TABLE = re.compile(r"^\s*\|")


def inline_stamps(text, anchors):
    """-> [(lineno, col, raw, secs, sect, lo, hi, in_table)] for non-heading stamps.

    lo/hi are the enclosing heading anchors: the bracket a repair must land in.
    `sect` is the enclosing heading's line — ANY heading, anchored or not, since
    a citation under an unanchored "## Conclusion" belongs to that block and not
    to the anchored heading three sections up.

    lo is only set when the immediately enclosing heading is itself anchored.
    Inheriting an anchor across an unanchored heading is how a legitimate
    "the speaker concludes, see [00:11:42]" gets mistaken for corruption.
    """
    heads = sorted((a[0], a[1]) for a in anchors)
    anchored = {ln: s for ln, s in heads}
    out, in_fence, sect = [], False, 0
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEAD.match(line):
            sect = i
            continue
        prev = anchored.get(sect)
        nxt = min((s for ln, s in heads if ln > i), default=None)
        for m in TS.finditer(line):
            out.append((i, m.start(), m.group(0), to_secs(*m.groups()),
                        sect, prev, nxt, bool(TABLE.match(line))))
    return out


def recap_sections(stamps, duration):
    """Sections whose stamps replay the whole video instead of following it.

    A "Key Takeaways" list at the end of a note cites [00:00:28] under a heading
    anchored at [00:22:50]. That is not corruption, and the bracket rule would
    "repair" every one of them into nonsense. Signature: two or more in-video
    stamps, in order, inside one section.
    """
    by_sect = {}
    for s in stamps:
        by_sect.setdefault(s[4], []).append(s)
    out = set()
    for sect, group in by_sect.items():
        vals = [g[3] for g in sorted(group)]
        if (len(vals) >= 2 and vals == sorted(vals)
                and all(v <= duration + SLACK for v in vals)):
            out.add(sect)
    return out


def is_broken(secs, lo, duration):
    if secs > duration + SLACK:
        return "PAST-END"
    if lo is not None and secs < lo - SLACK:
        return "BEFORE-HEADING"
    return None


def candidates(raw, secs):
    """Reinterpretations of a corrupted stamp, as (label, seconds)."""
    m = TS.match(raw)
    h, mm, ss = m.groups()
    out = []
    if h is None:                       # bare [MM:SS] — maybe it meant HH:MM
        out.append(("read-as-HH:MM", int(mm) * 3600 + int(ss) * 60))
        return out
    h, mm, ss = int(h), int(mm), int(ss)
    if ss == 0:                         # [28:14:00] = 28m14s written into HH:MM
        out.append(("field-shift", h * 60 + mm))
    if h == 0:                          # [00:HH:MM] = HH:MM:SS shifted left
        out.append(("left-shift", mm * 3600 + ss * 60))
    if h:                               # spurious hour digit on a good MM:SS
        out.append(("drop-hour", mm * 60 + ss))
        out.append(("minus-1h", secs - 3600))
    return out


def repair(raw, secs, lo, hi, duration):
    """-> (label, seconds) if exactly one reinterpretation lands in the bracket."""
    a = 0 if lo is None else lo - SLACK
    b = min(duration + SLACK, (duration if hi is None else hi) + SLACK)
    hits = {v: lab for lab, v in candidates(raw, secs)
            if a <= v <= b and v != secs and v >= 0}
    if len(hits) != 1:
        return None                     # 0 = no reading fits, 2+ = ambiguous
    v, lab = next(iter(hits.items()))
    return lab, v


def contradicted(line, v, idx, lo, hi, duration):
    """True if the bullet's own words say the content is somewhere else.

    A field shift can be arithmetically clean and still wrong. Score the bullet's
    keywords at the proposed second against the best-scoring window inside the
    same bracket; a clear loss means a human/agent should adjudicate, not a regex.
    """
    kws = keywords(TS.sub("", line))
    if len(kws) < MIN_HITS:
        return False                     # nothing to judge with, keep the arithmetic
    a = 0 if lo is None else max(0, lo - SLACK)
    b = min(duration, (duration if hi is None else hi) + SLACK)
    if b <= a:
        return False
    best_t, best_n = best_window(kws, idx, duration, lo=a, hi=b)
    if best_n < MIN_HITS:
        return False                     # paraphrase, not transcript wording
    return score_at(kws, idx, v) + 2 <= best_n and abs(best_t - v) > TOLERANCE


def scan(note_path):
    """-> (status, findings). findings: [(lineno, col, raw, secs, why, repair)]"""
    note = pathlib.Path(note_path)
    text = note.read_text(errors="replace")
    sub = subtitle_for(note, text)
    if not sub.exists():
        return f"SKIP no subtitle ({sub.name})", []
    sub_lines, duration = load_subtitle(sub)
    if not sub_lines:
        return f"SKIP subtitle has no anchors ({sub.name})", []
    anchors = note_anchors(text)
    stamps = inline_stamps(text, anchors)
    recaps = recap_sections(stamps, duration)
    idx = index_keywords(sub_lines)
    lines = text.splitlines()
    findings = []
    for lineno, col, raw, secs, sect, lo, hi, in_table in stamps:
        why = is_broken(secs, lo, duration)
        if not why or (why == "BEFORE-HEADING" and sect in recaps):
            continue
        # "(folded into the body-language tree at [00:14:19])" cites the note's own
        # heading. A cross-reference is not a content anchor and has no bracket.
        if why == "BEFORE-HEADING" and secs in {a[1] for a in anchors}:
            continue
        fix = None if in_table else repair(raw, secs, lo, hi, duration)
        if fix and contradicted(lines[lineno - 1], fix[1], idx, lo, hi, duration):
            fix = None      # the transcript disagrees; the ear beats the arithmetic
        findings.append((lineno, col, raw, secs, why, fix, lo, hi, in_table))
    return f"OK duration {fmt(duration)}", findings


def apply(note_path, findings):
    """Rewrite only the flagged stamps that have a mechanical repair."""
    note = pathlib.Path(note_path)
    lines = note.read_text(errors="replace").splitlines(keepends=True)
    n = 0
    # right-to-left within a line so earlier columns stay valid
    for lineno, col, raw, _s, _w, fix, *_ in sorted(findings, reverse=True):
        if not fix:
            continue
        line = lines[lineno - 1]
        assert line[col:col + len(raw)] == raw, f"{note}:{lineno} drifted"
        lines[lineno - 1] = line[:col] + fmt(fix[1]) + line[col + len(raw):]
        n += 1
    if n:
        note.write_text("".join(lines))
    return n


def selftest():
    # bracket arithmetic
    assert ("field-shift", 1694) in candidates("[28:14:00]", 101640)
    assert ("left-shift", 3960) in candidates("[00:01:06]", 66)
    assert ("drop-hour", 302) in candidates("[01:05:02]", 3902)
    assert ("minus-1h", 302) in candidates("[01:05:02]", 3902)
    # [06:02:00] in a note whose section runs 05:00-08:00 => 6m02s
    assert repair("[06:02:00]", 21720, 300, 480, 900) == ("field-shift", 362)
    # same stamp with no plausible bracket => untouched, agent's problem
    assert repair("[06:02:00]", 21720, 500, 520, 900) is None
    # ambiguous: field-shift (150) and drop-hour (1800) both fit => refuse
    assert repair("[02:30:00]", 9000, 0, 2000, 2000) is None
    # two readings that agree on the same second are not ambiguous
    assert repair("[01:05:02]", 3902, 0, 4000, 4000) == ("minus-1h", 302)
    # a stamp already inside the video is not broken
    assert is_broken(300, 0, 900) is None
    assert is_broken(2000, 0, 900) == "PAST-END"
    assert is_broken(10, 600, 900) == "BEFORE-HEADING"
    # inline stamps skip headings and fences, and carry their bracket
    text = ("## Intro [00:01:00]\n"
            "- point at [00:02:00]\n"
            "```\n- fenced [09:09:09]\n```\n"
            "## Next [00:05:00]\n"
            "- later [00:06:00]\n")
    st = inline_stamps(text, note_anchors(text))
    assert [s[3] for s in st] == [120, 360], st
    assert st[0][5:7] == (60, 300) and st[1][5:7] == (300, None)
    # a "Key Takeaways" recap replaying the video is one section, in order
    recap = ("## Intro [00:01:00]\n## Key Takeaways [00:22:50]\n"
             "- [00:00:28] a\n- [00:05:40] b\n")
    rs = inline_stamps(recap, note_anchors(recap))
    assert recap_sections(rs, 1700) == {2}
    # ...but a lone early stamp under a late heading is not excused
    lone = "## Intro [00:01:00]\n## Later [00:22:50]\n- [00:00:28] a\n"
    assert recap_sections(inline_stamps(lone, note_anchors(lone)), 1700) == set()
    print("selftest OK")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--selftest":
        return selftest()
    mode, paths = args[0], args[1:]
    if len(paths) == 1 and paths[0].startswith("@"):   # @file = newline path list
        paths = pathlib.Path(paths[0][1:]).read_text().split("\n")
        paths = [p for p in paths if p.strip()]
    total = fixed = 0
    for p in paths:
        status, findings = scan(p)
        if not findings:
            if status.startswith("SKIP"):
                print(f"{p}\t{status}")
            continue
        total += len(findings)
        print(f"{p}\t{status}\t{len(findings)} broken")
        for lineno, col, raw, secs, why, fix, lo, hi, in_table in findings:
            b = f"[{fmt(lo) if lo is not None else '-'}..{fmt(hi) if hi is not None else 'end'}]"
            r = f"-> {fmt(fix[1])} ({fix[0]})" if fix else ("TABLE" if in_table else "AGENT")
            print(f"  L{lineno}\t{why}\t{raw} in {b}\t{r}")
        if mode == "--fix":
            fixed += apply(p, findings)
    print(f"# {total} broken, {fixed} repaired mechanically", file=sys.stderr)


if __name__ == "__main__":
    main()
