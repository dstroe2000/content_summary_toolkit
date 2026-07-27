"""
Subtitle Summary Generator

This module processes subtitle files in a folder (recursively) and generates summary files
using fabric AI patterns.

Input:
    - Folder path containing subtitle files (.srt, .sub, .vtt, .sbv, .txt)
    - Processes recursively through all subfolders

Output:
    For each subtitle file, creates a summary file:
    - Original filename (without extension) + .summary.md
    - Placed in the same directory as the source file
    - Contains Table of Contents and three sections from fabric patterns

Processing:
    - Runs fabric patterns: summarize, youtube_summary, extract_wisdom
    - Filters out <think></think> sections from outputs
    - Extracts headers from each section and generates Table of Contents
    - Aggregates results into structured text file

External Dependencies:
    - fabric: AI-powered text processing tool with patterns

Example:
    python subtitle_summary_generator.py /path/to/subtitles
    python subtitle_summary_generator.py /path/to/subtitles --overwrite --verbose
"""

import sys
import argparse
import re
import shlex
import time
from pathlib import Path

from fabric_utils import (
    extract_first_level1_header,
    generate_toc,
    stripped_input,
    context_check,
    MAX_INPUT_TOKENS,
    run_fabric_with_retry,
    timeout_for,
)


# Supported subtitle file extensions
SUBTITLE_EXTENSIONS = {'.srt', '.sub', '.vtt', '.sbv', '.txt'}


def find_subtitle_files(folder_path, extensions=None):
    """
    Recursively find all subtitle files in the given folder.

    Args:
        folder_path (str): Root folder to search
        extensions (set): Set of file extensions to search for (default: SUBTITLE_EXTENSIONS)

    Returns:
        list: List of Path objects for all subtitle files found

    Example:
        files = find_subtitle_files('/path/to/subtitles')
        # Returns: [Path('/path/to/subtitles/video.srt'), Path('/path/to/subtitles/sub/video2.vtt')]
    """
    if extensions is None:
        extensions = SUBTITLE_EXTENSIONS

    folder = Path(folder_path)
    subtitle_files = []

    # Walk through all files in folder and subfolders
    for file_path in folder.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            # Skip already generated summary files
            if not (file_path.name.endswith('.summary.md') or file_path.name.endswith('.summary.txt')):
                subtitle_files.append(file_path)

    return sorted(subtitle_files)


# Trailing language tag on a subtitle name: `.en`, `.en-US`, `.pt-BR`.
LANG_TAG_RE = re.compile(r"\.[A-Za-z]{2,3}(-[A-Za-z]{2,4})?$")


def summary_path(file_path, flat_md=False):
    """Output path for a subtitle file's generated note.

    Default keeps the ``.summary.md`` suffix: the ``/ingest-vid`` slash command
    ``cat``s and ``rm``s that exact filename, so flipping the default would
    break a caller living outside this repo. ``flat_md`` opts into
    ``video.en.srt -> video.en.md`` for notes that land in the vault directly.

    Args:
        file_path (Path): Source subtitle file.
        flat_md (bool): Use ``{stem}.md`` instead of ``{name}.summary.md``.

    Returns:
        Path: Destination path for the generated note.
    """
    if flat_md:
        return file_path.with_suffix('.md')
    return file_path.with_suffix(file_path.suffix + '.summary.md')


def source_video_path(file_path):
    """Path of the video sitting beside a subtitle: ``video.en.srt -> video.mp4``.

    Strips the subtitle extension, then a language tag if one is present.
    ``Path.with_suffix('')`` cannot be used twice here -- on a dotted title like
    ``Ep. 3 - Intro.srt`` the second call eats ``. 3 - Intro`` and yields
    ``Ep.mp4``.

    Args:
        file_path (Path): Source subtitle file.

    Returns:
        Path: Sibling ``.mp4`` path (not checked for existence).
    """
    # ponytail: a title genuinely ending in `.AI` loses that tag; rename the
    # file or pass an explicit path if that ever bites.
    stem = LANG_TAG_RE.sub("", file_path.with_suffix("").name)
    return file_path.with_name(stem + ".mp4")


