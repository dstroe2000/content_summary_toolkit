"""
Subtitle Summary Generator

This module processes subtitle files in a folder (recursively) and generates summary files
using fabric AI patterns.

Input:
    - Folder path containing subtitle files (.srt, .sub, .vtt, .sbv, .txt)
    - Processes recursively through all subfolders

Output:
    For each subtitle file, creates a summary file:
    - Original filename (without extension) + .summary.txt
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

import subprocess
import re
import sys
import os
import argparse
import time
from pathlib import Path


# Supported subtitle file extensions
SUBTITLE_EXTENSIONS = {'.srt', '.sub', '.vtt', '.sbv', '.txt'}


def _filter_think_sections(text):
    """
    Remove <think></think> sections from text.

    LLM outputs from fabric may contain <think></think> tags that need to be filtered out
    before including the content in the final summary.

    Args:
        text (str): Text potentially containing <think></think> sections

    Returns:
        str: Text with all <think></think> sections removed and stripped
    """
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _extract_first_level1_header(text):
    """
    Extract the first level 1 header text from content.

    Searches for the first line starting with '# ' (single hash followed by space)
    and returns the header text with trailing colons removed.

    Args:
        text (str): Text content to search for headers

    Returns:
        str: Header text with trailing colons removed, or None if no header found

    Examples:
        >>> _extract_first_level1_header("# ONE SENTENCE SUMMARY:\\nContent here")
        'ONE SENTENCE SUMMARY'

        >>> _extract_first_level1_header("# Summary of Video\\nContent")
        'Summary of Video'
    """
    for line in text.split('\n'):
        # Match lines starting with exactly one # followed by space
        match = re.match(r'^#\s+(.+)$', line.strip())
        if match:
            header_text = match.group(1)
            # Remove trailing colons and trim whitespace
            header_text = re.sub(r':+\s*$', '', header_text).strip()
            return header_text

    # No level 1 header found
    return None


def _generate_toc(headers):
    """
    Generate Table of Contents from header texts.

    Args:
        headers (list): List of header texts extracted from sections

    Returns:
        str: Formatted TOC markdown or empty string if no headers

    Example:
        >>> headers = ['ONE SENTENCE SUMMARY', 'Summary of Video', 'SUMMARY']
        >>> print(_generate_toc(headers))
        ### TOC
        - [[#ONE SENTENCE SUMMARY]]
        - [[#Summary of Video]]
        - [[#SUMMARY]]
    """
    # Filter out None values (sections with no headers)
    valid_headers = [h for h in headers if h is not None]

    if not valid_headers:
        return ""  # No headers found, return empty string

    # Build TOC
    toc_lines = ["### TOC"]
    for header in valid_headers:
        toc_lines.append(f"- [[#{header}]]")

    return "\n".join(toc_lines)


def _run_command(command, verbose=False):
    """
    Run a bash command and return the output.

    Executes shell commands for processing subtitle files through fabric patterns.

    Args:
        command (str): The bash command to execute
        verbose (bool): Whether to print verbose output

    Returns:
        tuple: (success: bool, output: str) - success status and command stdout

    Example Commands:
        - "cat 'video.srt' | fabric -p summarize"
        - "cat 'video.srt' | fabric -p youtube_summary"
        - "cat 'video.srt' | fabric -p extract_wisdom"
    """
    try:
        if verbose:
            print(f"  Running: {command}")

        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            print(f"  Error running command: {command}")
            print(f"  Error output: {result.stderr}")
            return False, ""
    except Exception as e:
        print(f"  Exception running command: {e}")
        return False, ""


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
            if not file_path.name.endswith('.summary.txt'):
                subtitle_files.append(file_path)

    return sorted(subtitle_files)


def process_subtitle_file(file_path, overwrite=False, verbose=False):
    """
    Process a single subtitle file and generate summary.

    Pipeline:
    1. Check if summary file already exists (skip unless overwrite=True)
    2. Read subtitle file content
    3. Run fabric patterns: summarize, youtube_summary, extract_wisdom
    4. Filter out <think></think> sections from all outputs
    5. Aggregate into structured text file
    6. Write to {original_filename}.summary.txt

    Args:
        file_path (Path): Path to subtitle file
        overwrite (bool): Whether to overwrite existing summary files
        verbose (bool): Whether to print detailed processing info

    Returns:
        dict: Processing result with keys:
            - success (bool): Whether processing succeeded
            - skipped (bool): Whether file was skipped
            - reason (str): Reason for skip or failure

    Output File Structure:
        {original_filename}.summary.txt containing:

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
    output_filename = file_path.with_suffix(file_path.suffix + '.summary.txt')

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

    # Run fabric patterns
    file_path_str = str(file_path)

    # 1. Get summary using fabric's summarize pattern
    if verbose:
        print("  Getting summary...")
    summary_cmd = f'cat "{file_path_str}" | fabric -p summarize'
    success, summary = _run_command(summary_cmd, verbose)
    if not success:
        result['reason'] = 'Summarize pattern failed'
        return result
    filtered_summary = _filter_think_sections(summary)

    # 2. Get YouTube summary using fabric's youtube_summary pattern
    if verbose:
        print("  Getting YouTube summary...")
    yt_summary_cmd = f'cat "{file_path_str}" | fabric -p youtube_summary'
    success, youtube_summary = _run_command(yt_summary_cmd, verbose)
    if not success:
        result['reason'] = 'YouTube summary pattern failed'
        return result
    filtered_youtube_summary = _filter_think_sections(youtube_summary)

    # 3. Extract wisdom using fabric's extract_wisdom pattern
    if verbose:
        print("  Extracting wisdom...")
    wisdom_cmd = f'cat "{file_path_str}" | fabric -p extract_wisdom'
    success, extract_wisdom = _run_command(wisdom_cmd, verbose)
    if not success:
        result['reason'] = 'Extract wisdom pattern failed'
        return result
    filtered_extract_wisdom = _filter_think_sections(extract_wisdom)

    # Extract first level 1 header from each section for TOC
    if verbose:
        print("  Generating table of contents...")
    header_summarize = _extract_first_level1_header(filtered_summary)
    header_youtube = _extract_first_level1_header(filtered_youtube_summary)
    header_wisdom = _extract_first_level1_header(filtered_extract_wisdom)

    # Generate TOC
    toc_content = _generate_toc([header_summarize, header_youtube, header_wisdom])

    # Build TOC section only if we have headers
    toc_section = f"{toc_content}\n\n---\n\n" if toc_content else ""

    # Create aggregated content
    content = f"""{toc_section}{filtered_summary}

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
            output_name = file_path.with_suffix(file_path.suffix + '.summary.txt')
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

        result = process_subtitle_file(file_path, args.overwrite, args.verbose)

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
