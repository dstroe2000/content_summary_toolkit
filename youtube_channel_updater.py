"""
YouTube Channel Updater

This module updates existing YouTube summary markdown files by adding missing channel
author information above the video link.

Purpose:
    Updates files generated before the channel information feature was implemented.
    Scans existing YouTube summary files and inserts the author/channel line above
    the video link without modifying other content.

Usage:
    # Process default folder (output/yt_generated/)
    python youtube_channel_updater.py

    # Process custom folder
    python youtube_channel_updater.py --folder /path/to/folder

    # Preview changes without modifying files
    python youtube_channel_updater.py --dry-run

    # Verbose output
    python youtube_channel_updater.py --verbose

External Dependencies:
    - yt-dlp: YouTube metadata extraction tool for retrieving channel information

Example Output:
    ==================================================
    YouTube Channel Updater Summary
    ==================================================
    Total files found:      25
    Successfully updated:   20
    Already updated:        3
    No link found:          1
    Extraction failed:      1
    Success rate:           95.2%
    ==================================================
"""

import os
import sys
import re
import argparse
import yt_dlp
from pathlib import Path


def _get_youtube_channel_info(video_url):
    """
    Extract YouTube channel information from video URL using yt-dlp.

    Prefers modern handle format (@username) over legacy channel ID format.

    Args:
        video_url (str): YouTube video URL

    Returns:
        tuple: (author_name, channel_url) or (None, None) if extraction fails

    Example:
        author, channel = _get_youtube_channel_info("https://www.youtube.com/watch?v=sVcwVQRHIc8")
        # Returns: ("freeCodeCamp.org", "https://www.youtube.com/@freecodecamp")

    Note:
        Prefers handle format (https://www.youtube.com/@username) over
        legacy channel ID format (https://www.youtube.com/channel/UC...)
    """
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            # Get author name
            author_name = info.get('uploader', info.get('channel', 'Unknown'))

            # Try to get channel URL, preferring handle format over channel ID
            channel_url = info.get('channel_url', '')
            uploader_url = info.get('uploader_url', '')

            # Prefer handle format (@username) over channel ID (UC...)
            # Handle format contains '@', channel ID format contains '/channel/'
            if uploader_url and '/@' in uploader_url:
                # Modern handle format found in uploader_url
                channel_url = uploader_url
            elif channel_url and '/@' in channel_url:
                # Modern handle format found in channel_url
                pass  # Already using channel_url
            elif uploader_url:
                # Fallback to uploader_url if no handle found
                channel_url = uploader_url
            # else: keep channel_url as is (may be legacy format or empty)

            return author_name, channel_url
    except Exception as e:
        return None, None


def _extract_youtube_link(content):
    """
    Extract YouTube video URL from markdown file content.

    Searches for the pattern: [Link](https://www.youtube.com/watch?v=...)

    Args:
        content (str): Markdown file content

    Returns:
        tuple: (youtube_url, match_object) or (None, None) if not found

    Example:
        url, match = _extract_youtube_link(content)
        # Returns: ("https://www.youtube.com/watch?v=sVcwVQRHIc8", match_object)
    """
    # Pattern to match [Link](youtube_url)
    pattern = r'\[Link\]\((https://(?:www\.)?youtube\.com/watch\?v=[^\)]+)\)'
    match = re.search(pattern, content)

    if match:
        return match.group(1), match
    return None, None


def _is_already_updated(content):
    """
    Check if the file already has channel information.

    Checks if there's a non-empty line immediately before [Link](...)
    This prevents duplicate author lines.

    Args:
        content (str): Markdown file content

    Returns:
        bool: True if file appears to already have channel info, False otherwise

    Example:
        if _is_already_updated(content):
            print("File already updated, skipping")
    """
    # Look for pattern where there's content on the line before [Link](...)
    # Pattern: non-whitespace content, then [Link](...)
    pattern = r'\[[^\]]+\]\([^\)]+\)\s*\n\s*\[Link\]\(https://(?:www\.)?youtube\.com'

    if re.search(pattern, content):
        return True
    return False


