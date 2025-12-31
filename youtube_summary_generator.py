"""
YouTube Summary Generator

This module processes YouTube video entries and generates structured markdown summaries.

Entry Format:
    [title](reference)

    Where:
    - title: The title under square brackets [title]
    - reference: The YouTube URL under round brackets (reference)

Output:
    Creates two folders if they don't exist:
    - subtitle/ for storing YouTube subtitle files
    - generated/ for storing generated markdown files

    Creates a markdown file named "generated/{title}.md" containing:
    - Link to the original video
    - Filtered summary (from fabric -p summarize)
    - Filtered YouTube summary (from fabric -p youtube_summary)
    - Filtered extract wisdom (from fabric -p extract_wisdom)

External Dependencies:
    - fabric: AI-powered text processing tool with -y flag and patterns (summarize, youtube_summary, extract_wisdom)
    - yt-dlp: YouTube metadata extraction tool for retrieving channel information

Example:
    python youtube_summary_generator.py "[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)"
"""

import subprocess
import re
import sys
import os
import yt_dlp


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


def _run_command(command):
    """
    Run a bash command and return the output.

    Executes shell commands for retrieving YouTube transcripts and processing them
    through fabric patterns.

    Args:
        command (str): The bash command to execute

    Returns:
        str: Command stdout if successful, empty string on error

    Example Commands:
        - "fabric -y '<youtube_url>' --transcript-with-timestamps > 'subtitle/{title}.txt'"
        - "cat 'subtitle/{title}.txt' | fabric -p summarize"
        - "cat 'subtitle/{title}.txt' | fabric -p youtube_summary"
        - "cat 'subtitle/{title}.txt' | fabric -p extract_wisdom"
    """
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Error running command: {command}")
            print(f"Error output: {result.stderr}")
            return ""
    except Exception as e:
        print(f"Exception running command: {e}")
        return ""


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
        print(f"Warning: Could not extract channel info: {e}")
        return None, None


def process_youtube_entry(entry):
    """
    Process a YouTube entry and generate summary file.

    Pipeline:
    1. Parse entry to extract title and reference (YouTube URL)
    2. Validate that reference is a YouTube URL
    3. Extract YouTube channel information (author name and channel URL) using yt-dlp
    4. Ensure subtitle/ and generated/ folders exist (create if needed)
    5. Get transcript via: fabric -y '{reference}' --transcript-with-timestamps > 'subtitle/{title}.txt'
    6. Get summary via: cat 'subtitle/{title}.txt' | fabric -p summarize
    7. Get YouTube summary via: cat 'subtitle/{title}.txt' | fabric -p youtube_summary
    8. Get extract wisdom via: cat 'subtitle/{title}.txt' | fabric -p extract_wisdom
    9. Filter <think></think> sections from all three summaries
    10. Aggregate into structured markdown file

    Args:
        entry (str): Markdown-formatted entry in format "[title](reference)"

    Output File Structure:
        generated/{title}.md containing:

        [{author_name}]({channel_url})
        [Link]({reference})

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

    # Ensure output folders exist prior to generating files
    # Create subtitle/ and generated/ directories if they don't exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/subtitle", exist_ok=True)
    os.makedirs("output/yt_generated", exist_ok=True)

    # Get transcript using fabric
    subtitle_file = f"output/subtitle/{title}.txt"
    reference_cmd = f"""fabric -y "{reference}" --transcript-with-timestamps > "{subtitle_file}" """
    source_information = _run_command(reference_cmd)
    print(f"""... generated "{subtitle_file}" subtitle file \n""")

    # Get summary using fabric's summarize pattern
    # Command: fabric -p summarize source_information
    print("Getting summary ...")
    summary_cmd = f"""cat "{subtitle_file}" | fabric -p summarize"""
    summary = _run_command(summary_cmd)
    filtered_summary = _filter_think_sections(summary)
    print(f"""... generated summary section \n""")

    # Get YouTube summary using fabric's youtube_summary pattern
    # Command: fabric -p youtube_summary
    print("Getting YouTube summary...")
    yt_summary_cmd = f"""cat "{subtitle_file}" | fabric -p youtube_summary"""
    youtube_summary = _run_command(yt_summary_cmd)
    filtered_youtube_summary = _filter_think_sections(youtube_summary)
    print(f"""... generated youtube summary section""")

    
    # Extract wisdom using fabric's extract_wisdom pattern
    # Command: fabric -p extract_wisdom
    print("Extracting YouTube Wisdom ...")
    yt_summary_cmd = f"""cat "{subtitle_file}" | fabric -p extract_wisdom"""
    extract_wisdom = _run_command(yt_summary_cmd)
    filtered_extract_wisdom = _filter_think_sections(extract_wisdom)
    print(f"""... generated youtube summary section""")

    # Extract first level 1 header from each section for TOC
    print("Generating table of contents...")
    header_summarize = _extract_first_level1_header(filtered_summary)
    header_youtube = _extract_first_level1_header(filtered_youtube_summary)
    header_wisdom = _extract_first_level1_header(filtered_extract_wisdom)

    # Generate TOC
    toc_content = _generate_toc([header_summarize, header_youtube, header_wisdom])

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

    content = f"""[{author_name}]({channel_url})
[Link]({reference})

---
{toc_section}
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
