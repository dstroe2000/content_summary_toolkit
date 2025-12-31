"""
YouTube Channel Updater

This module updates existing YouTube summary markdown files by adding missing channel
author information and video descriptions.

Purpose:
    Updates files generated before the channel information and video description
    features were implemented. Scans existing YouTube summary files and inserts:
    - Author/channel line above the video link
    - Video description after TOC section

Usage:
    # Process default folder (output/yt_generated/)
    python youtube_channel_updater.py

    # Process custom folder
    python youtube_channel_updater.py --folder /path/to/folder

    # Preview changes without modifying files
    python youtube_channel_updater.py --dry-run

    # Verbose output
    python youtube_channel_updater.py --verbose

    # Skip video description extraction (channel info only)
    python youtube_channel_updater.py --skip-description

External Dependencies:
    - yt-dlp: YouTube metadata and description extraction tool

Example Output:
    ==================================================
    YouTube Channel Updater Summary
    ==================================================
    Total files found:      25
    Successfully updated:   20
    Already updated:        3
    No link found:          1
    Extraction failed:      1

    Video descriptions:
      Added:                15
      Already exists:       8
      Extraction failed:    2

    Success rate:           95.2%
    ==================================================
"""

import os
import sys
import re
import argparse
import subprocess
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


def _get_youtube_description(video_url):
    """
    Extract video description from YouTube URL using yt-dlp.

    This retrieves the original description text written by the video creator.

    Args:
        video_url (str): YouTube video URL

    Returns:
        str: Video description text, or empty string if extraction fails

    Example:
        description = _get_youtube_description("https://www.youtube.com/watch?v=sVcwVQRHIc8")
        # Returns: The video's description text as written by the creator

    Implementation:
        Runs: yt-dlp --get-description <video_url>
    """
    try:
        command = f'yt-dlp --get-description "{video_url}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return ""
    except Exception as e:
        return ""


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


def _has_video_description(content):
    """
    Check if file already has video description after TOC.

    Looks for content between the TOC separator and the next section separator.
    Pattern:
        ### TOC
        ...
        ---

        [content here]  ← If non-whitespace exists here, description exists

        ---

    Args:
        content (str): Markdown file content

    Returns:
        bool: True if video description exists, False otherwise

    Example:
        if _has_video_description(content):
            print("Description already exists, skipping")
    """
    # Find TOC section and the content after it
    # Pattern: ### TOC ... --- [content] ---
    pattern = r'### TOC.*?---\s*\n(.*?)\n---'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        between_separators = match.group(1).strip()
        # If there's content between the separators, description exists
        return len(between_separators) > 0

    # No TOC found or pattern doesn't match
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
    author_line = f'[{author_name}]({channel_url})\n'

    # Replace [Link](...) with author_line + [Link](...)
    updated_content = re.sub(pattern, author_line + r'\1', content, count=1)

    return updated_content


def _insert_video_description(content, video_description):
    """
    Insert video description after TOC section.

    Inserts the video description between the TOC separator and the next section.
    Pattern:
        ### TOC
        ...
        ---

        {video_description}  ← INSERT HERE

        ---

    Args:
        content (str): Original markdown file content
        video_description (str): Video description text to insert

    Returns:
        str: Updated content with description inserted, or original content if TOC not found

    Example:
        Before:
            ### TOC
            - [[#SUMMARY]]

            ---

            # SUMMARY

        After:
            ### TOC
            - [[#SUMMARY]]

            ---

            Video description text here...

            ---

            # SUMMARY
    """
    # Pattern to find TOC section followed by separator
    # We want to insert after the "---" that follows "### TOC"
    pattern = r'(### TOC.*?---)\s*\n'

    # Check if pattern exists
    if not re.search(pattern, content, re.DOTALL):
        # No TOC found, return original content
        return content

    # Create the replacement: TOC section + separator + description + separator
    replacement = r'\1\n\n' + video_description + '\n\n---\n'

    # Replace only the first occurrence
    updated_content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)

    return updated_content


