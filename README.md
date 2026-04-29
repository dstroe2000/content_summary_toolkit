# Content Summary Toolkit

A batch content summarizer that processes YouTube videos, blog articles, and local subtitle files (SRT/VTT/etc.) using AI-powered summarization through the [fabric](https://github.com/danielmiessler/fabric) tool.

## Overview

This tool helps you process a backlog of content by automatically generating structured markdown summaries. It extracts transcripts from YouTube videos, fetches blog content, processes local subtitle files, and creates comprehensive summaries using multiple AI patterns.

## Features

- **Batch Processing**: Process multiple entries from a single batch file
- **Multi-Format Support**: Handles YouTube videos, blog articles, and local subtitle files
- **AI-Powered Summaries**: Uses fabric's AI patterns for intelligent summarization
- **Multiple Summary Types**: Generates different perspectives on content:
  - General summary
  - YouTube-specific summary (for videos and subtitles)
  - Extracted wisdom and insights
- **Rich Metadata Extraction** (YouTube only):
  - Channel information with modern handle format (`@username`)
  - Video descriptions from creators
  - Auto-generated Table of Contents (TOC)
- **Local Subtitle Flow**: Recursively process folders of `.srt` / `.vtt` / `.sub` / `.sbv` / `.txt` files without YouTube lookups
- **Resilient to Fabric Output Drift**: Shared retry + pseudo-header promotion so dropped `# ` prefixes never break TOC anchors
- **Organized Output**: Structured folder hierarchy for easy navigation
- **Legacy Patcher**: Patch existing files with missing channel info, descriptions, and pseudo-header self-heal
- **Content Upgrader**: Upgrade older note formats to current template with validation + retry
- **Comprehensive Reporting**: Detailed statistics and success metrics
- **Error Resilient**: Continues processing even if individual entries fail

## Prerequisites

- Python 3.x
- [fabric](https://github.com/danielmiessler/fabric) - AI-powered text processing tool
  - Must be installed and configured with API access
  - Requires patterns: `summarize`, `youtube_summary`, `extract_wisdom`
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - YouTube metadata extraction
  - Used to extract channel information from YouTube videos
  - Authenticates via `--cookies-from-browser` to handle age-gated, members-only,
    or rate-limited videos. Default browser is `chrome`; override with env var
    `YTDLP_COOKIES_BROWSER` (e.g. `firefox`, `brave`, `edge`, `safari`) or set
    it to empty string to disable cookie pulling.

### Browser cookie pre-conditions

The toolkit pulls YouTube auth cookies from a real browser profile via
`yt-dlp --cookies-from-browser`. Set this up once before running:

1. **Install the browser** matching `YTDLP_COOKIES_BROWSER` (default `chrome`).
   On macOS: `brew install --cask google-chrome` (or `firefox`, `brave-browser`,
   `microsoft-edge`). Safari is built-in.
2. **Sign into YouTube** (i.e. into your Google account) in that browser at
   <https://youtube.com>. The cookie jar must contain a live YouTube session
   — fresh installs with no login produce empty cookies and yt-dlp will
   silently fall back to anonymous requests, defeating the point.
3. **Use the default profile** unless you override it. yt-dlp reads the
   browser's default profile by default; if you keep YouTube login in a
   non-default Chrome profile, set
   `YTDLP_COOKIES_BROWSER="chrome:Profile 1"` (yt-dlp accepts a
   `BROWSER[:PROFILE]` form).
4. **macOS Keychain prompt** (Chrome / Edge / Brave only): the first time
   yt-dlp reads cookies, macOS pops a Keychain prompt asking to release the
   "Chrome Safe Storage" password. Click *Always Allow* so subsequent runs
   are non-interactive. Firefox and Safari do not require this.
5. **Linux Chrome / Brave**: Chromium-family browsers may need to be
   **closed** for yt-dlp to read the cookie SQLite DB on Linux (file lock).
   Firefox can be read while open. macOS Chrome can be read while open on
   recent yt-dlp.
6. **Stay logged in**: if Google logs you out (password change, 2FA reset,
   browser cookie clear), re-login in the browser before next run.

To disable cookie pulling entirely (e.g. CI without a browser), export
`YTDLP_COOKIES_BROWSER=""`. Public videos still work without cookies.

## Installation

1. Clone this repository
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Ensure fabric is installed and configured:
   ```bash
   # Install fabric (follow fabric's installation guide)
   # https://github.com/danielmiessler/fabric
   ```

## Usage

### Batch Processing

Process a batch file containing multiple entries:

```bash
python content_summary_toolkit.py batch_entries.txt
```

### Individual Processing

Process a single YouTube video:
```bash
python youtube_summary_generator.py '[Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)'
```

Process a single blog article:
```bash
python blog_summary_generator.py '[Article Title](https://example.com/article)'
```

### Local Subtitle Folder

Recursively summarize every subtitle file under a directory — no YouTube
fetching, no channel lookup, no description. Outputs `{name}.summary.md`
alongside each source file:

```bash
# Process a whole course folder (all .srt/.vtt/.sub/.sbv/.txt)
python subtitle_summary_generator.py /path/to/subtitles

# Dry-run — list what would be processed
python subtitle_summary_generator.py /path/to/subtitles --dry-run

# Overwrite existing .summary.md outputs
python subtitle_summary_generator.py /path/to/subtitles --overwrite --verbose

# Limit to specific extensions
python subtitle_summary_generator.py /path/to/subtitles --extensions .srt .vtt
```

Each `.summary.md` contains the standard TOC + 3 fabric sections
(`summarize` / `youtube_summary` / `extract_wisdom`). Previously-produced
`.summary.txt` files from older versions are also skipped on re-scan.

### Upgrading Legacy Notes

Upgrade existing YouTube notes in an Obsidian vault to the current
template — detects partial/legacy shapes and runs only the missing fabric
patterns:

```bash
# Dry-run classification
python youtube_content_upgrader.py --folder /path/to/Youtube --dry-run

# Process one category, limited to N files for testing
python youtube_content_upgrader.py --folder /path/to/Youtube --category 2 --limit 5

# Process every upgradable file
python youtube_content_upgrader.py --folder /path/to/Youtube --category all --verbose
```

### Patching Legacy Files

Patch existing YouTube summary files with missing channel info and video descriptions:
```bash
# Patch all files in default folder (output/yt_generated/)
python youtube_summary_patcher.py

# Preview changes without modifying files
python youtube_summary_patcher.py --dry-run --verbose

# Update only channel info (skip video descriptions)
python youtube_summary_patcher.py --skip-description

# Patch files in custom folder
python youtube_summary_patcher.py --folder /path/to/folder
```

## Batch File Format

Create a text file with entries in markdown link format. The processor supports:

**Supported Entries:**
- **YouTube videos**: `[Video Title](https://youtube.com/watch?v=...)`
- **Blog articles**: `[Article Title](https://example.com/article)`
- **Markdown headers**: `# Section Name` (skipped)
- **Commentary**: `\# This is a comment` (skipped)
- **Separators**: `---` (skipped)
- **Empty lines** (skipped)

**Example batch_entries.txt:**
```markdown
# AI and Machine Learning

[Learn RAG From Scratch – Python AI Tutorial from a LangChain Engineer](https://www.youtube.com/watch?v=sVcwVQRHIc8)

[Article - More of Silicon Valley is building on free Chinese AI](https://www.nbcnews.com/tech/innovation/silicon-valley-building-free-chinese-ai-rcna242430)

---

# Web Development

\# This is a note to self - check this later

[Building Modern Web Apps](https://example.com/modern-web-apps)
```

## Output Structure

The URL-driven flows (YouTube + blog) create an organized folder structure
under the current directory:

```
output/
├── subtitle/              # YouTube transcripts
│   └── {video-title}.txt
├── yt_generated/          # YouTube summaries
│   └── {video-title}.md
├── blog/                  # Fetched blog content
│   └── {article-title}.md
└── blog_generated/        # Blog summaries
    └── {article-title}.md
```

The local subtitle flow (`subtitle_summary_generator.py`) writes its
output **in-place** next to each source file — no central folder:

```
/path/to/subtitles/
├── 01 - Intro.srt
├── 01 - Intro.srt.summary.md     ← generated
├── 02 - Setup.srt
├── 02 - Setup.srt.summary.md     ← generated
└── subfolder/
    ├── 03 - Next.vtt
    └── 03 - Next.vtt.summary.md  ← generated
```

## Summary Output Format

### YouTube Videos
Each generated summary contains:
1. **Channel author link** (name and URL extracted via yt-dlp)
   - Prefers modern handle format (`@username`) over legacy channel ID
2. **Link to original video**
3. **Table of Contents** - Auto-generated from section headers
4. **Video Description** - Original description from the creator
5. **General summary** - AI-generated overview
6. **YouTube-specific summary** - Detailed breakdown
7. **Extracted wisdom** - Key insights and takeaways

**Example Output Structure:**
```markdown
[Channel Name](https://www.youtube.com/@channelname)
[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

### TOC
- [[#ONE SENTENCE SUMMARY]]
- [[#Summary: Title]]
- [[#SUMMARY]]

---

Video description text here...

---

# ONE SENTENCE SUMMARY:
...

---
---
---

# Summary: Title
...

---
---
---

# SUMMARY
...
```

### Blog Articles
Each generated summary contains:
1. Link to original article
2. General summary
3. Extracted wisdom

All summaries automatically filter out AI thinking process (`<think>` tags).

## Processing Report

After batch processing completes, you'll see a comprehensive report:

```
==================================================
Batch Processing Summary
==================================================
Total lines:           25
YouTube processed:     8
Blog processed:        12
Skipped:              3
Invalid format:       1
Errors:               1
Success rate:         95.2%
Total time:           5 min 23.45 sec
==================================================
```

## Architecture

The project is one shared helper module plus six entry-point scripts:

1. **fabric_utils.py**: Shared helper module (internal)
   - `filter_think_sections` — strip `<think>...</think>` blocks
   - `extract_first_level1_header` — read first `# ` header from markdown
   - `generate_toc` — build `### TOC` with `[[#header]]` wikilinks
   - `promote_pseudo_header` — recover when fabric drops the leading `# ` on a heading
   - `run_command` — shell runner returning `(success, output)` with optional timeout
   - `run_fabric_with_retry` — runs a fabric pattern, retries up to `MAX_FABRIC_ATTEMPTS=3` when validation fails, falls back to `promote_pseudo_header` to recover deterministic dropouts. Accepts a pluggable validator so each tool can enforce its own quality bar.

2. **content_summary_toolkit.py**: Main orchestrator
   - Parses batch files
   - Routes entries to appropriate generators (YouTube vs blog)
   - Tracks statistics and generates reports

3. **youtube_summary_generator.py**: YouTube processor
   - Extracts channel information using `yt-dlp`
   - Extracts video descriptions using `yt-dlp --get-description`
   - Downloads transcripts using `fabric -y`
   - Runs 3 fabric patterns with retry + pseudo-header fallback
   - Generates TOC from section headers
   - Creates structured markdown output with full metadata

4. **blog_summary_generator.py**: Blog processor
   - Fetches blog content using `fabric -u`
   - Runs 2 fabric patterns with retry + pseudo-header fallback
   - Creates structured markdown output

5. **subtitle_summary_generator.py**: Local subtitle processor
   - Recursively scans a folder for `.srt` / `.sub` / `.vtt` / `.sbv` / `.txt`
   - Skips files that already have `.summary.md` (or legacy `.summary.txt`) alongside them
   - Runs 3 fabric patterns with retry + pseudo-header fallback
   - Writes `{source}.summary.md` in place
   - Flags: `--overwrite`, `--dry-run`, `--verbose`, `--extensions`

6. **youtube_content_upgrader.py**: Content upgrader
   - Classifies existing notes into categories (old-fabric, bare-content, near-compliant)
   - Runs only the missing fabric patterns per category
   - Enforces strict per-pattern validation (minimum line counts, required sub-headers)
   - Falls back to pseudo-header promotion after retries exhaust

7. **youtube_summary_patcher.py**: Legacy file patcher
   - Patches existing YouTube summary files to current format
   - Adds missing channel information (yt-dlp)
   - Generates TOC from existing headers (shared `generate_toc`)
   - Adds missing video descriptions after TOC
   - **Self-heals pseudo-headers on read**: if a section body has `ONE SENTENCE SUMMARY:` as plain text, promotes it to `# ONE SENTENCE SUMMARY:` so Obsidian TOC anchors resolve
   - Supports dry-run mode for preview

## Resilience to Fabric Output Drift

Fabric's LLM output is non-deterministic and occasionally drops the leading
`# ` from the top heading of a section — which used to silently produce
truncated TOCs with broken anchors. The toolkit now defends in depth:

1. **Retry** — each fabric call is run up to `MAX_FABRIC_ATTEMPTS=3` times
   (configurable) until the output passes validation (default: contains a
   level-1 header; per-tool validators may add stricter checks such as
   minimum line counts).
2. **Pseudo-header promotion** — if retries exhaust, the first
   heading-shaped uppercase line (`ONE SENTENCE SUMMARY:`, `SUMMARY`, etc.)
   is promoted to `# ...` so TOC generation succeeds.
3. **Self-heal on patch** — `youtube_summary_patcher.py` runs the same
   promotion pass over existing files on disk, so legacy notes with dropped
   `# ` prefixes get fixed the next time the patcher visits them.

## Error Handling

The processor is designed to be resilient:
- Individual entry failures don't stop batch processing
- All errors are collected and reported at the end
- Invalid format lines are logged and skipped
- Network issues are caught and reported
- Fabric output defects are retried and auto-repaired where possible

## Use Cases

- **Content Curation**: Process your reading/watching backlog
- **Research**: Quickly extract insights from multiple sources
- **Knowledge Management**: Build a searchable library of summaries
- **Learning**: Review key points from educational content
- **Content Creation**: Gather research for articles or videos

## Contributing

This project uses detailed specifications in the `specs/` folder:
- `specs/top_level.md` - Batch processor specification
- `specs/youtube_summary_generator.md` - YouTube processing specification
- `specs/blog_summary_generator.md` - Blog processing specification
- `specs/youtube_summary_patcher.md` - YouTube patcher specification

When adding a new fabric-based generator, import from `fabric_utils.py`
rather than re-implementing the helpers — that keeps retry behavior,
TOC formatting, and pseudo-header recovery consistent across the toolkit.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with [fabric](https://github.com/danielmiessler/fabric) by Daniel Miessler
