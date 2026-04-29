"""
YouTube Content Upgrader

Upgrades existing YouTube summary notes in an Obsidian vault to the current
template format by detecting missing sections and running only the required
fabric patterns.

Categories handled:
    - Category 1 (Old Fabric): Has extract_wisdom output only. Needs summarize +
      youtube_summary sections prepended, plus metadata wrapper.
    - Category 2 (Bare Content): Free-form AI summaries with no standard structure.
      Full regeneration from YouTube URL.
    - Category 3 (Near-Compliant): Has summarize output but missing youtube_summary
      and/or extract_wisdom. Append missing sections.

Quality validation:
    - Validates fabric output for pathological/empty results
    - Retries failed patterns (configurable max retries)
    - extract_wisdom is validated more strictly (known to produce bad output)

External Dependencies:
    - fabric: AI-powered text processing tool with patterns
    - yt-dlp: YouTube metadata and description extraction

Usage:
    # Dry-run scan of vault
    python youtube_content_upgrader.py --folder /path/to/Youtube --dry-run

    # Process category 2 (bare content) only
    python youtube_content_upgrader.py --folder /path/to/Youtube --category 2

    # Process all categories
    python youtube_content_upgrader.py --folder /path/to/Youtube --category all

    # Limit to N files (for testing)
    python youtube_content_upgrader.py --folder /path/to/Youtube --category 2 --limit 5

    # Verbose output
    python youtube_content_upgrader.py --folder /path/to/Youtube --category 2 --verbose
"""

import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from fabric_utils import (
    filter_think_sections,
    extract_first_level1_header,
    generate_toc,
    promote_pseudo_header,
    run_command,
    ytdlp_cookie_cli,
    ytdlp_cookie_opts,
    ytdlp_meta_opts,
)

try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp is required. Install with: pip install yt-dlp")
    sys.exit(1)


# ─── Constants ──────────────────────────────────────────────────────────────

SUBTITLE_DIR = Path(__file__).parent / "output" / "subtitle"
BACKUP_DIR = Path(__file__).parent / "output" / "upgrader_backups"

MAX_RETRIES = 2
RETRY_DELAY = 5  # seconds
INTER_NOTE_DELAY = 3  # seconds between notes to avoid YouTube rate limiting
INTER_REQUEST_DELAY = 3  # seconds between individual YouTube API calls within a note

# Minimum line counts for quality validation
MIN_LINES = {
    "summarize": 8,
    "youtube_summary": 10,
    "extract_wisdom": 15,
}

# Section detection patterns
SECTION_PATTERNS = {
    "summarize": r"^#\s+ONE SENTENCE SUMMARY",
    "youtube_summary": r"^#\s+Summary[:.]",
    "extract_wisdom_header": r"^#\s+SUMMARY\s*$",
    "extract_wisdom_ideas": r"^#\s+IDEAS",
    "extract_wisdom_insights": r"^#\s+INSIGHTS",
    "extract_wisdom_quotes": r"^#\s+QUOTES",
    "fabric_command": r"^yt\s+\"https?://",
    "toc": r"^###\s+TOC",
    "channel_before_link": r"\[[^\]]+\]\([^\)]+\)\s*\n\s*\[Link\]\(https://(?:www\.)?youtube\.com",
    "video_link": r"\[Link\]\((https://(?:www\.)?youtube\.com/watch\?v=[^\)]+)\)",
    "bare_url": r"^https?://(?:www\.)?youtube\.com/watch\?v=",
}


# ─── Helpers ────────────────────────────────────────────────────────────────
# Text helpers (filter_think_sections, extract_first_level1_header,
# generate_toc, promote_pseudo_header, run_command) come from fabric_utils.