def process_subtitle_file(file_path, overwrite=False, verbose=False,
                          flat_md=False, source_video=False):
    """
    Process a single subtitle file and generate summary.

    Pipeline:
    1. Check if summary file already exists (skip unless overwrite=True)
    2. Read subtitle file content
    3. Run fabric patterns: summarize, youtube_summary, extract_wisdom
    4. Filter out <think></think> sections from all outputs
    5. Aggregate into structured text file
    6. Write to {original_filename}.summary.md

    Args:
        file_path (Path): Path to subtitle file
        overwrite (bool): Whether to overwrite existing summary files
        verbose (bool): Whether to print detailed processing info
        flat_md (bool): Write ``{stem}.md`` instead of ``{name}.summary.md``
        source_video (bool): Prepend a ``file://`` link to the sibling video

    Returns:
        dict: Processing result with keys:
            - success (bool): Whether processing succeeded
            - skipped (bool): Whether file was skipped
            - reason (str): Reason for skip or failure

    Output File Structure:
        {original_filename}.summary.md containing:

        ### TOC
        - [[#header1]]
        - [[#header2]]
        - [[#header3]]

        ---

        {filtered summary}

        ---
        ---
        ---

        {filtered youtube_summary}

        ---
        ---
        ---

        {filtered extract_wisdom}
    """
    result = {
        'success': False,
        'skipped': False,
        'reason': ''
    }

    # Determine output filename
    output_filename = summary_path(file_path, flat_md)

    # Check if summary already exists
    if output_filename.exists() and not overwrite:
        result['skipped'] = True
        result['reason'] = 'Summary already exists'
        return result

    # Check if file is empty
    if file_path.stat().st_size == 0:
        result['skipped'] = True
        result['reason'] = 'Empty file'
        return result

    if verbose:
        print(f"\nProcessing: {file_path}")

    # Read subtitle file
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            subtitle_content = f.read()

        if not subtitle_content.strip():
            result['skipped'] = True
            result['reason'] = 'Empty content'
            return result
    except Exception as e:
        result['reason'] = f'Read error: {e}'
        return result

    # Run fabric patterns. shlex.quote prevents shell expansion in paths
    # containing $$, $VAR, backticks, etc. (subprocess uses shell=True).
    fabric_timeout = timeout_for(file_path)

    # Over-window input is truncated by the backend without a word, so the note
    # would silently describe only the tail of the file.
    fits, est_tokens = context_check(file_path)
    if not fits:
        result['reason'] = (f'Too large: ~{est_tokens:,} tokens > '
                            f'{MAX_INPUT_TOKENS:,} budget')
        return result

    # Timestamps cost ~35% of a transcript's tokens and mean nothing to these
    # patterns; the file on disk keeps them.
    with stripped_input(file_path) as file_in:

        # 1. Get summary using fabric's summarize pattern (retry if no H1 header)
        if verbose:
            print("  Getting summary...")
        summary_cmd = f'{file_in} | fabric -p summarize'
        success, filtered_summary, header_summarize = run_fabric_with_retry(
            summary_cmd, "summarize", verbose, timeout=fabric_timeout)
        if not success:
            result['reason'] = 'Summarize pattern failed'
            return result

        # 2. Get YouTube summary using fabric's youtube_summary pattern (retry if no H1 header)
        if verbose:
            print("  Getting YouTube summary...")
        yt_summary_cmd = f'{file_in} | fabric -p youtube_summary'
        success, filtered_youtube_summary, header_youtube = run_fabric_with_retry(
            yt_summary_cmd, "youtube_summary", verbose, timeout=fabric_timeout)
        if not success:
            result['reason'] = 'YouTube summary pattern failed'
            return result

        # 3. Extract wisdom using fabric's extract_wisdom pattern (retry if no H1 header)
        if verbose:
            print("  Extracting wisdom...")
        wisdom_cmd = f'{file_in} | fabric -p extract_wisdom'
        success, filtered_extract_wisdom, header_wisdom = run_fabric_with_retry(
            wisdom_cmd, "extract_wisdom", verbose, timeout=fabric_timeout)
        if not success:
            result['reason'] = 'Extract wisdom pattern failed'
            return result

        if verbose:
            print("  Generating table of contents...")

    # Generate TOC
    toc_content = generate_toc([header_summarize, header_youtube, header_wisdom])

    # Build TOC section only if we have headers
    toc_section = f"{toc_content}\n\n---\n\n" if toc_content else ""

    # Source-video backlink. The vault organizer's tagger needs a [link](url)
    # + blank + --- anchor to insert tags; it doubles as a jump-to-source link
    # that survives the note moving into the vault.
    header = ""
    if source_video:
        header = f"[▶ Source video]( <file://{source_video_path(file_path)}> )\n\n---\n\n"

    # Create aggregated content
    content = header + f"""{toc_section}{filtered_summary}

---
---
---

{filtered_youtube_summary}

---
---
---

{filtered_extract_wisdom}
"""

    # Write to output file
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(content)

        result['success'] = True
        if verbose:
            print(f"  Created: {output_filename}")
        return result
    except Exception as e:
        result['reason'] = f'Write error: {e}'
        return result


