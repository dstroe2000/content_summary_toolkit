# YouTube Summary Patcher Specification

## Context
I have existing YouTube summary files in the `output/yt_generated/` folder that were generated before the channel information, TOC, and video description features were implemented. These legacy files may be missing:
- The author and channel information line above the video link
- The Table of Contents (TOC) section
- The video description after the TOC section

## Goal
Create a CLI application that patches existing YouTube summary markdown files to the current format by:
1. Extracting the YouTube video URL
2. Adding the missing channel author information above the video link
3. Generating and inserting TOC from existing headers (if missing)
4. Adding the video description after the TOC section

## Input
- **Folder path**: Path to the folder containing existing YouTube summary files (default: `output/yt_generated/`)
- **File pattern**: Markdown files (`*.md`) in the specified folder

## Expected File Structure (Before Update)

Files may have one of these structures:

**Structure 1** (Missing channel info only):
```markdown

[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

### TOC
- [[#SUMMARY]]

---

# SUMMARY
{summary content}
...
```

**Structure 2** (Missing both channel info and description):
```markdown

[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

### TOC
- [[#SUMMARY]]

---

# SUMMARY
{summary content}
...
```

## Desired File Structure (After Update)

Updated files should have this complete structure:
```markdown
[{author_name}]({channel_url})
[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

### TOC
- [[#SUMMARY]]

---

{video_description}

---

# SUMMARY
{summary content}
...
```

## Processing Steps

For each markdown file in the target folder:

1. **Read the file content**
   - Read the entire markdown file into memory

2. **Extract YouTube video URL**
   - Search for the pattern: `[Link](https://www.youtube.com/watch?v=...)`
   - Extract the YouTube URL from the round brackets
   - If no YouTube link found, skip the file and log a warning

3. **Check if channel info already exists**
   - Check if there's already content on the line immediately before `[Link](...)`
   - If a non-empty line exists before `[Link](...)`, assume file is already updated and skip it
   - This prevents duplicate channel info updates

4. **Extract channel information using yt-dlp**
   - Use yt-dlp to extract channel metadata from the video URL
   - Get `author_name` (channel name)
   - Get `channel_url` (channel URL)
   - **Prefer handle format** (`https://www.youtube.com/@username`) over legacy channel ID format
   - If extraction fails, log error and skip the file

5. **Update file content with channel info**
   - Insert `[{author_name}]({channel_url})` on a new line
   - Place it immediately before the existing `[Link](...)`  line
   - Preserve all other content exactly as is
   - No blank line between author line and link line

6. **Extract video description using yt-dlp** (unless --skip-description flag is set)
   - Use yt-dlp to extract video description: `yt-dlp --get-description <video_url>`
   - Get the original description text written by the video creator
   - If extraction fails, log warning and continue (non-fatal)

7. **Check if description already exists**
   - Look for content between the TOC separator and the next section
   - Pattern: `### TOC ... --- [content] ---`
   - If content exists between separators, description already present, skip

8. **Insert video description** (if not already present and TOC exists)
   - Find the TOC section: `### TOC ... ---`
   - Insert description after the TOC separator
   - Add separators: `--- {description} ---`
   - If no TOC section found, skip description insertion

9. **Write updated content back to file**
   - Overwrite the original file with updated content
   - Use UTF-8 encoding

10. **Report progress**
    - Log each file being processed
    - Show success/failure status for both channel info and description
    - Provide final summary statistics

## Command-Line Interface

### Basic Usage
```bash
python youtube_summary_patcher.py
```
This processes all `.md` files in `output/yt_generated/` folder (default)
Patches files with channel info, TOC, and video descriptions

### With Custom Folder
```bash
python youtube_summary_patcher.py --folder /path/to/folder
```

### Dry Run Mode (Preview Only)
```bash
python youtube_summary_patcher.py --dry-run
```
Shows what would be patched without making changes

### Verbose Mode
```bash
python youtube_summary_patcher.py --verbose
```
Shows detailed processing information for each file

### Skip Description Mode
```bash
python youtube_summary_patcher.py --skip-description
```
Only patches channel information, skips video description extraction
Useful when you only want to add author/channel lines

## Output Report

After processing completes, display a summary:

```
==================================================
YouTube Summary Patcher Summary
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
```

Note: Video description stats are only shown when `--skip-description` is NOT used.

## Error Handling

- **File read errors**: Log error and continue with next file
- **Invalid YouTube URLs**: Log warning and skip file
- **yt-dlp extraction failures**: Log error with video URL and skip file
- **File write errors**: Log error and continue with next file
- All errors should be collected and displayed in final report

## Edge Cases

1. **Files without YouTube links**: Skip and log
2. **Files already updated** (channel info): Detect and skip (avoid duplicates)
3. **Files with description already present**: Detect and skip description insertion
4. **Files without TOC section**: Skip description insertion, only update channel info
5. **Malformed markdown**: Handle gracefully, log warning
6. **Network issues during yt-dlp**: Retry once, then skip if fails
7. **Empty files**: Skip and log
8. **Empty video description**: Don't insert if description is empty/whitespace only
9. **Description extraction fails**: Log warning, continue with channel update (non-fatal)

## Dependencies

- Python 3.x
- yt-dlp library (for channel metadata extraction)
- Standard library: os, sys, re, argparse

## Example Transformations

### Before:
```markdown

[Link](https://www.youtube.com/watch?v=sVcwVQRHIc8)

---

### TOC
- [[#ONE SENTENCE SUMMARY]]
- [[#SUMMARY]]

---

# ONE SENTENCE SUMMARY
This video teaches RAG from scratch...

---
---
---

# SUMMARY
This video teaches RAG from scratch...
```

### After:
```markdown
[freeCodeCamp.org](https://www.youtube.com/@freecodecamp)
[Link](https://www.youtube.com/watch?v=sVcwVQRHIc8)

---

### TOC
- [[#ONE SENTENCE SUMMARY]]
- [[#SUMMARY]]

---

Learn how to build a Retrieval Augmented Generation (RAG) system from scratch in Python!
This comprehensive course teaches the fundamentals...

---

# ONE SENTENCE SUMMARY
This video teaches RAG from scratch...

---
---
---

# SUMMARY
This video teaches RAG from scratch...
```

## Safety Features

- **Dry-run mode**: Preview changes before applying
- **Backup option**: Optionally create `.bak` backup files before updating
- **Skip already updated**: Prevent duplicate author lines
- **Non-destructive**: Only inserts content, doesn't remove anything

## HowTo Generate

Generate Python code based on all the above instructions. The file should be named `youtube_summary_patcher.py`.

The script should:
1. Use argparse for CLI argument parsing
2. Include detailed docstrings for all functions
3. Follow the same code style as `youtube_summary_generator.py`
4. Reuse the `_get_youtube_channel_info()` and `_get_youtube_description()` function patterns from `youtube_summary_generator.py`
5. Include comprehensive error handling
6. Provide clear progress feedback to the user
7. Support TOC generation from existing headers