def _get_youtube_channel_info(video_url):
    """Extract YouTube channel info using yt-dlp."""
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            **ytdlp_meta_opts(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            author_name = info.get("uploader", info.get("channel", "Unknown"))
            channel_url = info.get("channel_url", "")
            uploader_url = info.get("uploader_url", "")
            if uploader_url and "/@" in uploader_url:
                channel_url = uploader_url
            elif uploader_url:
                channel_url = uploader_url
            return author_name, channel_url
    except Exception:
        return None, None


def _get_youtube_description(video_url):
    """Extract video description using yt-dlp."""
    try:
        cookie_flag = ytdlp_cookie_cli()
        command = f'yt-dlp {cookie_flag} --get-description "{video_url}"'.strip()
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except Exception:
        return ""


# ─── Classification ─────────────────────────────────────────────────────────

def _extract_youtube_url(content):
    """Extract YouTube URL from note content."""
    # Try [Link](url) format first
    match = re.search(SECTION_PATTERNS["video_link"], content)
    if match:
        return match.group(1)
    # Try bare URL
    for line in content.split("\n"):
        line = line.strip()
        if re.match(SECTION_PATTERNS["bare_url"], line):
            return line
    return None


def _detect_sections(content):
    """Detect which template sections are present in the note."""
    lines = content.split("\n")
    sections = {
        "has_channel_link": bool(re.search(SECTION_PATTERNS["channel_before_link"], content)),
        "has_video_link": bool(re.search(SECTION_PATTERNS["video_link"], content)),
        "has_toc": bool(re.search(SECTION_PATTERNS["toc"], content, re.MULTILINE)),
        "has_summarize": False,
        "has_youtube_summary": False,
        "has_extract_wisdom": False,
        "has_fabric_command": False,
    }

    for line in lines:
        stripped = line.strip()
        if re.match(SECTION_PATTERNS["summarize"], stripped, re.IGNORECASE):
            sections["has_summarize"] = True
        if re.match(SECTION_PATTERNS["youtube_summary"], stripped, re.IGNORECASE):
            sections["has_youtube_summary"] = True
        if re.match(SECTION_PATTERNS["extract_wisdom_header"], stripped, re.IGNORECASE):
            # Verify it's the extract_wisdom SUMMARY (has IDEAS/INSIGHTS nearby)
            if (
                re.search(SECTION_PATTERNS["extract_wisdom_ideas"], content, re.MULTILINE)
                or re.search(SECTION_PATTERNS["extract_wisdom_insights"], content, re.MULTILINE)
            ):
                sections["has_extract_wisdom"] = True
        if re.match(SECTION_PATTERNS["fabric_command"], stripped):
            sections["has_fabric_command"] = True

    return sections


def classify_note(filepath):
    """Classify a note into a category based on its content.

    Returns:
        dict with keys: category (1, 2, 3, 'compliant', 'skip'),
        sections, youtube_url, line_count
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {"category": "skip", "reason": "unreadable"}

    youtube_url = _extract_youtube_url(content)
    if not youtube_url:
        return {"category": "skip", "reason": "no_youtube_url"}

    sections = _detect_sections(content)
    line_count = len(content.split("\n"))

    has_s = sections["has_summarize"]
    has_ys = sections["has_youtube_summary"]
    has_ew = sections["has_extract_wisdom"]

    # Compliant: has all 3 content sections
    if has_s and has_ys and has_ew:
        return {
            "category": "compliant",
            "sections": sections,
            "youtube_url": youtube_url,
            "line_count": line_count,
        }

    # Category 3 (Near-compliant): has summarize, missing others
    if has_s and (not has_ys or not has_ew):
        missing = []
        if not has_ys:
            missing.append("youtube_summary")
        if not has_ew:
            missing.append("extract_wisdom")
        return {
            "category": 3,
            "sections": sections,
            "youtube_url": youtube_url,
            "line_count": line_count,
            "missing_patterns": missing,
        }

    # Category 1 (Old Fabric): has extract_wisdom but not summarize
    if has_ew and not has_s:
        missing = ["summarize", "youtube_summary"] if not has_ys else ["summarize"]
        return {
            "category": 1,
            "sections": sections,
            "youtube_url": youtube_url,
            "line_count": line_count,
            "missing_patterns": missing,
        }

    # Category 2 (Bare content): has some content but no standard sections
    if line_count > 5 and not has_s and not has_ew:
        return {
            "category": 2,
            "sections": sections,
            "youtube_url": youtube_url,
            "line_count": line_count,
            "missing_patterns": ["summarize", "youtube_summary", "extract_wisdom"],
        }

    # Metadata only (very short, no content)
    if line_count <= 5:
        return {
            "category": 2,
            "sections": sections,
            "youtube_url": youtube_url,
            "line_count": line_count,
            "missing_patterns": ["summarize", "youtube_summary", "extract_wisdom"],
            "reason": "metadata_only",
        }

    return {
        "category": 2,
        "sections": sections,
        "youtube_url": youtube_url,
        "line_count": line_count,
        "missing_patterns": ["summarize", "youtube_summary", "extract_wisdom"],
    }


# ─── Quality Validation ─────────────────────────────────────────────────────

def _validate_fabric_output(pattern_name, output):
    """Validate fabric pattern output for quality.

    Returns:
        (is_valid, reason)
    """
    if not output or not output.strip():
        return False, "empty output"

    lines = [l for l in output.strip().split("\n") if l.strip()]
    min_lines = MIN_LINES.get(pattern_name, 5)

    if len(lines) < min_lines:
        return False, f"too few lines ({len(lines)} < {min_lines})"

    # Check for repetitive/pathological output
    if len(lines) > 5:
        unique_lines = set(l.strip() for l in lines if len(l.strip()) > 10)
        if len(unique_lines) < len(lines) * 0.3:
            return False, "repetitive output (>70% duplicate lines)"

    # extract_wisdom specific checks
    if pattern_name == "extract_wisdom":
        has_summary = bool(re.search(r"^#\s+SUMMARY", output, re.MULTILINE))
        has_ideas = bool(re.search(r"^#\s+IDEAS", output, re.MULTILINE))
        if not has_summary:
            return False, "extract_wisdom missing # SUMMARY header"
        if not has_ideas:
            return False, "extract_wisdom missing # IDEAS header"

    # summarize specific checks
    if pattern_name == "summarize":
        has_oss = bool(
            re.search(r"^#\s+ONE SENTENCE SUMMARY", output, re.MULTILINE | re.IGNORECASE)
        )
        if not has_oss:
            return False, "summarize missing # ONE SENTENCE SUMMARY header"

    return True, "ok"


# ─── Transcript & Pattern Processing ────────────────────────────────────────

def _ensure_transcript(title, youtube_url, verbose=False):
    """Ensure transcript file exists. Download if needed.

    Uses yt-dlp directly to download VTT subtitles and converts to plain text.
    Falls back to fabric -y if direct download fails.

    Returns:
        (success, subtitle_filepath)
    """
    SUBTITLE_DIR.mkdir(parents=True, exist_ok=True)
    subtitle_file = SUBTITLE_DIR / f"{title}.txt"

    if subtitle_file.exists() and subtitle_file.stat().st_size > 0:
        if verbose:
            print(f"    Transcript exists: {subtitle_file.name}")
        return True, subtitle_file

    if verbose:
        print(f"    Downloading transcript via yt-dlp...")

    # Download VTT subtitle directly with yt-dlp
    success = _download_transcript_ytdlp(title, youtube_url, subtitle_file, verbose)
    if success:
        return True, subtitle_file

    # Fallback: try fabric -y
    if verbose:
        print(f"    Direct download failed, trying fabric -y fallback...")
    cookie_flag = ytdlp_cookie_cli()
    yt_dlp_args = f"--sleep-requests 2 {cookie_flag}".strip()
    cmd = f'fabric -y "{youtube_url}" --transcript-with-timestamps --yt-dlp-args="{yt_dlp_args}" > "{subtitle_file}"'
    success, output = run_command(cmd, timeout=120)

    if success and subtitle_file.exists() and subtitle_file.stat().st_size > 0:
        if verbose:
            print(f"    Transcript saved via fabric ({subtitle_file.stat().st_size} bytes)")
        return True, subtitle_file
    else:
        if verbose:
            print(f"    Transcript download failed: {output[:100]}")
        if subtitle_file.exists():
            subtitle_file.unlink()
        return False, None


def _download_transcript_ytdlp(title, youtube_url, output_file, verbose=False):
    """Download transcript directly via yt-dlp and convert VTT to plain text.

    Returns:
        True if successful, False otherwise
    """
    import tempfile
    import glob

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en"],
                "subtitlesformat": "vtt",
                "outtmpl": os.path.join(tmpdir, "subtitle.%(ext)s"),
                **ytdlp_meta_opts(),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])

            # Find the VTT file
            vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
            if not vtt_files:
                if verbose:
                    print(f"    no VTT files found")
                return False

            vtt_path = vtt_files[0]
            plain_text = _vtt_to_plain_text(vtt_path)

            if not plain_text or len(plain_text.strip()) < 50:
                if verbose:
                    print(f"    VTT conversion produced too little text")
                return False

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(plain_text)

            if verbose:
                print(f"    Transcript saved ({output_file.stat().st_size} bytes)")
            return True

    except Exception as e:
        if verbose:
            print(f"    yt-dlp direct download error: {e}")
        return False


def _vtt_to_plain_text(vtt_path):
    """Convert a VTT subtitle file to plain text with timestamps."""
    lines = []
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove VTT header
    parts = re.split(r"\n\n+", content)
    for part in parts:
        part = part.strip()
        if not part or part.startswith("WEBVTT") or part.startswith("Kind:") or part.startswith("Language:"):
            continue

        block_lines = part.split("\n")
        # Find timestamp line
        timestamp = None
        text_parts = []
        for line in block_lines:
            if re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->", line):
                # Extract start timestamp
                match = re.match(r"(\d{2}):(\d{2}):(\d{2})\.\d{3}", line)
                if match:
                    h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if h > 0:
                        timestamp = f"{h}:{m:02d}:{s:02d}"
                    else:
                        timestamp = f"{m}:{s:02d}"
            elif not re.match(r"^\d+$", line.strip()):
                # Strip VTT formatting tags
                cleaned = re.sub(r"<[^>]+>", "", line).strip()
                if cleaned:
                    text_parts.append(cleaned)

        if text_parts:
            text = " ".join(text_parts)
            if timestamp:
                lines.append(f"({timestamp}) {text}")
            else:
                lines.append(text)

    # Deduplicate overlapping VTT cues — keep only lines that add new text
    deduped = []
    seen_text = ""
    for line in lines:
        text_only = re.sub(r"^\(\d+:[\d:]+\)\s*", "", line)
        # Skip if this text is fully contained in what we've already seen recently
        if text_only in seen_text:
            continue
        deduped.append(line)
        seen_text = (seen_text + " " + text_only)[-500:]  # rolling window

    return "\n".join(deduped)


def _run_fabric_pattern(pattern_name, subtitle_file, verbose=False):
    """Run a fabric pattern with retry logic and validation.

    Returns:
        (success, filtered_output)

    After ``MAX_RETRIES`` attempts without passing ``_validate_fabric_output``,
    this falls back to ``promote_pseudo_header`` to recover from fabric
    deterministically dropping the leading ``# `` on its top header, then
    re-validates. If that still fails, returns ``(False, None)``.
    """
    last_filtered = None

    for attempt in range(1, MAX_RETRIES + 1):
        if verbose:
            attempt_str = f" (attempt {attempt}/{MAX_RETRIES})" if attempt > 1 else ""
            print(f"    Running fabric -p {pattern_name}{attempt_str}...")

        cmd = f'cat "{subtitle_file}" | fabric -p {pattern_name}'
        success, output = run_command(cmd, timeout=300)

        if not success:
            if verbose:
                print(f"    fabric -p {pattern_name} command failed: {output[:100]}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            continue

        filtered = filter_think_sections(output)
        last_filtered = filtered
        is_valid, reason = _validate_fabric_output(pattern_name, filtered)

        if is_valid:
            if verbose:
                lines = len(filtered.split("\n"))
                print(f"    {pattern_name} OK ({lines} lines)")
            return True, filtered
        else:
            if verbose:
                print(f"    {pattern_name} validation failed: {reason}")
            if attempt < MAX_RETRIES:
                if verbose:
                    print(f"    Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

    # Retries exhausted. Try pseudo-header promotion (handles deterministic
    # dropout of the leading ``# ``) and re-validate.
    if last_filtered is not None:
        patched, promoted = promote_pseudo_header(last_filtered)
        if promoted is not None:
            is_valid, reason = _validate_fabric_output(pattern_name, patched)
            if is_valid:
                if verbose:
                    print(
                        f"    {pattern_name} recovered via pseudo-header promotion "
                        f"('{promoted}')"
                    )
                return True, patched
            elif verbose:
                print(
                    f"    {pattern_name} pseudo-header promoted but still invalid: {reason}"
                )

    return False, None


# ─── Note Assembly ──────────────────────────────────────────────────────────

def _build_full_note(
    title, youtube_url, author_name, channel_url, video_description,
    summarize_output, youtube_summary_output, extract_wisdom_output,
    tags=""
):
    """Build a complete note from all components."""
    header_summarize = extract_first_level1_header(summarize_output)
    header_youtube = extract_first_level1_header(youtube_summary_output)
    header_wisdom = extract_first_level1_header(extract_wisdom_output)
    toc_content = generate_toc([header_summarize, header_youtube, header_wisdom])

    toc_section = f"\n{toc_content}\n\n---\n" if toc_content else ""
    description_section = f"\n{video_description}\n\n---\n" if video_description else ""
    tags_line = f"\n{tags}\n" if tags else "\n"

    content = f"""[{author_name}]({channel_url})
[Link]({youtube_url})
{tags_line}---
{toc_section}{description_section}
{summarize_output}

---
---
---

{youtube_summary_output}

---
---
---

{extract_wisdom_output}

"""
    return content


def _append_missing_sections(content, missing_outputs):
    """Append missing sections to existing note content."""
    # Find the end of existing content (before trailing whitespace)
    content = content.rstrip()

    for pattern_name, output in missing_outputs:
        content += "\n\n---\n---\n---\n\n"
        content += output

    content += "\n"
    return content


def _prepend_and_wrap_old_fabric(
    content, youtube_url, author_name, channel_url, video_description,
    summarize_output, youtube_summary_output, tags=""
):
    """Wrap old fabric notes: add header, prepend summarize + youtube_summary."""
    lines = content.split("\n")

    # Remove existing header lines (channel link, video link, fabric command, blank lines)
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            not stripped
            or re.match(r"\[.+\]\(https?://", stripped)
            or re.match(r"yt\s+\"https?://", stripped)
            or stripped == "---"
        ):
            body_start = i + 1
        else:
            break

    existing_body = "\n".join(lines[body_start:]).strip()

    # Extract headers for TOC
    header_summarize = extract_first_level1_header(summarize_output)
    header_youtube = extract_first_level1_header(youtube_summary_output)
    header_wisdom = extract_first_level1_header(existing_body)
    toc_content = generate_toc([header_summarize, header_youtube, header_wisdom])

    toc_section = f"\n{toc_content}\n\n---\n" if toc_content else ""
    description_section = f"\n{video_description}\n\n---\n" if video_description else ""
    tags_line = f"\n{tags}\n" if tags else "\n"

    new_content = f"""[{author_name}]({channel_url})
[Link]({youtube_url})
{tags_line}---
{toc_section}{description_section}
{summarize_output}

---
---
---

{youtube_summary_output}

---
---
---

{existing_body}

"""
    return new_content


# ─── Processing Functions ───────────────────────────────────────────────────

def process_note(filepath, classification, dry_run=False, verbose=False):
    """Process a single note based on its classification.

    Returns:
        dict with status, message, patterns_run, patterns_failed
    """
    result = {
        "status": "unknown",
        "message": "",
        "patterns_run": [],
        "patterns_failed": [],
    }

    category = classification["category"]
    youtube_url = classification["youtube_url"]
    title = Path(filepath).stem

    if verbose:
        print(f"\n  Processing: {title}")
        print(f"  Category: {category}")
        print(f"  URL: {youtube_url}")

    if dry_run:
        missing = classification.get("missing_patterns", [])
        result["status"] = "dry_run"
        result["message"] = f"Would run: {', '.join(missing)}"
        return result

    # Backup original file
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{title}.md.bak"
    if not backup_path.exists():
        shutil.copy2(filepath, backup_path)

    # Ensure transcript
    success, subtitle_file = _ensure_transcript(title, youtube_url, verbose)
    if not success:
        result["status"] = "failed"
        result["message"] = "Transcript download failed"
        return result

    # Get channel info and description (throttled to avoid YouTube rate limits)
    if verbose:
        print(f"    Fetching channel info...")
    time.sleep(INTER_REQUEST_DELAY)
    author_name, channel_url = _get_youtube_channel_info(youtube_url)
    if not author_name:
        author_name = "Unknown"
        channel_url = ""

    time.sleep(INTER_REQUEST_DELAY)
    video_description = _get_youtube_description(youtube_url)

    # Read current content
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Run missing patterns
    missing_patterns = classification.get("missing_patterns", [])
    pattern_outputs = {}

    for pattern in missing_patterns:
        success, output = _run_fabric_pattern(pattern, subtitle_file, verbose)
        if success:
            pattern_outputs[pattern] = output
            result["patterns_run"].append(pattern)
        else:
            result["patterns_failed"].append(pattern)

    # If all patterns failed, abort
    if not pattern_outputs:
        result["status"] = "failed"
        result["message"] = f"All patterns failed: {', '.join(missing_patterns)}"
        return result

    # Assemble the upgraded note based on category
    if category == 2:
        # Full replacement
        s_out = pattern_outputs.get("summarize", "")
        ys_out = pattern_outputs.get("youtube_summary", "")
        ew_out = pattern_outputs.get("extract_wisdom", "")

        if not s_out or not ys_out or not ew_out:
            # Partial success - still write what we have
            if verbose:
                failed = [p for p in missing_patterns if p not in pattern_outputs]
                print(f"    Partial success (failed: {', '.join(failed)})")

        new_content = _build_full_note(
            title, youtube_url, author_name, channel_url,
            video_description, s_out or "", ys_out or "", ew_out or ""
        )

    elif category == 1:
        # Old fabric: wrap + prepend
        s_out = pattern_outputs.get("summarize", "")
        ys_out = pattern_outputs.get("youtube_summary", "")

        new_content = _prepend_and_wrap_old_fabric(
            content, youtube_url, author_name, channel_url,
            video_description, s_out or "", ys_out or ""
        )

    elif category == 3:
        # Near-compliant: append missing sections
        missing_outputs = []
        for pattern in ["youtube_summary", "extract_wisdom"]:
            if pattern in pattern_outputs:
                missing_outputs.append((pattern, pattern_outputs[pattern]))

        new_content = _append_missing_sections(content, missing_outputs)

        # Add metadata if missing
        sections = classification["sections"]
        if not sections["has_channel_link"] and author_name != "Unknown":
            link_pattern = r"(\[Link\]\(https://(?:www\.)?youtube\.com/watch\?v=[^\)]+\))"
            author_line = f"[{author_name}]({channel_url})\n"
            new_content = re.sub(link_pattern, author_line + r"\1", new_content, count=1)

    else:
        result["status"] = "skipped"
        result["message"] = f"Unknown category: {category}"
        return result

    # Write upgraded note
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    status = "upgraded" if not result["patterns_failed"] else "partial"
    result["status"] = status
    result["message"] = (
        f"Patterns run: {', '.join(result['patterns_run'])}"
        + (f" | Failed: {', '.join(result['patterns_failed'])}" if result["patterns_failed"] else "")
    )
    return result


# ─── Scanning & Batch Processing ────────────────────────────────────────────

def scan_folder(folder_path, target_category=None):
    """Scan a folder recursively and classify all notes.

    Args:
        folder_path: Root folder to scan
        target_category: Filter by category (1, 2, 3, or None for all)

    Returns:
        dict mapping filepath -> classification
    """
    results = {}
    folder = Path(folder_path)

    for md_file in sorted(folder.rglob("*.md")):
        classification = classify_note(md_file)

        if classification["category"] == "skip":
            continue
        if classification["category"] == "compliant":
            continue

        if target_category is not None and classification["category"] != target_category:
            continue

        results[str(md_file)] = classification

    return results


def process_batch(
    folder_path, target_category=None, dry_run=False, verbose=False, limit=None
):
    """Process a batch of notes.

    Returns:
        dict with summary statistics
    """
    print(f"Scanning {folder_path}...")
    start_time = time.time()

    notes = scan_folder(folder_path, target_category)

    if limit:
        limited = dict(list(notes.items())[:limit])
        notes = limited

    # Print scan summary
    cat_counts = {}
    for classification in notes.values():
        cat = classification["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"\nFound {len(notes)} notes to process:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: str(x[0])):
        label = {
            1: "Old Fabric (wrap + prepend)",
            2: "Bare Content (full replace)",
            3: "Near-Compliant (append missing)",
        }.get(cat, str(cat))
        print(f"  Category {cat}: {count} — {label}")

    if dry_run:
        print("\n[DRY-RUN MODE — no files will be modified]")

    if not notes:
        print("Nothing to process.")
        return {"total": 0}

    # Process
    stats = {
        "total": len(notes),
        "upgraded": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "patterns_run": 0,
        "patterns_failed": 0,
        "errors": [],
    }

    for i, (filepath, classification) in enumerate(notes.items(), 1):
        title = Path(filepath).stem
        cat = classification["category"]

        # Throttle between notes to avoid YouTube rate limiting
        if i > 1 and not dry_run:
            time.sleep(INTER_NOTE_DELAY)

        if not verbose:
            print(f"[{i}/{len(notes)}] Cat {cat}: {title[:55]}...", end=" ", flush=True)

        try:
            result = process_note(filepath, classification, dry_run, verbose)
        except Exception as e:
            result = {"status": "failed", "message": str(e), "patterns_run": [], "patterns_failed": []}

        stats["patterns_run"] += len(result.get("patterns_run", []))
        stats["patterns_failed"] += len(result.get("patterns_failed", []))

        if result["status"] == "upgraded":
            stats["upgraded"] += 1
            if not verbose:
                print("✓")
        elif result["status"] == "partial":
            stats["partial"] += 1
            if not verbose:
                print(f"⚠ ({result['message']})")
        elif result["status"] == "dry_run":
            stats["skipped"] += 1
            if not verbose:
                print(f"→ {result['message']}")
        elif result["status"] == "failed":
            stats["failed"] += 1
            stats["errors"].append(f"{title}: {result['message']}")
            if not verbose:
                print(f"✗ ({result['message']})")
        else:
            stats["skipped"] += 1
            if not verbose:
                print(f"- {result['message']}")

    elapsed = time.time() - start_time
    stats["elapsed_seconds"] = elapsed

    # Print summary
    print(f"\n{'='*55}")
    print("Content Upgrader Summary")
    if dry_run:
        print("(DRY-RUN MODE — No files were modified)")
    print(f"{'='*55}")
    print(f"Total notes:         {stats['total']}")
    print(f"Upgraded:            {stats['upgraded']}")
    print(f"Partial:             {stats['partial']}")
    print(f"Failed:              {stats['failed']}")
    print(f"Skipped/dry-run:     {stats['skipped']}")
    print(f"Patterns run:        {stats['patterns_run']}")
    print(f"Patterns failed:     {stats['patterns_failed']}")

    if elapsed < 60:
        print(f"Elapsed:             {elapsed:.1f}s")
    else:
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        if h:
            print(f"Elapsed:             {int(h)}h {int(m)}m {s:.0f}s")
        else:
            print(f"Elapsed:             {int(m)}m {s:.0f}s")

    if stats["errors"]:
        print(f"\nErrors:")
        for err in stats["errors"][:20]:
            print(f"  - {err}")
        if len(stats["errors"]) > 20:
            print(f"  ... and {len(stats['errors']) - 20} more")

    print(f"{'='*55}")

    # Save report
    report_path = BACKUP_DIR / f"upgrader_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")

    return stats


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Upgrade YouTube notes to current template format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Categories:
  1  Old Fabric: Has extract_wisdom only → prepend summarize + youtube_summary
  2  Bare Content: No standard structure → full regeneration
  3  Near-Compliant: Has summarize, missing others → append missing sections

Examples:
  %(prog)s --folder /path/to/Youtube --dry-run
  %(prog)s --folder /path/to/Youtube --category 2 --limit 3 --verbose
  %(prog)s --folder /path/to/Youtube --category all
        """,
    )

    parser.add_argument(
        "--folder", required=True, help="Root folder containing YouTube notes"
    )
    parser.add_argument(
        "--category",
        default="all",
        help="Category to process: 1, 2, 3, or 'all' (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Scan and classify without modifying files"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Detailed output"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of files to process"
    )

    args = parser.parse_args()

    # Parse category
    if args.category == "all":
        target_cat = None
    else:
        try:
            target_cat = int(args.category)
            if target_cat not in (1, 2, 3):
                print("Error: category must be 1, 2, 3, or 'all'")
                sys.exit(1)
        except ValueError:
            print("Error: category must be 1, 2, 3, or 'all'")
            sys.exit(1)

    process_batch(
        folder_path=args.folder,
        target_category=target_cat,
        dry_run=args.dry_run,
        verbose=args.verbose,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
