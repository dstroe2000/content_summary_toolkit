# Content Summary Toolkit Test Specification

## Overview

This specification outlines comprehensive unit tests for `content_summary_toolkit.py`, the main batch processor for YouTube and blog entry summaries. The tests cover all functions, edge cases, error conditions, and integration scenarios.

> **Status: not implemented.** `test_content_summary_toolkit.py` does not exist yet.
> Last refreshed 2026-07-25 against the subtitle/timeout error taxonomy
> (`SUBTITLE_ERROR` sentinel, `FabricTimeout` propagation, and the
> `subtitle_errors` / `timeout_errors` counters), which postdates the original
> draft.

## Test Structure

**Test File**: `test_content_summary_toolkit.py`  
**Framework**: `unittest` with `unittest.mock` for external dependencies  
**Coverage**: 100% function coverage with comprehensive edge case testing

The repo's existing checks (`test_fetch_transcript.py`, `test_subtitle_naming.py`)
are plain assert-based scripts with a `__main__` block, no framework. `unittest`
is proposed here only because this suite needs `patch` to stub the two
generators; keep the same "runnable with `python <file>`" property.

## Core Functions & Testing Requirements

### 1. `_classify_entry(line)` - Entry Classification

**Function Purpose**: Parses batch file lines into SKIP, YOUTUBE, BLOG, or INVALID categories

**SKIP Cases (6 tests):**
- Empty line: `""` → `('SKIP', None, None)`
- Whitespace only: `"   "` → `('SKIP', None, None)`
- Markdown header: `"# Section"` → `('SKIP', None, None)`
- Commentary: `"\\# Comment"` → `('SKIP', None, None)`
- Separator: `"---"` → `('SKIP', None, None)`
- Mixed whitespace: `"\t\n  # Header  \t"` → `('SKIP', None, None)`

**YOUTUBE Cases (4 tests):**
- Standard YouTube: `"[Video](https://youtube.com/watch?v=123)"` → `('YOUTUBE', 'Video', 'https://youtube.com/watch?v=123')`
- YouTube with query: `"[Video](https://youtube.com/watch?v=123&t=456)"` → YOUTUBE
- Short YouTube: `"[Video](https://youtu.be/abc)"` → YOUTUBE
- Case variations: `"[Video](https://YOUTUBE.COM/watch?v=123)"` → YOUTUBE

**BLOG Cases (3 tests):**
- Standard blog: `"[Article](https://example.com)"` → `('BLOG', 'Article', 'https://example.com')`
- HTTPS blog: `"[Post](https://blog.example.com/post)"` → BLOG
- HTTP blog: `"[Page](http://oldsite.com/page)"` → BLOG

**INVALID Cases (5 tests):**
- No brackets: `"Just some text"` → `('INVALID', None, None)`
- Missing opening bracket: `"title](url)"` → INVALID
- Missing closing bracket: `"[title](url"` → INVALID
- Empty brackets: `"[]()"` → INVALID
- Malformed: `"[title)url]"` → INVALID

**Edge Cases (4 tests):**
- Unicode title: `"[Título español](https://example.com)"` → BLOG
- URLs with parens: `"[Test](https://example.com/page(a)b)"` → BLOG (regex handles this)
- Very long title: 500+ chars → Should work
- Empty title: `"[](https://example.com)"` → BLOG (regex captures empty string)

### 2. `_process_youtube(entry)` & `_process_blog(entry)` - Processing Wrappers

**Function Purpose**: Call external generators, translating their failure modes
into values the batch loop can count. The two wrappers do **not** share a return
contract — `_process_youtube` returns a four-way value, `_process_blog` a bool.

**YouTube Processing (6 tests):**

`_process_youtube` returns `str | FabricTimeout`:

| generator behaviour | wrapper returns | batch counts as |
|---|---|---|
| returns normally | `'ok'` | `processed_youtube` |
| returns `SUBTITLE_ERROR` (`"subtitle_error"`) | `SUBTITLE_ERROR` | `subtitle_errors` |
| raises `FabricTimeout` | the exception instance | `timeout_errors` |
| raises any other `Exception` | `'error'` | generic `errors` entry |

- Success → `'ok'`
- `process_youtube_entry` returns `SUBTITLE_ERROR` → returned verbatim, **not** `'error'`
- `FabricTimeout` raised → instance returned, not re-raised; `pattern_label`,
  `elapsed` and `transcript_kb` survive the round trip
