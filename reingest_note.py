#!/usr/bin/env python3
"""Replace a vault note's generated body with a fresh one, keeping what is real.

A failed ingest leaves the note structurally perfect and semantically empty:
"No content provided for summarization" under a heading, then thousands of bare
"- " bullets. The provenance header and the uploader's own description above it
are fine, so this splices rather than rewrites.

Layout, which every affected note shares:

    <channel / [Link] / tags>      keep
    ---
    <### TOC>                      replace, from the new summary
    ---
    <uploader description>         keep
    ---
    <generated body>               replace, from the new summary

Usage:
    reingest_note.py <note.md> <subtitle.txt.summary.md> [--write]
Without --write it prints what it would do and touches nothing.
"""
import pathlib
import sys

SEP = "---"


def split_sections(text, n=3):
    """-> (parts, seps_ok). parts are the n+1 chunks between standalone '---'."""
    lines = text.splitlines(keepends=True)
    cuts = [i for i, l in enumerate(lines) if l.strip() == SEP][:n]
    if len(cuts) < n:
        return None, False
    parts, prev = [], 0
    for c in cuts:
        parts.append("".join(lines[prev:c]))
        prev = c + 1
    parts.append("".join(lines[prev:]))
    return parts, True


def split_summary(text):
    """Fresh summary -> (toc, body). It opens with '### TOC' then a '---'."""
    lines = text.splitlines(keepends=True)
    cut = next((i for i, l in enumerate(lines) if l.strip() == SEP), None)
    if cut is None:
        return "", text
    return "".join(lines[:cut]), "".join(lines[cut + 1:])


GENERATED_OPENERS = ("ONE SENTENCE SUMMARY", "MAIN POINTS", "TAKEAWAYS",
                     "SUMMARY:", "IDEAS:", "QUOTES:")


def looks_generated(chunk):
    """True if this chunk is summariser output rather than an uploader blurb."""
    for line in chunk.splitlines():
        s = line.strip().lstrip("#").strip()
        if not s:
            continue
        return s.upper().startswith(GENERATED_OPENERS)
    return False


def reingest(note_path, summary_path):
    """-> (new_text, report) or (None, reason)."""
    note = pathlib.Path(note_path)
    text = note.read_text(errors="replace")
    parts, ok = split_sections(text)
    if not ok:
        return None, "note does not have the expected 3 '---' separators"
    head, _old_toc, desc, old_body = parts
    # Not every note has an uploader description in that slot. One had a SECOND
    # broken body there, and preserving it kept the exact error string this is
    # meant to remove. A description never opens with the summariser's headings.
    if looks_generated(desc):
        desc, old_body = "\n", desc + SEP + "\n" + old_body
    fresh = pathlib.Path(summary_path).read_text(errors="replace")
    toc, body = split_summary(fresh)
    if not body.strip():
        return None, "fresh summary has no body"
    if "No content provided" in body or "haven't included the actual content" in body:
        return None, "fresh summary is itself an error summary — do not ship it"
    # blank line after the separator: the notes are written that way, and a TOC
    # glued to its '---' renders as part of the rule in some Obsidian themes
    new = f"{head}{SEP}\n\n{toc}{SEP}\n{desc}{SEP}\n{body}"
    empt = sum(1 for l in old_body.splitlines() if l.strip() == "-")
    return new, (f"body {len(old_body.splitlines())} -> {len(body.splitlines())} lines, "
                 f"{empt} empty bullets dropped")


def main():
    args = [a for a in sys.argv[1:] if a != "--write"]
    write = "--write" in sys.argv
    if len(args) != 2:
        sys.exit(__doc__)
    new, report = reingest(*args)
    if new is None:
        print(f"SKIP {args[0]}: {report}")
        return 1
    print(f"{'WROTE' if write else 'DRY  '} {args[0]}: {report}")
    if write:
        pathlib.Path(args[0]).write_text(new)
    return 0


def selftest():
    note = ("[Chan](u)\n\n---\n### TOC\n- [[#OLD]]\n---\ndescription here\n---\n"
            "# ONE SENTENCE SUMMARY:\nNo content provided for summarization.\n- \n- \n")
    fresh = "### TOC\n- [[#NEW]]\n\n---\n\n# ONE SENTENCE SUMMARY:\nReal content.\n"
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "n.md").write_text(note)
    (d / "s.md").write_text(fresh)
    new, rep = reingest(d / "n.md", d / "s.md")
    assert "[Chan](u)" in new and "description here" in new, new
    assert "No content provided" not in new and "[[#OLD]]" not in new, new
    assert "[[#NEW]]" in new and "Real content." in new, new
    assert new.count("\n---\n") == 3, repr(new)
    assert "2 empty bullets dropped" in rep, rep
    # a fresh summary that is itself broken must never be shipped
    (d / "bad.md").write_text("### TOC\n---\n# X\nNo content provided for summarization.\n")
    assert reingest(d / "n.md", d / "bad.md")[0] is None
    # a note without the expected shape is refused, not guessed at
    (d / "flat.md").write_text("no separators here\n")
    assert reingest(d / "flat.md", d / "s.md")[0] is None
    # the description slot may hold a SECOND broken body, not a blurb. Keeping it
    # would preserve the very error string this tool exists to remove.
    twobody = ("[Chan](u)\n---\n### TOC\n- [[#OLD]]\n---\n"
               "ONE SENTENCE SUMMARY:\nNo content provided for summarization.\n---\n"
               "# ONE SENTENCE SUMMARY:\nalso broken\n")
    (d / "two.md").write_text(twobody)
    new, _ = reingest(d / "two.md", d / "s.md")
    assert "No content provided" not in new, new
    assert "Real content." in new and "[Chan](u)" in new, new
    assert looks_generated("\n# MAIN POINTS:\n1. x\n")
    assert not looks_generated("\nAnyone can build an agent. LangSmith is…\n")
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
