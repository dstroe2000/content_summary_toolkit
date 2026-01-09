# Subtitle Summary Generator Specification

## Context
I have a folder containing subtitle files (and potentially subfolders with more subtitle files) that need to be processed and summarized. These are local subtitle files in various formats (`.srt`, `.sub`, `.vtt`, `.sbv`, etc.).

## Goal
Create a CLI application that processes all subtitle files in a folder (recursively through subfolders) and generates summary files with insights extracted using fabric patterns.

## Input
- **Folder path**: Path to the folder containing subtitle files (can be provided as command-line argument)
- **File patterns**: Subtitle files with extensions: `.srt`, `.sub`, `.vtt`, `.sbv`, `.txt`
- **Recursive**: Process all subfolders recursively

## Output File Naming Convention
For each subtitle file, create a summary file with:
- **Original filename** (without extension) + `.summary.txt`
- **Same location** as the original file

Examples:
- `video.srt` → `video.summary.txt`
- `lecture_notes.sub` → `lecture_notes.summary.txt`
- `subfolder/content.vtt` → `subfolder/content.summary.txt`

## Processing Steps

For each subtitle file found:

1. **Read the subtitle file content**
   - Read the entire subtitle file into memory
   - Handle various subtitle formats (SRT, SUB, VTT, etc.)

2. **Generate summaries using fabric patterns**

   Run three fabric patterns on the subtitle content:

   a. **Summary** - Run this bash command:
   ```bash
   cat "{subtitle_file_path}" | fabric -p summarize
   ```
   - Filter out information under the `<think></think>` section

   b. **YouTube Summary** - Run this bash command:
   ```bash
   cat "{subtitle_file_path}" | fabric -p youtube_summary
   ```
   - Filter out information under the `<think></think>` section

   c. **Extract Wisdom** - Run this bash command:
   ```bash
   cat "{subtitle_file_path}" | fabric -p extract_wisdom
   ```
   - Filter out information under the `<think></think>` section

3. **Aggregate the information**

   Combine the filtered results in the following structure:

```markdown
### TOC
- [[#header1]]
- [[#header2]]
- [[#header3]]

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
```

   **Table of Contents (TOC) Generation:**
   - Extract the first level 1 header (lines starting with `# `) from each of the three sections
   - Remove trailing colons from header text
   - Generate TOC using wiki-style links format: `[[#header_text]]`
   - Place TOC at the beginning of the file
   - If no headers are found in any section, omit the TOC section entirely

4. **Write to output file**
   - Save the aggregated content to `{original_filename}.summary.txt`
   - Place in the same directory as the original subtitle file
   - Use UTF-8 encoding

5. **Skip already processed files (optional)**
   - Check if `.summary.txt` file already exists
   - Optionally skip or overwrite based on command-line flag

## Command-Line Interface

### Basic Usage
```bash
python subtitle_summary_generator.py <folder_path>
```
Process all subtitle files in the specified folder and subfolders

### With Overwrite Flag
```bash
python subtitle_summary_generator.py <folder_path> --overwrite
```
Overwrite existing `.summary.txt` files if they already exist

### Dry Run Mode
```bash
python subtitle_summary_generator.py <folder_path> --dry-run
```
Show what files would be processed without actually processing them

### Verbose Mode
```bash
python subtitle_summary_generator.py <folder_path> --verbose
```
Show detailed processing information for each file

### Filter by Extension
```bash
python subtitle_summary_generator.py <folder_path> --extensions .srt .vtt
```
Only process specific subtitle file extensions

## Output Report

After processing completes, display a summary:

```
==================================================
Subtitle Summary Generator Report
==================================================
Total subtitle files found:    15
Successfully processed:        13
Already existed (skipped):     2
Processing failed:             0

Success rate:                  100.0%
Total processing time:         45.3 seconds
==================================================
```

## Error Handling

- **File read errors**: Log error and continue with next file
- **Fabric command failures**: Log error with filename and continue
- **File write errors**: Log error and continue with next file
- **Empty subtitle files**: Skip and log warning
- All errors should be collected and displayed in final report

## Edge Cases

1. **Empty subtitle files**: Skip and log warning
2. **Files already processed**: Check for existing `.summary.txt`, skip unless `--overwrite` flag
3. **Binary or corrupted files**: Handle gracefully, log error
4. **Permission errors**: Log error and continue
5. **Fabric pattern failures**: Log which pattern failed and continue with others
6. **Mixed file types**: Only process files with valid subtitle extensions

## Dependencies

- Python 3.x
- fabric CLI tool (must be installed and available in PATH)
- Standard library: os, sys, re, argparse, subprocess

## Example Transformation

### Input File: `lecture_01.srt`
```
1
00:00:01,000 --> 00:00:05,000
Welcome to this lecture on machine learning.

2
00:00:05,500 --> 00:00:10,000
Today we'll discuss neural networks...
```

### Output File: `lecture_01.summary.txt`
```markdown
### TOC
- [[#ONE SENTENCE SUMMARY]]
- [[#SUMMARY]]
- [[#WISDOM]]

---

# ONE SENTENCE SUMMARY:
This lecture provides an introduction to neural networks and their applications in machine learning.

---
---
---

# SUMMARY

## INTRODUCTION
This video covers the fundamentals of neural networks...

## KEY POINTS
- Neural networks are inspired by biological neurons
- Backpropagation is used for training
- Applications include image recognition...

---
---
---

# WISDOM

## MAIN IDEAS
- Understanding the basics of neural networks is crucial...

## INSIGHTS
- Neural networks have revolutionized AI...
```

## HowTo Generate

Generate Python code based on all the above instructions. The file should be named `subtitle_summary_generator.py`.

The script should:
1. Use argparse for CLI argument parsing
2. Recursively walk through folders to find subtitle files
3. Include detailed docstrings for all functions
4. Follow the same code style as `youtube_summary_generator.py`
5. Reuse the pattern for filtering `<think></think>` sections
6. Include comprehensive error handling
7. Provide clear progress feedback to the user
8. Support the command-line flags described above
