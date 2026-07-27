"""
Process local SRT files with YouTube metadata enrichment.

For each SRT in --input-folder, finds the matching YouTube URL in --map-file
(markdown links `[title](url)`) by title prefix, fetches channel + description
via yt-dlp, runs fabric patterns (summarize, youtube_summary, extract_wisdom)
on the SRT content, and writes a YouTube-style note to --output-folder.

Usage:
    python srt_with_youtube_meta.py \
        --input-folder /path/to/srts \
        --map-file /path/to/test.md \
        --output-folder /path/to/output/yt_generated
"""

import argparse
import os
import re
import shlex
import sys
import unicodedata
from pathlib import Path

from fabric_utils import (
    generate_toc,
    stripped_input,
    context_check,
    MAX_INPUT_TOKENS,
    run_fabric_with_retry,
    timeout_for,
    youtube_meta,
)


LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def parse_map_file(path):
    """Return list of (title, url) tuples from markdown link lines."""
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = LINK_RE.search(line)
            if not m:
                continue
            title = m.group(1).strip()
            url = m.group(2).strip()
            if "youtube.com" in url or "youtu.be" in url:
                pairs.append((title, url))
    return pairs


def match_srt_to_url(srt_stem, pairs):
    """Find best matching (title, url) for an SRT filename stem.

    Strategy: SRT filenames are sanitized versions of YouTube titles.
    Match by longest common prefix, with simple normalization.
    """
    def norm(s):
        s = unicodedata.normalize("NFC", s)
        return re.sub(r"\s+", " ", s).strip().lower()

    n_stem = norm(srt_stem)
    best = None
    best_len = 0
    for title, url in pairs:
        n_title = norm(title)
        # SRT stem is usually a prefix of the full title (or equal)
        if n_title.startswith(n_stem) or n_stem.startswith(n_title):
            shared = min(len(n_stem), len(n_title))
            if shared > best_len:
                best = (title, url)
                best_len = shared
    return best


def process_srt(srt_path, title, url, output_folder, overwrite=False, verbose=False):
    output_path = Path(output_folder) / f"{srt_path.stem}.md"
    if output_path.exists() and not overwrite:
        print(f"  skip: {output_path.name} exists")
        return "skipped"

    # Channel and description ride in the same yt-dlp payload; asking twice
    # doubles the requests YouTube sees per video, which is what gets a batch
    # rate-limited.
    print(f"  metadata ...")
    author, channel_url, description, _title = youtube_meta(url)

    fabric_timeout = timeout_for(srt_path)
    fits, est_tokens = context_check(srt_path)
    if not fits:
        print(f"  too large: ~{est_tokens:,} tokens > {MAX_INPUT_TOKENS:,} budget")
        return "failed:oversized"
    with stripped_input(srt_path) as srt_in:
        print(f"  fabric summarize ...")
        ok, sum_text, h1 = run_fabric_with_retry(
            f'{srt_in} | fabric -p summarize', "summarize", verbose,
            timeout=fabric_timeout
        )
        if not ok:
            return "failed:summarize"

        print(f"  fabric youtube_summary ...")
        ok, yt_text, h2 = run_fabric_with_retry(
            f'{srt_in} | fabric -p youtube_summary', "youtube_summary", verbose,
            timeout=fabric_timeout
        )
        if not ok:
            return "failed:youtube_summary"

        print(f"  fabric extract_wisdom ...")
        ok, wis_text, h3 = run_fabric_with_retry(
            f'{srt_in} | fabric -p extract_wisdom', "extract_wisdom", verbose,
            timeout=fabric_timeout
        )
        if not ok:
            return "failed:extract_wisdom"

    toc = generate_toc([h1, h2, h3])
    toc_section = f"\n{toc}\n\n---\n" if toc else ""
    desc_section = f"\n{description}\n\n---\n" if description else ""

    content = f"""[{author}]({channel_url})
[Link]({url})

---
{toc_section}{desc_section}
{sum_text}

---
---
---

{yt_text}

---
---
---

{wis_text}

"""
    os.makedirs(output_folder, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  wrote {output_path}")
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-folder", required=True)
    ap.add_argument("--map-file", required=True)
    ap.add_argument("--output-folder", required=True)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--only", help="only process srt whose stem starts with this string")
    args = ap.parse_args()

    in_folder = Path(args.input_folder)
    if not in_folder.is_dir():
        print(f"input folder not found: {in_folder}")
        sys.exit(1)

    pairs = parse_map_file(args.map_file)
    print(f"Loaded {len(pairs)} URL mappings from {args.map_file}")

    srts = sorted(p for p in in_folder.glob("*.srt") if p.is_file())
    if args.only:
        srts = [s for s in srts if s.stem.startswith(args.only)]
    print(f"Found {len(srts)} SRT file(s)")

    stats = {"ok": 0, "skipped": 0, "failed": 0, "unmatched": 0}
    for i, srt in enumerate(srts, 1):
        print(f"\n[{i}/{len(srts)}] {srt.name}")
        match = match_srt_to_url(srt.stem, pairs)
        if not match:
            print(f"  unmatched: no URL for {srt.stem}")
            stats["unmatched"] += 1
            continue
        title, url = match
        print(f"  matched -> {title}")
        result = process_srt(srt, title, url, args.output_folder,
                             overwrite=args.overwrite, verbose=args.verbose)
        if result == "ok":
            stats["ok"] += 1
        elif result == "skipped":
            stats["skipped"] += 1
        else:
            stats["failed"] += 1
            print(f"  FAIL: {result}")

    print("\n" + "=" * 50)
    print(f"ok:        {stats['ok']}")
    print(f"skipped:   {stats['skipped']}")
    print(f"failed:    {stats['failed']}")
    print(f"unmatched: {stats['unmatched']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
