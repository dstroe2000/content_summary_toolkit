"""
YouTube Summary Generator

This module processes YouTube video entries and generates structured markdown summaries.

Entry Format:
    [title](reference)

    Where:
    - title: The title under square brackets [title]
    - reference: The YouTube URL under round brackets (reference)

Output:
    Creates three folders if they don't exist:
    - output/ for all outputs
    - output/subtitle/ for storing YouTube subtitle files
    - output/yt_generated/ for storing generated markdown files

    Creates a markdown file named "output/yt_generated/{title}.md" containing:
    - Channel name and URL
    - Link to the original video
    - Table of Contents
    - Video description (original creator's description via yt-dlp)
    - Filtered summary (from fabric -p summarize)
    - Filtered YouTube summary (from fabric -p youtube_summary)
    - Filtered extract wisdom (from fabric -p extract_wisdom)

External Dependencies:
    - fabric: AI-powered text processing tool with -y flag and patterns (summarize, youtube_summary, extract_wisdom)
    - yt-dlp: YouTube metadata and description extraction tool

Example:
    python youtube_summary_generator.py "[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)"
"""

import subprocess
import re
import sys
import os
import yt_dlp

from fabric_utils import (
    generate_toc,
    run_command,
    run_fabric_with_retry,
    ytdlp_cookie_cli,
    ytdlp_cookie_opts,
    ytdlp_meta_opts,
)


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
            **ytdlp_meta_opts(),
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
        print(f"Warning: Could not extract channel info: {e}")
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
        cookie_flag = ytdlp_cookie_cli()
        command = f'yt-dlp {cookie_flag} --get-description "{video_url}"'.strip()
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Warning: Could not extract video description")
            print(f"Error output: {result.stderr}")
            return ""
    except Exception as e:
        print(f"Warning: Could not extract video description: {e}")
        return ""