def _update_file_content(content, author_name, channel_url):
    """
    Insert channel author information above the video link.

    Inserts [{author_name}]({channel_url}) on a new line immediately before
    the existing [Link](...) line.

    Args:
        content (str): Original markdown file content
        author_name (str): YouTube channel name
        channel_url (str): YouTube channel URL

    Returns:
        str: Updated content with channel information inserted

    Example:
        Before:
            [Link](https://www.youtube.com/watch?v=VIDEO_ID)

        After:
            [freeCodeCamp.org](https://www.youtube.com/@freecodecamp)

            [Link](https://www.youtube.com/watch?v=VIDEO_ID)
    """
    # Pattern to find [Link](youtube_url)
    pattern = r'(\[Link\]\(https://(?:www\.)?youtube\.com/watch\?v=[^\)]+\))'

    # Create the author line to insert
    author_line = f'[{author_name}]({channel_url})\n\n'

    # Replace [Link](...) with author_line + [Link](...)
    updated_content = re.sub(pattern, author_line + r'\1', content, count=1)

    return updated_content


def process_file(file_path, dry_run=False, verbose=False):
    """
    Process a single markdown file to add channel information.

    Pipeline:
    1. Read file content
    2. Extract YouTube video URL
    3. Check if already updated (skip if yes)
    4. Get channel info using yt-dlp
    5. Update file content with author line
    6. Write back to file (unless dry-run mode)

    Args:
        file_path (str or Path): Path to markdown file to process
        dry_run (bool): If True, preview changes without modifying file
        verbose (bool): If True, print detailed processing information

    Returns:
        dict: Processing result with keys:
            - status: 'updated', 'already_updated', 'no_link', 'extraction_failed', 'error'
            - message: Description of what happened
            - author_name: Channel name (if successful)
            - channel_url: Channel URL (if successful)

    Example:
        result = process_file("output/yt_generated/video.md", dry_run=True)
        if result['status'] == 'updated':
            print(f"Would update with: {result['author_name']}")
    """
    file_path = Path(file_path)

    if verbose:
        print(f"\nProcessing: {file_path.name}")

    try:
        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract YouTube link
        youtube_url, _ = _extract_youtube_link(content)
        if not youtube_url:
            if verbose:
                print("  ⚠ No YouTube link found")
            return {
                'status': 'no_link',
                'message': 'No YouTube link found in file'
            }

        if verbose:
            print(f"  Found video: {youtube_url}")

        # Check if already updated
        if _is_already_updated(content):
            if verbose:
                print("  ✓ Already updated, skipping")
            return {
                'status': 'already_updated',
                'message': 'File already has channel information'
            }

        # Get channel information
        if verbose:
            print("  Fetching channel info...")

        author_name, channel_url = _get_youtube_channel_info(youtube_url)

        if not author_name or not channel_url:
            if verbose:
                print("  ✗ Failed to extract channel info")
            return {
                'status': 'extraction_failed',
                'message': f'Failed to extract channel info for {youtube_url}'
            }

        if verbose:
            print(f"  Channel: {author_name}")
            print(f"  URL: {channel_url}")

        # Update content
        updated_content = _update_file_content(content, author_name, channel_url)

        # Write back to file (unless dry-run)
        if not dry_run:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            if verbose:
                print("  ✓ File updated successfully")
        else:
            if verbose:
                print("  ✓ Would update (dry-run mode)")

        return {
            'status': 'updated',
            'message': 'Successfully updated',
            'author_name': author_name,
            'channel_url': channel_url
        }

    except Exception as e:
        if verbose:
            print(f"  ✗ Error: {str(e)}")
        return {
            'status': 'error',
            'message': f'Error processing file: {str(e)}'
        }


