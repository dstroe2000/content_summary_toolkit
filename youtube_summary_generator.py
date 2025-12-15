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

Example:
    python youtube_summary_generator.py "[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)"
"""

import subprocess
import re
import sys
import os


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


def process_youtube_entry(entry):
    """
    Process a YouTube entry and generate summary file.

    Pipeline:
    1. Parse entry to extract title and reference (YouTube URL)
    2. Validate that reference is a YouTube URL
    3. Ensure subtitle/ and generated/ folders exist (create if needed)
    4. Get transcript via: fabric -y '{reference}' --transcript-with-timestamps > 'subtitle/{title}.txt'
    5. Get summary via: cat 'subtitle/{title}.txt' | fabric -p summarize
    6. Get YouTube summary via: cat 'subtitle/{title}.txt' | fabric -p youtube_summary
    7. Get extract wisdom via: cat 'subtitle/{title}.txt' | fabric -p extract_wisdom
    8. Filter <think></think> sections from all three summaries
    9. Aggregate into structured markdown file

    Args:
        entry (str): Markdown-formatted entry in format "[title](reference)"

    Output File Structure:
        generated/{title}.md containing:

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

    # Create filename from title
    # Filename format: generated/{title}.md
    filename = f"""output/yt_generated/{title}.md"""

    # Create the content following the specified structure
    # Structure per specification:
    # - Blank line
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
    content = f"""

[Link]({reference})

---

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