def process_youtube_entry(entry):
    """
    Process a YouTube entry and generate summary file.

    Pipeline:
    1. Parse entry to extract title and reference (YouTube URL)
    2. Validate that reference is a YouTube URL
    3. Extract YouTube channel information (author name and channel URL) using yt-dlp
    4. Extract video description using yt-dlp
    5. Ensure subtitle/ and generated/ folders exist (create if needed)
    6. Get transcript via: fabric -y '{reference}' --transcript-with-timestamps > 'subtitle/{title}.txt'
    7. Get summary via: cat 'subtitle/{title}.txt' | fabric -p summarize
    8. Get YouTube summary via: cat 'subtitle/{title}.txt' | fabric -p youtube_summary
    9. Get extract wisdom via: cat 'subtitle/{title}.txt' | fabric -p extract_wisdom
    10. Filter <think></think> sections from all three summaries
    11. Generate Table of Contents from section headers
    12. Aggregate into structured markdown file

    Args:
        entry (str): Markdown-formatted entry in format "[title](reference)"

    Output File Structure:
        generated/{title}.md containing:

        [{author_name}]({channel_url})
        [Link]({reference})

        ---

        ### TOC
        - [[#ONE SENTENCE SUMMARY]]
        - [[#Summary: {title}]]
        - [[#SUMMARY]]

        ---

        {video_description}

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

    Returns:
        None

    Example:
        entry = "[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)"
        process_youtube_entry(entry)
        # Creates: "generated/Learn RAG From Scratch.md" and "subtitle/Learn RAG From Scratch.txt"
    """

    # Parse the entry to extract title and reference
    # Expected format: [title](reference)
    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', entry.strip())
    if not match:
        print("Invalid entry format. Expected: [title](reference)")
        return

    title = match.group(1).strip()
    reference = match.group(2).strip()

    # Check if it's a YouTube reference (youtube.com or youtu.be)
    if 'youtube.com' not in reference and 'youtu.be' not in reference:
        print("Not a YouTube reference, skipping...")
        return

    print(f"Processing: {title}")

    # Extract YouTube channel information using yt-dlp
    print("Extracting channel information...")
    author_name, channel_url = _get_youtube_channel_info(reference)
    if author_name and channel_url:
        print(f"Channel: {author_name} ({channel_url})")
    else:
        print("Warning: Could not extract channel information, using defaults")
        author_name = "Unknown"
        channel_url = ""

    # Extract video description using yt-dlp
    print("Extracting video description...")
    video_description = _get_youtube_description(reference)
    if video_description:
        print(f"Description extracted ({len(video_description)} characters)")
    else:
        print("Warning: Could not extract video description")
        video_description = ""

    # Ensure output folders exist prior to generating files
    # Create subtitle/ and generated/ directories if they don't exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/subtitle", exist_ok=True)
    os.makedirs("output/yt_generated", exist_ok=True)

    # Get transcript using fabric
    subtitle_file = f"output/subtitle/{title}.txt"
    reference_cmd = f"""fabric -y "{reference}" --transcript-with-timestamps > "{subtitle_file}" """
    run_command(reference_cmd)
    print(f"""... generated "{subtitle_file}" subtitle file \n""")

    # Get summary using fabric's summarize pattern (retry + pseudo-header fallback)
    print("Getting summary ...")
    summary_cmd = f"""cat "{subtitle_file}" | fabric -p summarize"""
    success, filtered_summary, header_summarize = run_fabric_with_retry(
        summary_cmd, "summarize")
    if not success:
        print("Error: fabric summarize failed; aborting")
        return
    print(f"""... generated summary section \n""")

    # Get YouTube summary using fabric's youtube_summary pattern
    print("Getting YouTube summary...")
    yt_summary_cmd = f"""cat "{subtitle_file}" | fabric -p youtube_summary"""
    success, filtered_youtube_summary, header_youtube = run_fabric_with_retry(
        yt_summary_cmd, "youtube_summary")
    if not success:
        print("Error: fabric youtube_summary failed; aborting")
        return
    print(f"""... generated youtube summary section""")

    # Extract wisdom using fabric's extract_wisdom pattern
    print("Extracting YouTube Wisdom ...")
    wisdom_cmd = f"""cat "{subtitle_file}" | fabric -p extract_wisdom"""
    success, filtered_extract_wisdom, header_wisdom = run_fabric_with_retry(
        wisdom_cmd, "extract_wisdom")
    if not success:
        print("Error: fabric extract_wisdom failed; aborting")
        return
    print(f"""... generated extract_wisdom section""")

    # Generate TOC from headers returned by retry helper
    print("Generating table of contents...")
    toc_content = generate_toc([header_summarize, header_youtube, header_wisdom])

    # Create filename from title
    # Filename format: generated/{title}.md
    filename = f"""output/yt_generated/{title}.md"""

    # Create the content following the specified structure
    # Structure per specification:
    # - [{author_name}]({channel_url})
    # - [Link]({reference})
    # - Blank line
    # - ---
    # - Blank line
    # - {filtered summary}
    # - Blank line
    # - --- --- ---
    # - Blank line
    # - {filtered youtube_summary}
    # - Blank line
    # - --- --- ---
    # - Blank line
    # - {filtered extract_wisdom}
    # - Blank line

    # Build TOC section only if we have headers
    toc_section = f"\n{toc_content}\n\n---\n" if toc_content else ""

    # Build video description section if available
    description_section = f"\n{video_description}\n\n---\n" if video_description else ""

    content = f"""[{author_name}]({channel_url})
[Link]({reference})

---
{toc_section}{description_section}
{filtered_summary}

---
---
---

{filtered_youtube_summary}

---
---
---

{filtered_extract_wisdom}

"""

    # Write the file to disk
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"""
Created file: '{filename}'
--- 

""")
    except Exception as e:
        print(f"Error writing file: {e}")


if __name__ == "__main__":
    """
    Main entry point for the script.

    Usage:
        python youtube_summary_generator.py '[title](reference)'

    Example:
        python youtube_summary_generator.py '[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)'

        or

        python youtube_summary_generator.py '[I Didn’t Expect the 1010music Bento To Be This Good](https://www.youtube.com/watch?v=n1u6mEnK1ns)'

    The script expects exactly one command-line argument: a markdown-formatted entry
    containing the video title in square brackets and the YouTube URL in round brackets.
    """
    if len(sys.argv) != 2:
        print("Usage: python youtube_summary_generator.py '[title](reference)'")
        sys.exit(1)

    entry = sys.argv[1]
    process_youtube_entry(entry)
