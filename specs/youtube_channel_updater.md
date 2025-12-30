# YouTube Channel Updater Specification

## Context
I have existing YouTube summary files in the `output/yt_generated/` folder that were generated before the channel information feature was implemented. These files contain a YouTube link but are missing the author and channel information line above it.

## Goal
Create a CLI application that updates existing YouTube summary markdown files by extracting the YouTube video URL and adding the missing channel author information above the video link.

## Input
- **Folder path**: Path to the folder containing existing YouTube summary files (default: `output/yt_generated/`)
- **File pattern**: Markdown files (`*.md`) in the specified folder

## Expected File Structure (Before Update)

Current files have this structure:
```markdown

[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

{summary content}
...
```

## Desired File Structure (After Update)

Updated files should have this structure:
```markdown
[{author_name}]({channel_url})

[Link](https://www.youtube.com/watch?v=VIDEO_ID)

---

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

3. **Check if already updated**
   - Check if there's already content on the line immediately before `[Link](...)`
   - If a non-empty line exists before `[Link](...)`, assume file is already updated and skip it
   - This prevents duplicate updates

4. **Extract channel information using yt-dlp**
   - Use yt-dlp to extract channel metadata from the video URL
   - Get `author_name` (channel name)
   - Get `channel_url` (channel URL)
   - **Prefer handle format** (`https://www.youtube.com/@username`) over legacy channel ID format
   - If extraction fails, log error and skip the file

5. **Update file content**
   - Insert `[{author_name}]({channel_url})` on a new line
   - Place it immediately before the existing `[Link](...)`  line
   - Preserve all other content exactly as is
   - Maintain proper spacing (blank line after author line)

6. **Write updated content back to file**
   - Overwrite the original file with updated content
   - Use UTF-8 encoding

7. **Report progress**
   - Log each file being processed
   - Show success/failure status
   - Provide final summary statistics

## Command-Line Interface

### Basic Usage
```bash
python youtube_channel_updater.py
```
This processes all `.md` files in `output/yt_generated/` folder (default)

### With Custom Folder
```bash
python youtube_channel_updater.py --folder /path/to/folder
```

### Dry Run Mode (Preview Only)
```bash
python youtube_channel_updater.py --dry-run
```
Shows what would be updated without making changes

### Verbose Mode
```bash
python youtube_channel_updater.py --verbose
```
Shows detailed processing information for each file

## Output Report

After processing completes, display a summary:

```
==================================================
YouTube Channel Updater Summary
==================================================
Total files found:      25
Successfully updated:   20
Already updated:        3
No link found:          1
Extraction failed:      1
Success rate:           95.2%
==================================================
```

## Error Handling

- **File read errors**: Log error and continue with next file
- **Invalid YouTube URLs**: Log warning and skip file
- **yt-dlp extraction failures**: Log error with video URL and skip file
- **File write errors**: Log error and continue with next file
- All errors should be collected and displayed in final report

## Edge Cases

1. **Files without YouTube links**: Skip and log
2. **Files already updated**: Detect and skip (avoid duplicates)
3. **Malformed markdown**: Handle gracefully, log warning
4. **Network issues during yt-dlp**: Retry once, then skip if fails
5. **Empty files**: Skip and log

## Dependencies

- Python 3.x
- yt-dlp library (for channel metadata extraction)
- Standard library: os, sys, re, argparse

## Example Transformations

### Before:
```markdown

[Link](https://www.youtube.com/watch?v=sVcwVQRHIc8)

---

# SUMMARY
This video teaches RAG from scratch...
```

### After:
```markdown
[freeCodeCamp.org](https://www.youtube.com/@freecodecamp)

[Link](https://www.youtube.com/watch?v=sVcwVQRHIc8)

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

Generate Python code based on all the above instructions. The file should be named `youtube_channel_updater.py`.

The script should:
1. Use argparse for CLI argument parsing
2. Include detailed docstrings for all functions
3. Follow the same code style as `youtube_summary_generator.py`
4. Reuse the `_get_youtube_channel_info()` function pattern from `youtube_summary_generator.py`
5. Include comprehensive error handling
6. Provide clear progress feedback to the user