def process_file(file_path, dry_run=False, verbose=False, skip_description=False):
    """
    Process a single markdown file to add channel information and video description.

    Pipeline:
    1. Read file content
    2. Extract YouTube video URL
    3. Check if already updated (skip if yes)
    4. Get channel info using yt-dlp
    5. Update file content with author line
    6. Get video description using yt-dlp (unless skip_description=True)
    7. Insert video description after TOC (if not already present)
    8. Write back to file (unless dry-run mode)

    Args:
        file_path (str or Path): Path to markdown file to process
        dry_run (bool): If True, preview changes without modifying file
        verbose (bool): If True, print detailed processing information
        skip_description (bool): If True, skip video description extraction

    Returns:
        dict: Processing result with keys:
            - status: 'updated', 'already_updated', 'no_link', 'extraction_failed', 'error'
            - message: Description of what happened
            - author_name: Channel name (if successful)
            - channel_url: Channel URL (if successful)
            - description_added: True if description was added
            - description_exists: True if description already existed
            - description_failed: True if description extraction failed

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

        # Update content with channel info
        updated_content = _update_file_content(content, author_name, channel_url)

        # Track description status
        description_added = False
        description_exists = False
        description_failed = False

        # Handle video description (unless skipped)
        if not skip_description:
            if verbose:
                print("  Checking video description...")

            # Check if description already exists
            if _has_video_description(updated_content):
                if verbose:
                    print("  ✓ Description already exists")
                description_exists = True
            else:
                # Extract video description
                if verbose:
                    print("  Fetching video description...")

                video_description = _get_youtube_description(youtube_url)

                if video_description:
                    if verbose:
                        print(f"  Description fetched ({len(video_description)} characters)")

                    # Insert description after TOC
                    updated_content = _insert_video_description(updated_content, video_description)

                    # Check if insertion was successful (TOC exists)
                    if _has_video_description(updated_content):
                        description_added = True
                        if verbose:
                            print("  ✓ Description added")
                    else:
                        if verbose:
                            print("  ⚠ No TOC found, skipping description")
                else:
                    description_failed = True
                    if verbose:
                        print("  ⚠ Failed to fetch description")

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
            'channel_url': channel_url,
            'description_added': description_added,
            'description_exists': description_exists,
            'description_failed': description_failed
        }

    except Exception as e:
        if verbose:
            print(f"  ✗ Error: {str(e)}")
        return {
            'status': 'error',
            'message': f'Error processing file: {str(e)}'
        }


def process_folder(folder_path, dry_run=False, verbose=False, skip_description=False):
    """
    Process all markdown files in a folder.

    Scans the folder for .md files and processes each one to add
    missing channel information and video descriptions.

    Args:
        folder_path (str or Path): Path to folder containing markdown files
        dry_run (bool): If True, preview changes without modifying files
        verbose (bool): If True, print detailed processing information
        skip_description (bool): If True, skip video description extraction

    Returns:
        dict: Summary statistics with keys:
            - total_files: Total number of .md files found
            - updated: Number of files successfully updated
            - already_updated: Number of files that already had channel info
            - no_link: Number of files without YouTube links
            - extraction_failed: Number of files where channel extraction failed
            - errors: Number of files that had processing errors
            - description_added: Number of files where description was added
            - description_exists: Number of files that already have description
            - description_failed: Number of files where description extraction failed
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
            'description_added': 0,
            'description_exists': 0,
            'description_failed': 0,
            'success_rate': 0.0
        }

    print(f"Found {len(md_files)} markdown file(s) in {folder_path}")
    if dry_run:
        print("Running in DRY-RUN mode - no files will be modified")
    if skip_description:
        print("Skipping video description extraction")
    print()

    # Statistics
    stats = {
        'total_files': len(md_files),
        'updated': 0,
        'already_updated': 0,
        'no_link': 0,
        'extraction_failed': 0,
        'errors': 0,
        'description_added': 0,
        'description_exists': 0,
        'description_failed': 0
    }

    # Process each file
    for file_path in md_files:
        result = process_file(file_path, dry_run=dry_run, verbose=verbose, skip_description=skip_description)

        # Update statistics
        if result['status'] == 'updated':
            stats['updated'] += 1
            # Track description stats if applicable
            if result.get('description_added'):
                stats['description_added'] += 1
            if result.get('description_exists'):
                stats['description_exists'] += 1
            if result.get('description_failed'):
                stats['description_failed'] += 1
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


def print_summary(stats, dry_run=False, skip_description=False):
    """
    Print summary statistics after processing.

    Displays a formatted report of processing results including
    total files, success count, failures, description stats, and success rate.

    Args:
        stats (dict): Statistics dictionary from process_folder()
        dry_run (bool): If True, indicates this was a dry-run
        skip_description (bool): If True, indicates descriptions were skipped

    Example:
        ==================================================
        YouTube Channel Updater Summary
        ==================================================
        Total files found:      25
        Successfully updated:   20
        Already updated:        3
        No link found:          1
        Extraction failed:      1

        Video descriptions:
          Added:                15
          Already exists:       8
          Extraction failed:    2

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

    # Show description stats only if not skipped
    if not skip_description:
        print()
        print("Video descriptions:")
        print(f"  Added:                {stats['description_added']}")
        print(f"  Already exists:       {stats['description_exists']}")
        print(f"  Extraction failed:    {stats['description_failed']}")

    print()
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
        --skip-description: Skip video description extraction

    Usage:
        python youtube_channel_updater.py
        python youtube_channel_updater.py --folder /path/to/folder
        python youtube_channel_updater.py --dry-run --verbose
        python youtube_channel_updater.py --skip-description
    """
    parser = argparse.ArgumentParser(
        description='Update existing YouTube summary files with channel information and video descriptions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s --folder /path/to/folder
  %(prog)s --dry-run
  %(prog)s --verbose --dry-run
  %(prog)s --skip-description
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

    parser.add_argument(
        '--skip-description',
        action='store_true',
        help='Skip video description extraction (only update channel info)'
    )

    args = parser.parse_args()

    # Process folder
    stats = process_folder(
        folder_path=args.folder,
        dry_run=args.dry_run,
        verbose=args.verbose,
        skip_description=args.skip_description
    )

    # Print summary
    print_summary(stats, dry_run=args.dry_run, skip_description=args.skip_description)


if __name__ == "__main__":
    main()
