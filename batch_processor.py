"""
Batch Processor for YouTube and Blog Entry Summaries

This module processes batch files containing multiple entries and routes them to
the appropriate generator (YouTube or blog) based on entry type.

Entry Types:
    - YouTube entries: [title](youtube-url) → routed to process_youtube_entry()
    - Blog entries: [title](blog-url) → routed to process_blog_entry()
    - Empty lines → skipped
    - Markdown headers (lines starting with #) → skipped
    - Commentary (lines starting with \\#) → skipped
    - Separators (lines with ---) → skipped

External Dependencies:
    - youtube_summary_generator: Provides process_youtube_entry() function
    - blog_summary_generator: Provides process_blog_entry() function

Example:
    python batch_processor.py batch_entries.txt
"""

import sys
import re
import os
import time
from youtube_summary_generator import process_youtube_entry
from blog_summary_generator import process_blog_entry


def _classify_entry(line):
    """
    Classify a batch file line into entry type.

    Classifies lines into one of the following categories:
    - SKIP: Empty lines, markdown headers (#), commentary (\\#), or separators (---)
    - YOUTUBE: Markdown-formatted YouTube URL entries
    - BLOG: Markdown-formatted non-YouTube URL entries
    - INVALID: Lines that don't match any expected format

    Args:
        line (str): Single line from batch file

    Returns:
        tuple: (entry_type, title, url) where:
            - entry_type (str): One of 'SKIP', 'YOUTUBE', 'BLOG', 'INVALID'
            - title (str or None): Extracted title from [title] or None
            - url (str or None): Extracted URL from (url) or None

    Examples:
        >>> _classify_entry("")
        ('SKIP', None, None)

        >>> _classify_entry("# Section Header")
        ('SKIP', None, None)

        >>> _classify_entry("---")
        ('SKIP', None, None)

        >>> _classify_entry("[Video](https://youtube.com/watch?v=123)")
        ('YOUTUBE', 'Video', 'https://youtube.com/watch?v=123')

        >>> _classify_entry("[Article](https://example.com/article)")
        ('BLOG', 'Article', 'https://example.com/article')
    """
    stripped = line.strip()

    # Skip conditions: empty lines, markdown headers, commentary, or separators
    if not stripped or stripped.startswith('#') or stripped.startswith('\\#') or stripped == '---':
        return ('SKIP', None, None)

    # Parse markdown format [title](url)
    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', stripped)
    if not match:
        return ('INVALID', None, None)

    title = match.group(1).strip()
    url = match.group(2).strip()

    # Classify by URL domain
    if 'youtube.com' in url or 'youtu.be' in url:
        return ('YOUTUBE', title, url)
    else:
        return ('BLOG', title, url)


def _process_youtube(entry):
    """
    Process a YouTube entry by calling process_youtube_entry() function.

    Calls the YouTube summary generator function directly to process the entry.

    Args:
        entry (str): Markdown-formatted entry "[title](youtube-url)"

    Returns:
        bool: True if processing succeeded, False otherwise

    Side Effects:
        - Calls process_youtube_entry() which prints output and creates files
        - Prints errors to stdout if processing fails
    """
    try:
        process_youtube_entry(entry)
        return True
    except Exception as e:
        print(f"  Error: Exception processing YouTube entry: {e}")
        return False


def _process_blog(entry):
    """
    Process a blog entry by calling process_blog_entry() function.

    Calls the blog summary generator function directly to process the entry.

    Args:
        entry (str): Markdown-formatted entry "[title](blog-url)"

    Returns:
        bool: True if processing succeeded, False otherwise

    Side Effects:
        - Calls process_blog_entry() which prints output and creates files
        - Prints errors to stdout if processing fails
    """
    try:
        process_blog_entry(entry)
        return True
    except Exception as e:
        print(f"  Error: Exception processing blog entry: {e}")
        return False


