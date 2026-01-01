# Fabric Backlog Processor

A batch content summarizer that processes YouTube videos and blog articles using AI-powered summarization through the [fabric](https://github.com/danielmiessler/fabric) tool.

## Overview

This tool helps you process a backlog of content (YouTube videos and blog articles) by automatically generating structured markdown summaries. It extracts transcripts from YouTube videos, fetches blog content, and creates comprehensive summaries using multiple AI patterns.

## Features

- **Batch Processing**: Process multiple entries from a single batch file
- **Multi-Format Support**: Handles both YouTube videos and blog articles
- **AI-Powered Summaries**: Uses fabric's AI patterns for intelligent summarization
- **Multiple Summary Types**: Generates different perspectives on content:
  - General summary
  - YouTube-specific summary (for videos)
  - Extracted wisdom and insights
- **Rich Metadata Extraction**:
  - Channel information with modern handle format (`@username`)
  - Video descriptions from creators
  - Auto-generated Table of Contents (TOC)
- **Organized Output**: Structured folder hierarchy for easy navigation
- **Legacy Patcher**: Patch existing files with missing channel info and descriptions
- **Comprehensive Reporting**: Detailed statistics and success metrics
- **Error Resilient**: Continues processing even if individual entries fail

## Prerequisites

- Python 3.x
- [fabric](https://github.com/danielmiessler/fabric) - AI-powered text processing tool
  - Must be installed and configured with API access
  - Requires patterns: `summarize`, `youtube_summary`, `extract_wisdom`
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - YouTube metadata extraction
  - Used to extract channel information from YouTube videos

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
python fabric_backlog.py batch_entries.txt
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

The processor creates an organized folder structure:

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

The project consists of four main components:

1. **fabric_backlog.py**: Main orchestrator
   - Parses batch files
   - Routes entries to appropriate generators
   - Tracks statistics and generates reports

2. **youtube_summary_generator.py**: YouTube processor
   - Extracts channel information using `yt-dlp`
   - Extracts video descriptions using `yt-dlp --get-description`
   - Downloads transcripts using `fabric -y`
   - Generates Table of Contents from section headers
   - Generates 3 types of summaries
   - Creates structured markdown output with full metadata

3. **blog_summary_generator.py**: Blog processor
   - Fetches blog content using `fabric -u`
   - Generates 2 types of summaries
   - Creates structured markdown output

4. **youtube_summary_patcher.py**: Legacy file patcher
   - Patches existing YouTube summary files to current format
   - Adds missing channel information
   - Generates TOC from existing headers
   - Adds missing video descriptions after TOC
   - Supports dry-run mode for preview
   - Provides detailed patch statistics

## Error Handling

The processor is designed to be resilient:
- Individual entry failures don't stop batch processing
- All errors are collected and reported at the end
- Invalid format lines are logged and skipped
- Network issues are caught and reported

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

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with [fabric](https://github.com/danielmiessler/fabric) by Daniel Miessler
