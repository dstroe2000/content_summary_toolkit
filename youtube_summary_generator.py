"""
YouTube Summary Generator

This module processes YouTube video entries and generates structured markdown summaries.

Entry Format:
    [title](reference)   or   a bare YouTube URL

    Where:
    - title: The title under square brackets [title]
    - reference: The YouTube URL under round brackets (reference)

    A bare URL carries no title, so the title is taken from yt-dlp metadata
    (same call that fetches channel + description) and run through
    fabric_utils.clean_title() to match the vault's filename conventions.

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
    python youtube_summary_generator.py "https://www.youtube.com/watch?v=sVcwVQRHIc8"
"""

import re
import shlex
import sys
import os

from fabric_utils import (
    FabricTimeout,
    clean_title,
    fetch_transcript,
    generate_toc,
    context_check,
    stripped_input,
    MAX_INPUT_TOKENS,
    MODEL_CONTEXT_TOKENS,
    run_fabric_with_retry,
    timeout_for,
    youtube_meta,
)

# A line that is nothing but a URL -- the title has to come from the source.
BARE_URL_RE = re.compile(r'^https?://\S+$')

# Status returned by process_youtube_entry() when the transcript could not be
# fetched, so the batch runner can count subtitle failures separately.
SUBTITLE_ERROR = "subtitle_error"

# Status returned when the transcript is too long for the backend's context
# window. Distinct from a timeout: nothing stalled, the input simply cannot be
# sent whole, and sending it anyway buys a summary of a silently cropped
# transcript.
OVERSIZED_ERROR = "oversized_error"


def process_youtube_entry(entry):
    """
    Process a YouTube entry and generate summary file.

    Pipeline:
    1. Parse entry to extract title and reference (YouTube URL)
    2. Validate that reference is a YouTube URL
    3. Extract channel name, channel URL and description in one yt-dlp call
    4. Ensure subtitle/ and generated/ folders exist (create if needed)
    5. Get transcript via yt-dlp into 'subtitle/{title}.txt' (reused if already present)
    6. Check the transcript fits the backend context window (timestamps stripped)
    7. Get summary via: <de-timestamped subtitle> | fabric -p summarize
    8. Get YouTube summary via: <de-timestamped subtitle> | fabric -p youtube_summary
    9. Get extract wisdom via: <de-timestamped subtitle> | fabric -p extract_wisdom
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
    # Expected format: [title](reference), or a bare URL with no title at all
    entry = entry.strip()
    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', entry)
    if match:
        title = match.group(1).strip()
        reference = match.group(2).strip()
    elif BARE_URL_RE.match(entry):
        title = None            # filled in from yt-dlp metadata below
        reference = entry
    else:
        print("Invalid entry format. Expected: [title](reference) or a bare URL")
        return

    # Check if it's a YouTube reference (youtube.com or youtu.be)
    if 'youtube.com' not in reference and 'youtu.be' not in reference:
        print("Not a YouTube reference, skipping...")
        return

    print(f"Processing: {title or reference}")

    # Channel info, description and title ship in the same yt-dlp payload; one call.
    print("Extracting channel information and description...")
    author_name, channel_url, video_description, meta_title = youtube_meta(reference)

    # A bare-URL entry has no title to name files with. Bail rather than write
    # to a placeholder filename that no later run would ever match.
    if title is None:
        title = clean_title(meta_title)
        if not title:
            print(f"\n!!! TITLE ERROR: could not fetch a title for {reference}\n")
            return 'error'
        print(f"Title from yt-dlp: {title}")
    if channel_url:
        print(f"Channel: {author_name} ({channel_url})")
    else:
        print("Warning: Could not extract channel information, using defaults")
    if video_description:
        print(f"Description extracted ({len(video_description)} characters)")
    else:
        print("Warning: Could not extract video description")

    # Ensure output folders exist prior to generating files
    # Create subtitle/ and generated/ directories if they don't exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/subtitle", exist_ok=True)
    os.makedirs("output/yt_generated", exist_ok=True)

    # Get transcript via yt-dlp (cookie-authenticated). shlex.quote prevents shell
    # expansion of $$, $VAR, backticks etc. in title-derived filenames or URLs.
    subtitle_file = f"output/subtitle/{title}.txt"
    ok, reason = fetch_transcript(reference, subtitle_file)

    # Abort before the fabric patterns: summarizing an empty transcript yields a
    # confidently fabricated note, which is worse than no note at all.
    if not ok or os.path.getsize(subtitle_file) == 0:
        print(f"\n!!! SUBTITLE ERROR: {title}\n    {reason or 'empty transcript file'}\n")
        if os.path.exists(subtitle_file) and os.path.getsize(subtitle_file) == 0:
            os.remove(subtitle_file)
        return SUBTITLE_ERROR
    print(f"""... generated "{subtitle_file}" subtitle file \n""")

    # Transcript size is the lever behind most fabric timeouts, so carry it
    # into any timeout raised below.
    transcript_kb = os.path.getsize(subtitle_file) / 1024
    fabric_timeout = timeout_for(subtitle_file)

    # Timestamps are dropped from every fabric pipe below (~35% of the tokens),
    # so the fit check must measure what actually gets sent.
    fits, est_tokens = context_check(subtitle_file)
    if not fits:
        print(f"\n!!! TOO LARGE: {title}\n    ~{est_tokens:,} tokens exceeds the "
              f"{MAX_INPUT_TOKENS:,}-token input budget "
              f"({MODEL_CONTEXT_TOKENS:,} context window)\n")
        return OVERSIZED_ERROR
    print(f"Transcript: {transcript_kb:.0f} KB, ~{est_tokens:,} tokens "
          f"(timeouts at {fabric_timeout}s)")

    with stripped_input(subtitle_file) as subtitle_in:
        try:
            # Get summary using fabric's summarize pattern (retry + pseudo-header fallback)
            print("Getting summary ...")
            summary_cmd = f"{subtitle_in} | fabric -p summarize"
            success, filtered_summary, header_summarize = run_fabric_with_retry(
                summary_cmd, "summarize", timeout=fabric_timeout)
            if not success:
                print("Error: fabric summarize failed; aborting")
                return
            print(f"""... generated summary section \n""")

            # Get YouTube summary using fabric's youtube_summary pattern
            print("Getting YouTube summary...")
            yt_summary_cmd = f"{subtitle_in} | fabric -p youtube_summary"
            success, filtered_youtube_summary, header_youtube = run_fabric_with_retry(
                yt_summary_cmd, "youtube_summary", timeout=fabric_timeout)
            if not success:
                print("Error: fabric youtube_summary failed; aborting")
                return
            print(f"""... generated youtube summary section""")

            # Extract wisdom using fabric's extract_wisdom pattern
            print("Extracting YouTube Wisdom ...")
            wisdom_cmd = f"{subtitle_in} | fabric -p extract_wisdom"
            success, filtered_extract_wisdom, header_wisdom = run_fabric_with_retry(
                wisdom_cmd, "extract_wisdom", timeout=fabric_timeout)
            if not success:
                print("Error: fabric extract_wisdom failed; aborting")
                return
            print(f"""... generated extract_wisdom section""")
        except FabricTimeout as e:
            e.title = title
            e.transcript_kb = transcript_kb
            print(f"\n!!! TIMEOUT: {title}\n    {e} on a {transcript_kb:.0f} KB transcript\n")
            raise

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