def main():
    """
    Main entry point for the script.

    Parses command-line arguments and processes all subtitle files in the specified folder.
    """
    parser = argparse.ArgumentParser(
        description='Generate summaries for subtitle files using fabric AI patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python subtitle_summary_generator.py /path/to/subtitles
  python subtitle_summary_generator.py /path/to/subtitles --overwrite
  python subtitle_summary_generator.py /path/to/subtitles --verbose
  python subtitle_summary_generator.py /path/to/subtitles --dry-run
  python subtitle_summary_generator.py /path/to/subtitles --extensions .srt .vtt
        """
    )

    parser.add_argument(
        'folder',
        help='Folder path containing subtitle files (processed recursively)'
    )

    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing summary files'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without actually processing'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed processing information'
    )

    parser.add_argument(
        '--extensions',
        nargs='+',
        help='Filter by specific subtitle file extensions (e.g., .srt .vtt)'
    )

    parser.add_argument(
        '--flat-md',
        action='store_true',
        help='Name output {stem}.md instead of {name}.summary.md '
             '(off by default: /ingest-vid expects the .summary.md name)'
    )

    parser.add_argument(
        '--source-video',
        action='store_true',
        help='Prepend a file:// link to the video sitting beside the subtitle'
    )

    args = parser.parse_args()

    # Validate folder exists
    folder_path = Path(args.folder)
    if not folder_path.exists():
        print(f"Error: Folder does not exist: {args.folder}")
        sys.exit(1)

    if not folder_path.is_dir():
        print(f"Error: Path is not a directory: {args.folder}")
        sys.exit(1)

    # Determine which extensions to use
    extensions = SUBTITLE_EXTENSIONS
    if args.extensions:
        # Ensure extensions start with dot
        extensions = {ext if ext.startswith('.') else f'.{ext}' for ext in args.extensions}
        extensions = {ext.lower() for ext in extensions}

    # Find all subtitle files
    print(f"Scanning for subtitle files in: {folder_path}")
    subtitle_files = find_subtitle_files(folder_path, extensions)

    if not subtitle_files:
        print("No subtitle files found.")
        sys.exit(0)

    print(f"Found {len(subtitle_files)} subtitle file(s)")

    # Dry run mode - just list files
    if args.dry_run:
        print("\nFiles to be processed (dry-run mode):")
        for file_path in subtitle_files:
            output_name = summary_path(file_path, args.flat_md)
            exists = output_name.exists()
            status = " (exists)" if exists else ""
            print(f"  {file_path}{status}")
        print(f"\nTotal: {len(subtitle_files)} files would be processed")
        sys.exit(0)

    # Process files
    print("\nProcessing files...")
    start_time = time.time()

    stats = {
        'total': len(subtitle_files),
        'success': 0,
        'skipped': 0,
        'failed': 0,
        'errors': []
    }

    for i, file_path in enumerate(subtitle_files, 1):
        # Show progress
        if not args.verbose:
            print(f"[{i}/{len(subtitle_files)}] {file_path.name}...", end=' ')

        result = process_subtitle_file(file_path, args.overwrite, args.verbose,
                                       args.flat_md, args.source_video)

        if result['success']:
            stats['success'] += 1
            if not args.verbose:
                print("✓")
        elif result['skipped']:
            stats['skipped'] += 1
            if not args.verbose:
                print(f"⊘ ({result['reason']})")
        else:
            stats['failed'] += 1
            error_msg = f"{file_path}: {result['reason']}"
            stats['errors'].append(error_msg)
            if not args.verbose:
                print(f"✗ ({result['reason']})")

    # Calculate processing time
    end_time = time.time()
    total_time = end_time - start_time

    # Print summary report
    print("\n" + "=" * 50)
    print("Subtitle Summary Generator Report")
    print("=" * 50)
    print(f"Total subtitle files found:    {stats['total']}")
    print(f"Successfully processed:        {stats['success']}")
    print(f"Already existed (skipped):     {stats['skipped']}")
    print(f"Processing failed:             {stats['failed']}")
    print()

    # Calculate success rate (excluding skipped)
    processed = stats['success'] + stats['failed']
    if processed > 0:
        success_rate = (stats['success'] / processed) * 100
        print(f"Success rate:                  {success_rate:.1f}%")

    print(f"Total processing time:         {total_time:.1f} seconds")
    print("=" * 50)

    # Print errors if any
    if stats['errors']:
        print("\nErrors encountered:")
        for error in stats['errors']:
            print(f"  - {error}")

    # Exit with error code if there were failures
    if stats['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
