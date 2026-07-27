"""
Blog Summary Generator

This module processes blog/article URLs and generates structured markdown summaries.

Entry Format:
    [title](reference)   or   a bare article URL

    Where:
    - title: The title under square brackets [title]
    - reference: The blog/article URL under round brackets (reference)
    - Note: YouTube URLs are explicitly skipped by this script

    A bare URL carries no title, so the page is fetched and its og:title (or
    <title>) is used, cleaned to the vault's filename conventions.

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
import shlex
import sys
import os

from fabric_utils import (
    generate_toc,
    page_title,
    run_command,
    context_check,
    MAX_INPUT_TOKENS,
    run_fabric_with_retry,
    timeout_for,
)

# A line that is nothing but a URL -- the title has to come from the page itself.
BARE_URL_RE = re.compile(r'^https?://\S+$')


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
    # Expected format: [title](reference), or a bare URL with no title at all
    entry = entry.strip()
    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', entry)
    if match:
        title = match.group(1).strip()
        reference = match.group(2).strip()
    elif BARE_URL_RE.match(entry):
        title = None            # filled in from the page's own metadata below
        reference = entry
    else:
        print("Invalid entry format. Expected: [title](reference) or a bare URL")
        return

    # Check if it's a YouTube reference (youtube.com or youtu.be)
    if 'youtube.com' in reference or 'youtu.be' in reference:
        print("This a YouTube reference, skipping...")
        return

    # A bare-URL entry has no title to name files with. Bail rather than write
    # to a placeholder filename that no later run would ever match.
    if title is None:
        print("Fetching article title...")
        title = page_title(reference)
        if not title:
            print(f"\n!!! TITLE ERROR: could not fetch a title for {reference}\n")
            return False
        print(f"Title from page: {title}")

    print(f"Processing: {title}")

    # Ensure output folders exist prior to generating files
    # Create subtitle/ and generated/ directories if they don't exist
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/blog", exist_ok=True)
    os.makedirs("output/blog_generated", exist_ok=True)

    # Get blog_file using fabric. shlex.quote prevents shell expansion of
    # $$, $VAR, backticks etc. in title-derived filenames or URLs.
    blog_file = f"output/blog/{title}.md"
    blog_q = shlex.quote(blog_file)
    reference_q = shlex.quote(reference)
    reference_cmd = f"fabric -u {reference_q}  > {blog_q}"
    run_command(reference_cmd)
    print(f"... generated '{blog_file}' blog file \n")
    fabric_timeout = timeout_for(blog_file)

    # A long-form article can outrun the window too; truncation there is silent.
    fits, est_tokens = context_check(blog_file)
    if not fits:
        print(f"\n!!! TOO LARGE: {title}\n    ~{est_tokens:,} tokens exceeds the "
              f"{MAX_INPUT_TOKENS:,}-token input budget\n")
        return

    # Get summary using fabric's summarize pattern (retry + pseudo-header fallback)
    print("Getting Blog summary ...")
    summary_cmd = f"cat {blog_q} | fabric -p summarize"
    success, filtered_summary, header_summarize = run_fabric_with_retry(
        summary_cmd, "summarize", timeout=fabric_timeout)
    if not success:
        print("Error: fabric summarize failed; aborting")
        return
    print(f"... generated blog summary section \n")

    # Extract wisdom using fabric's extract_wisdom pattern
    print("Extracting Blog Wisdom ...")
    wisdom_cmd = f"cat {blog_q} | fabric -p extract_wisdom"
    success, filtered_extract_wisdom, header_wisdom = run_fabric_with_retry(
        wisdom_cmd, "extract_wisdom", timeout=fabric_timeout)
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