- Generic exception → prints error, returns `'error'`
- Sentinel is a plain string, so a generator returning the literal
  `"subtitle_error"` is indistinguishable — pin the value so a future
  refactor to an enum/object is caught
- Mock verification that the `"[title](url)"` string is passed through unchanged

**Blog Processing (3 tests):**
- Success → returns `True`
- Exception during processing → prints error, returns `False`
- Mock verification that correct entry string is passed

Note the asymmetry: blog processing has no subtitle or timeout path, so a
stalled fabric pattern on a blog entry surfaces as a generic `False`.

### 3. `process_batch_file(batch_file_path)` - Main Orchestrator

**Function Purpose**: File validation → Statistics init → Line processing → Report generation

**File Handling (4 tests):**
- Non-existent file → Returns False, prints error
- Permission denied → Returns False, prints error
- Empty file → Returns True, zero statistics
- File with only skips → Returns True, skipped count only

**Mixed Content Processing (4 tests):**
- All YouTube entries → Correct YouTube count
- All blog entries → Correct blog count
- Mixed valid entries → Correct counts for each type
- Mixed with invalids → Correct invalid count and error messages

**Statistics Tracking (7 tests):**

`stats` carries eight keys: `total`, `processed_youtube`, `processed_blog`,
`skipped`, `invalid`, `subtitle_errors`, `timeout_errors`, `errors`.

- Verify all statistics counters update correctly
- Error collection and reporting
- Success rate calculation (with division by zero protection)
- Subtitle failure → `subtitle_errors` increments **and** an
  `f"Line {n}: SUBTITLE ERROR - {title}"` string lands in `errors`; the entry is
  counted once, not in both `subtitle_errors` and the generic failure branch
- Timeout → `timeout_errors` increments and the message interpolates all three
  fields: `f"Line {n}: TIMEOUT ({pattern_label}, {elapsed:.0f}s, {transcript_kb:.0f} KB) - {title}"`
- A batch mixing ok / subtitle-error / timeout / generic-failure entries →
  each of the four lands in exactly one bucket
- Both error counters stay at 0 for a batch of blog-only entries

**Progress Output (2 tests):**
- Verify progress messages printed for valid entries
- Verify error messages printed for invalid entries
- Silent processing for skipped entries

### 4. `_print_summary_report(stats, elapsed_time)` - Reporting

**Function Purpose**: Formatted statistics display with calculations

**Statistics Display (5 tests):**
- All statistics displayed correctly in formatted output
- Error list displayed when errors present
- No errors section when no errors
- `Subtitle errors:` and `Timeout errors:` lines are present, read via
  `stats.get(key, 0)` — a stats dict missing those keys must print `0`, not raise
- Success rate denominator is `processed_youtube + processed_blog + len(errors)`;
  subtitle and timeout failures reach it only through their `errors` entries, so
  they must not be double-counted

**Time Formatting (4 tests):**
- Seconds: `45.67` → `"45.67 seconds"`
- Minutes: `125.5` → `"2 min 5.50 sec"`
- Hours: `3661.25` → `"1 hr 1 min 1.25 sec"`
- Edge cases: `0.0`, `59.99`, `3599.99`

**Success Rate Calculation (3 tests):**
- Normal case: processed=8, errors=2 → `"80.0%"`
- No attempts: processed=0, errors=0 → No success rate shown
- All failures: processed=0, errors=5 → `"0.0%"`

### 5. Integration Tests

**End-to-End Scenarios (3 tests):**
- Complete batch file processing with mocks
- Error handling throughout pipeline
- Statistics accuracy across full workflow

**Mock Verification (2 tests):**
- Correct entry strings passed to external functions
- Proper exception handling and error collection

## Implementation Considerations

### Mocking Strategy
- Mock `youtube_summary_generator.process_youtube_entry`
- Mock `blog_summary_generator.process_blog_entry`
- Use `patch` decorators for clean test isolation

### Test Data
- Create temporary files for batch processing tests
- Use `tempfile` module for safe file operations
- Include real examples from `test.md` as test cases

### Coverage Goals
- 100% function coverage
- All edge cases and error conditions
- Realistic integration scenarios

### Test Organization
- Separate test classes for logical grouping
- Descriptive test method names
- Setup/teardown for temporary resources

## Critical Edge Cases Identified