def process_folder(folder_path, dry_run=False, verbose=False):
    """
    Process all markdown files in a folder.

    Scans the folder for .md files and processes each one to add
    missing channel information.

    Args:
        folder_path (str or Path): Path to folder containing markdown files
        dry_run (bool): If True, preview changes without modifying files
        verbose (bool): If True, print detailed processing information

    Returns:
        dict: Summary statistics with keys:
            - total_files: Total number of .md files found
            - updated: Number of files successfully updated
            - already_updated: Number of files that already had channel info
            - no_link: Number of files without YouTube links
            - extraction_failed: Number of files where channel extraction failed
            - errors: Number of files that had processing errors
            - success_rate: Percentage of files successfully processed

    Example:
        stats = process_folder("output/yt_generated", dry_run=True)
        print(f"Success rate: {stats['success_rate']:.1f}%")
    """
    folder_path = Path(folder_path)

    if not folder_path.exists():
        print(f"Error: Folder not found: {folder_path}")
        sys.exit(1)

    # Find all .md files
    md_files = list(folder_path.glob("*.md"))

    if not md_files:
        print(f"No markdown files found in: {folder_path}")
        return {
            'total_files': 0,
            'updated': 0,
            'already_updated': 0,
            'no_link': 0,
            'extraction_failed': 0,
            'errors': 0,
            'success_rate': 0.0
        }

    print(f"Found {len(md_files)} markdown file(s) in {folder_path}")
    if dry_run:
        print("Running in DRY-RUN mode - no files will be modified")
    print()

    # Statistics
    stats = {
        'total_files': len(md_files),
        'updated': 0,
        'already_updated': 0,
        'no_link': 0,
        'extraction_failed': 0,
        'errors': 0
    }

    # Process each file
    for file_path in md_files:
        result = process_file(file_path, dry_run=dry_run, verbose=verbose)

        # Update statistics
        if result['status'] == 'updated':
            stats['updated'] += 1
            if not verbose:
                print(f"✓ Updated: {file_path.name}")
        elif result['status'] == 'already_updated':
            stats['already_updated'] += 1
            if not verbose:
                print(f"- Skipped (already updated): {file_path.name}")
        elif result['status'] == 'no_link':
            stats['no_link'] += 1
            if not verbose:
                print(f"⚠ Skipped (no link): {file_path.name}")
        elif result['status'] == 'extraction_failed':
            stats['extraction_failed'] += 1
            if not verbose:
                print(f"✗ Failed (extraction): {file_path.name}")
        else:  # error
            stats['errors'] += 1
            if not verbose:
                print(f"✗ Error: {file_path.name}")

    # Calculate success rate
    total_processed = stats['updated'] + stats['already_updated']
    if stats['total_files'] > 0:
        stats['success_rate'] = (total_processed / stats['total_files']) * 100
    else:
        stats['success_rate'] = 0.0

    return stats


def print_summary(stats, dry_run=False):
    """
    Print summary statistics after processing.

    Displays a formatted report of processing results including
    total files, success count, failures, and success rate.

    Args:
        stats (dict): Statistics dictionary from process_folder()
        dry_run (bool): If True, indicates this was a dry-run

    Example:
        ==================================================
        YouTube Channel Updater Summary
        ==================================================
        Total files found:      25
        Successfully updated:   20
        Already updated:        3
        No link found:          1
        Extraction failed:      1
        Success rate:           95.2%
        ==================================================
    """
    print("\n" + "=" * 50)
    print("YouTube Channel Updater Summary")
    if dry_run:
        print("(DRY-RUN MODE - No files were modified)")
    print("=" * 50)
    print(f"Total files found:      {stats['total_files']}")
    print(f"Successfully updated:   {stats['updated']}")
    print(f"Already updated:        {stats['already_updated']}")
    print(f"No link found:          {stats['no_link']}")
    print(f"Extraction failed:      {stats['extraction_failed']}")
    print(f"Errors:                 {stats['errors']}")
    print(f"Success rate:           {stats['success_rate']:.1f}%")
    print("=" * 50)


def main():
    """
    Main entry point for the YouTube Channel Updater CLI application.

    Parses command-line arguments and orchestrates the update process.

    Command-line Arguments:
        --folder: Path to folder containing markdown files (default: output/yt_generated/)
        --dry-run: Preview changes without modifying files
        --verbose: Print detailed processing information

    Usage:
        python youtube_channel_updater.py
        python youtube_channel_updater.py --folder /path/to/folder
        python youtube_channel_updater.py --dry-run --verbose
    """
    parser = argparse.ArgumentParser(
        description='Update existing YouTube summary files with channel information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s --folder /path/to/folder
  %(prog)s --dry-run
  %(prog)s --verbose --dry-run
        """
    )

    parser.add_argument(
        '--folder',
        type=str,
        default='output/yt_generated',
        help='Path to folder containing markdown files (default: output/yt_generated/)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed processing information'
    )

    args = parser.parse_args()

    # Process folder
    stats = process_folder(
        folder_path=args.folder,
        dry_run=args.dry_run,
        verbose=args.verbose
    )

    # Print summary
    print_summary(stats, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
