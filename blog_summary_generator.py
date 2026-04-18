"""
Blog Summary Generator

This module processes blog/article URLs and generates structured markdown summaries.

Entry Format:
    [title](reference)

    Where:
    - title: The title under square brackets [title]
    - reference: The blog/article URL under round brackets (reference)
    - Note: YouTube URLs are explicitly skipped by this script

Output:
    Creates three folders if they don't exist:
    - output/ for all outputs
    - output/blog/ for storing fetched blog content
    - output/blog_generated/ for storing generated summary markdown files

    Creates a markdown file named "output/blog_generated/{title}.md" containing:
    - Link to the original article
    - Filtered summary (from fabric -p summarize)
    - Filtered extract wisdom (from fabric -p extract_wisdom)

External Dependencies:
    - fabric: AI-powered text processing tool with -u flag for URLs and patterns (summarize, extract_wisdom)

Example:
    python blog_summary_generator.py '[Article - More of Silicon Valley is building on free Chinese AI](https://www.nbcnews.com/tech/innovation/silicon-valley-building-free-chinese-ai-rcna242430)'
"""

import re
import sys
import os

from fabric_utils import (
    generate_toc,
    run_command,
    run_fabric_with_retry,
)


def process_blog_entry(entry):
    """
    Process a blog/article entry and generate summary file.

    Pipeline:
    1. Parse entry to extract title and reference (blog/article URL)
    2. Validate that reference is NOT a YouTube URL (YouTube URLs are skipped)
    3. Ensure output/, output/blog/, and output/blog_generated/ folders exist (create if needed)
    4. Fetch blog content via: fabric -u '{reference}' > 'output/blog/{title}.md'
    5. Get summary via: cat 'output/blog/{title}.md' | fabric -p summarize
    6. Get extract wisdom via: cat 'output/blog/{title}.md' | fabric -p extract_wisdom
    7. Filter <think></think> sections from both summaries
    8. Aggregate into structured markdown file

    Args:
        entry (str): Markdown-formatted entry in format "[title](reference)"

    Output File Structure:
        output/blog_generated/{title}.md containing:

        [Link]({reference})

        ---

        {filtered summary}

        ---
        ---
        ---

        {filtered extract_wisdom}

    Returns:
        None

    Example:
        entry = "[Article - More of Silicon Valley is building on free Chinese AI](https://www.nbcnews.com/tech/innovation/silicon-valley-building-free-chinese-ai-rcna242430)"
        process_blog_entry(entry)
        # Creates: "output/blog_generated/Article - More of Silicon Valley is building on free Chinese AI.md"
        #          "output/blog/Article - More of Silicon Valley is building on free Chinese AI.md"
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
    if 'youtube.com' in reference or 'youtu.be' in reference:
        print("This a YouTube reference, skipping...")
        return

    print(f"Processing: {title}")

    # Ensure output folders exist prior to generating files
    # Create subtitle/ and generated/ directories if they don't exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/blog", exist_ok=True)
    os.makedirs("output/blog_generated", exist_ok=True)

    # Get blog_file using fabric
    blog_file = f"output/blog/{title}.md"
    reference_cmd = f"""fabric -u "{reference}"  > "{blog_file}" """
    run_command(reference_cmd)
    print(f"... generated '{blog_file}' blog file \n")

    # Get summary using fabric's summarize pattern (retry + pseudo-header fallback)
    print("Getting Blog summary ...")
    summary_cmd = f"""cat "{blog_file}" | fabric -p summarize"""
    success, filtered_summary, header_summarize = run_fabric_with_retry(
        summary_cmd, "summarize")
    if not success:
        print("Error: fabric summarize failed; aborting")
        return
    print(f"... generated blog summary section \n")

    # Extract wisdom using fabric's extract_wisdom pattern
    print("Extracting Blog Wisdom ...")
    wisdom_cmd = f"""cat "{blog_file}" | fabric -p extract_wisdom"""
    success, filtered_extract_wisdom, header_wisdom = run_fabric_with_retry(
        wisdom_cmd, "extract_wisdom")
    if not success:
        print("Error: fabric extract_wisdom failed; aborting")
        return
    print(f"... generated blog extract wisdom section\n")

    # Generate TOC (only 2 sections for blog) from headers returned by retry helper
    print("Generating table of contents...")
    toc_content = generate_toc([header_summarize, header_wisdom])

    # Create filename from title
    # Filename format: output/blog_generated/{title}.md
    filename = f"""output/blog_generated/{title}.md"""

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
    # - {filtered extract_wisdom}
    # - Blank line

    # Build TOC section only if we have headers
    toc_section = f"\n{toc_content}\n\n---\n" if toc_content else ""

    content = f"""

[Link]({reference})

---
{toc_section}
{filtered_summary}

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
        python blog_summary_generator.py '[title](reference)'

    Example:
        python blog_summary_generator.py '[Article - More of Silicon Valley is building on free Chinese AI](https://www.nbcnews.com/tech/innovation/silicon-valley-building-free-chinese-ai-rcna242430)'


    The script expects exactly one command-line argument: a markdown-formatted entry
    containing the blog/article title in square brackets and the blog/article URL in round brackets.
    Note: YouTube URLs are skipped by this script.
    """
    if len(sys.argv) != 2:
        print("Usage: python blog_summary_generator.py '[title](reference)'")
        sys.exit(1)

    entry = sys.argv[1]
    process_blog_entry(entry)