### Entry Classification Edge Cases
- Empty brackets: `[]()` → INVALID (regex won't match)
- Missing brackets: `[title](url` or `title](url)` → INVALID
- URLs with parentheses: `[Test](http://example.com/page(with)parens)` → Works (regex handles nested parens)
- Unicode in titles/URLs: `[Título](http://ñandu.com)` → Must handle UTF-8
- Very long titles/URLs: 1000+ characters → Should work (no length limits)
- Case sensitivity: `YouTube.COM`, `YOUTUBE.COM` → Still detects as YouTube

### File Processing Edge Cases
- Empty files → Process successfully with all zeros
- Files with only whitespace → All lines skipped
- Mixed line endings (Windows \\r\\n, Unix \\n) → Should handle (Python universal newline)
- Very large files → Memory usage (no obvious limits)
- Files with invalid UTF-8 → Encoding error handling
- Permission issues → Proper error messages

### Statistics & Reporting Edge Cases
- Division by zero: If total_attempted = 0, success rate calculation skipped
- Error message truncation: `line.strip()[:50]` in invalid format errors
- Time edge cases: 0 seconds, negative time (unlikely), very large times

### Error Taxonomy Edge Cases
- **`FabricTimeout` without `transcript_kb`**: the attribute is not set by
  `FabricTimeout.__init__` — `youtube_summary_generator.py` attaches it on the
  way out (`e.transcript_kb = transcript_kb`) just before re-raising. A timeout
  escaping any path that skips that annotation makes the batch reporter raise
  `AttributeError` while formatting the message, killing the run mid-batch.
  Regression test: raise a bare `FabricTimeout("p", 420, 421.0)` from the mocked
  generator and assert the batch still completes.
- **Sentinel vs. generic failure**: `_process_youtube` compares with `==`, so any
  return value equal to `"subtitle_error"` is treated as a subtitle failure
- **Timeouts are not retried**: one stalled pattern costs one `timeout_errors`
  increment, never `MAX_FABRIC_ATTEMPTS` of them
- **Partial notes**: a subtitle failure aborts before any fabric call and writes
  no `.md`; a timeout aborts mid-pipeline after earlier patterns succeeded.
  Neither leaves a partial note behind

## Dependencies to Mock

### External Functions
- `process_youtube_entry(entry)`: Takes markdown entry string; returns
  `SUBTITLE_ERROR` when the transcript can't be fetched, raises `FabricTimeout`
  when a pattern stalls, may raise anything else
- `process_blog_entry(entry)`: Takes markdown entry string, can raise exceptions
- Both expect format: `"[title](url)"`

### Imported Symbols
- `SUBTITLE_ERROR` (from `youtube_summary_generator`) — the string `"subtitle_error"`
- `FabricTimeout` (from `fabric_utils`) — constructor takes
  `(pattern_label, limit, elapsed)`; `transcript_kb` and `title` are attached
  by the caller afterwards, so mocks must set them to mimic a real timeout

### File Operations
- File reading with UTF-8 encoding
- File existence and permission checks
- Temporary file creation for testing

## Test File Structure Template

```python
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
from fabric_utils import FabricTimeout
from youtube_summary_generator import SUBTITLE_ERROR
from content_summary_toolkit import (
    _classify_entry,
    _process_youtube,
    _process_blog,
    process_batch_file,
    _print_summary_report
)

def timeout(pattern="extract_wisdom", limit=420, elapsed=421.0, kb=229.0):
    """Build a FabricTimeout shaped like one that survived the generator."""
    e = FabricTimeout(pattern, limit, elapsed)
    e.transcript_kb = kb          # attached by youtube_summary_generator, not __init__
    e.title = "Some Video"
    return e

class TestClassifyEntry(unittest.TestCase):
    # SKIP cases tests...

class TestProcessingFunctions(unittest.TestCase):
    # Processing wrapper tests: 'ok' / SUBTITLE_ERROR / FabricTimeout / 'error'...

class TestBatchProcessing(unittest.TestCase):
    # Main orchestrator tests, incl. the four-way counter split...

class TestSummaryReport(unittest.TestCase):
    # Reporting function tests, incl. missing-counter .get() defaults...

class TestIntegration(unittest.TestCase):
    # End-to-end tests...

if __name__ == '__main__':
    unittest.main()
```

## Success Criteria

- All tests pass consistently
- 100% code coverage of `content_summary_toolkit.py`
- Tests run in < 30 seconds
- No external dependencies required (all mocked)
- Tests are maintainable and well-documented