def _print_summary_report(stats, elapsed_time):
    """
    Print a summary report of batch processing statistics.

    Args:
        stats (dict): Dictionary containing processing statistics with keys:
            - total (int): Total lines processed
            - processed_youtube (int): Successfully processed YouTube entries
            - processed_blog (int): Successfully processed blog entries
            - skipped (int): Skipped lines (empty, headers, commentary)
            - invalid (int): Invalid format lines
            - errors (list): List of error messages
        elapsed_time (float): Total time taken for batch processing in seconds

    Side Effects:
        Prints formatted summary report to stdout
    """
    print("\n" + "=" * 50)
    print("Batch Processing Summary")
    print("=" * 50)
    print(f"Total lines:           {stats['total']}")
    print(f"YouTube processed:     {stats['processed_youtube']}")
    print(f"Blog processed:        {stats['processed_blog']}")
    print(f"Skipped:              {stats['skipped']}")
    print(f"Invalid format:       {stats['invalid']}")
    print(f"Errors:               {len(stats['errors'])}")

    # Calculate success rate
    total_attempted = stats['processed_youtube'] + stats['processed_blog'] + len(stats['errors'])
    if total_attempted > 0:
        success_count = stats['processed_youtube'] + stats['processed_blog']
        success_rate = (success_count / total_attempted) * 100
        print(f"Success rate:         {success_rate:.1f}%")

    # Format and display elapsed time
    if elapsed_time < 60:
        time_str = f"{elapsed_time:.2f} seconds"
    elif elapsed_time < 3600:
        minutes = int(elapsed_time // 60)
        seconds = elapsed_time % 60
        time_str = f"{minutes} min {seconds:.2f} sec"
    else:
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = elapsed_time % 60
        time_str = f"{hours} hr {minutes} min {seconds:.2f} sec"

    print(f"Total time:           {time_str}")

    # Print errors if any
    if stats['errors']:
        print("\nErrors encountered:")
        for error in stats['errors']:
            print(f"  - {error}")

    print("=" * 50)


def process_batch_file(batch_file_path):
    """
    Main batch processing orchestrator.

    Processes a batch file line-by-line, classifying each entry and routing it
    to the appropriate generator. Continues processing even if individual entries
    fail, collecting all errors for final reporting.

    Pipeline:
    1. Validate batch file exists and is readable
    2. Initialize statistics counters
    3. Process each line:
       - Classify entry type (SKIP, YOUTUBE, BLOG, INVALID)
       - Route to appropriate generator function (direct call)
       - Collect results and errors
    4. Print summary report with statistics

    Args:
        batch_file_path (str): Path to batch file containing entries to process

    Returns:
        bool: True if batch file was processed (may have individual entry errors),
              False if batch file couldn't be read

    Side Effects:
        - Prints progress messages during processing
        - Calls generator functions which create output files
        - Prints final summary report

    Example:
        success = process_batch_file("entries.txt")
        if not success:
            print("Failed to process batch file")
    """
    print(f"Processing batch file: {batch_file_path}\n")

    # Record start time
    start_time = time.time()

    # Initialize statistics tracking
    stats = {
        'total': 0,
        'processed_youtube': 0,
        'processed_blog': 0,
        'skipped': 0,
        'invalid': 0,
        'errors': []
    }

    try:
        with open(batch_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                stats['total'] += 1
                entry_type, title, url = _classify_entry(line)

                if entry_type == 'SKIP':
                    stats['skipped'] += 1
                    # Silent skip - no output for cleaner logs

                elif entry_type == 'INVALID':
                    stats['invalid'] += 1
                    error_msg = f"Line {line_num}: Invalid format - {line.strip()[:50]}"
                    stats['errors'].append(error_msg)
                    print(f"Line {line_num}: Skipping - Invalid format")

                elif entry_type == 'YOUTUBE':
                    entry = f"[{title}]({url})"
                    print(f"Line {line_num}: Processing YouTube - \"{title}\"")
                    success = _process_youtube(entry)
                    if success:
                        stats['processed_youtube'] += 1
                    else:
                        error_msg = f"Line {line_num}: YouTube processing failed - {title}"
                        stats['errors'].append(error_msg)

                elif entry_type == 'BLOG':
                    entry = f"[{title}]({url})"
                    print(f"Line {line_num}: Processing Blog - \"{title}\"")
                    success = _process_blog(entry)
                    if success:
                        stats['processed_blog'] += 1
                    else:
                        error_msg = f"Line {line_num}: Blog processing failed - {title}"
                        stats['errors'].append(error_msg)

    except FileNotFoundError:
        print(f"Error: Batch file not found: {batch_file_path}")
        return False
    except PermissionError:
        print(f"Error: Permission denied reading batch file: {batch_file_path}")
        return False
    except Exception as e:
        print(f"Error reading batch file: {e}")
        return False

    # Calculate elapsed time
    elapsed_time = time.time() - start_time

    # Print summary report
    _print_summary_report(stats, elapsed_time)

    return True


if __name__ == "__main__":
    """
    Main entry point for the batch processor script.

    Usage:
        python batch_processor.py <batch_file>

    Example:
        python batch_processor.py batch_entries.txt

    The script expects exactly one command-line argument: the path to a batch file
    containing entries to process. Each line in the batch file should be one of:
    - [title](youtube-url) for YouTube videos
    - [title](blog-url) for blog/articles
    - Empty line (skipped)
    - Line starting with # (markdown header, skipped)
    - Line starting with \\# (commentary, skipped)
    - Line with --- (separator, skipped)

    Exit codes:
        0: Batch file processed successfully (individual entries may have failed)
        1: Batch file could not be processed (file not found, permission error, etc.)
    """
    if len(sys.argv) != 2:
        print("Usage: python batch_processor.py <batch_file>")
        print("\nExample:")
        print("  python batch_processor.py batch_entries.txt")
        sys.exit(1)

    batch_file = sys.argv[1]
    success = process_batch_file(batch_file)
    sys.exit(0 if success else 1)
