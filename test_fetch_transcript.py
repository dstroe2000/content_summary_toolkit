"""Self-check for transcript fetching. Run: python test_fetch_transcript.py

Offline by default (SRT parsing only). Pass --live to also hit YouTube.
"""
import os
import shlex
import subprocess
import sys
import time
from fabric_utils import (
    CHARS_PER_TOKEN,
    FABRIC_TIMEOUT,
    FABRIC_TIMEOUT_MAX,
    FabricTimeout,
    _overlap_words,
    _srt_to_timestamped,
    fetch_transcript,
    MAX_INPUT_TOKENS,
    context_check,
    read_stripped,
    run_command,
    run_fabric_with_retry,
    stripped_input,
    timeout_for,
)

SRT = """1
00:00:00,080 --> 00:00:02,000
Well guys, semiconductor stocks

2
00:00:02,000 --> 00:00:04,120
Well guys, semiconductor stocks
completely crashed this week

3
00:01:05,500 --> 00:01:07,000
<c.colorE5E5E5>and investors are</c> wondering
"""


def test_srt_to_timestamped():
    lines = _srt_to_timestamped(SRT)
    assert lines == [
        "[00:00:00] Well guys, semiconductor stocks",
        "[00:00:02] completely crashed this week",
        "[00:01:05] and investors are wondering",
    ], lines
    assert _srt_to_timestamped("") == []


ROLLING_SRT = """1
00:00:02,000 --> 00:00:04,000
If you're coding with Cloud or CodeX

2
00:00:04,000 --> 00:00:06,000
If you're coding with Cloud or CodeX today, there's a new paradigm

3
00:00:06,000 --> 00:00:08,000
today, there's a new paradigm you're going to love
"""


def test_rolling_captions_are_merged_not_duplicated():
    """A cue repeating the previous cue's TAIL, not the whole previous cue.

    Trimming only exact duplicates leaves such a transcript at double length,
    and lets "paradigm" read as two separate mentions to a keyword search.
    """
    lines = _srt_to_timestamped(ROLLING_SRT)
    assert lines == [
        "[00:00:02] If you're coding with Cloud or CodeX",
        "[00:00:04] today, there's a new paradigm",
        "[00:00:06] you're going to love",
    ], lines
    # word-level: a shared trailing "a" must not eat the next cue's "and"
    assert _overlap_words("this is a", "and then") == 0


def test_timeout_raises_without_retrying():
    """A stalled pattern must abort at once, not burn max_attempts x timeout."""
    started = time.time()
    try:
        run_fabric_with_retry("sleep 30", "fake_pattern", timeout=1)
    except FabricTimeout as e:
        elapsed = time.time() - started
        assert e.pattern_label == "fake_pattern", e.pattern_label
        assert e.limit == 1, e.limit
        assert elapsed < 3, f"retried instead of failing fast: {elapsed:.1f}s"
    else:
        raise AssertionError("expected FabricTimeout")


def test_timeout_kills_the_whole_pipeline():
    """No pipe stage may outlive the timeout -- an orphan holds the backend."""
    import os
    import subprocess
    marker = "/tmp/_orphan_check.pid"
    if os.path.exists(marker):
        os.remove(marker)
    # Second stage of the pipe: the one subprocess.run(timeout=) used to orphan.
    ok, _ = run_command(f"echo x | (echo $$ > {marker}; sleep 30)", timeout=1)
    assert not ok
    with open(marker) as f:
        pid = int(f.read().strip())
    os.remove(marker)
    alive = subprocess.run(["ps", "-p", str(pid)],
                           capture_output=True).returncode == 0
    assert not alive, f"pid {pid} survived the timeout"


def test_default_timeout_is_seven_minutes():
    assert FABRIC_TIMEOUT == 420, FABRIC_TIMEOUT


def test_timeout_scales_with_input_size():
    """The 375 KB transcript that blew the flat 420s must now get more room."""
    path = "/tmp/_timeout_scale_check.txt"
    with open(path, "w") as f:
        f.write("x" * 10 * 1024)          # 10 KB -- below the floor
    assert timeout_for(path) == FABRIC_TIMEOUT, timeout_for(path)
    with open(path, "w") as f:
        f.write("x" * 375 * 1024)         # the transcript from the failing run
    assert timeout_for(path) == 750, timeout_for(path)
    with open(path, "w") as f:
        f.write("x" * 4000 * 1024)        # absurd input stays capped
    assert timeout_for(path) == FABRIC_TIMEOUT_MAX, timeout_for(path)
    os.remove(path)
    # A missing file must not crash the caller before fabric even runs.
    assert timeout_for(path) == FABRIC_TIMEOUT


def test_strip_removes_timing_noise_and_nothing_else():
    """What we measure must be exactly what gets piped to fabric."""
    path = "/tmp/_strip_check.srt"
    with open(path, "w") as f:
        f.write("1\n00:00:00,080 --> 00:00:02,000\nsemiconductor stocks\n\n"
                "[00:01:05] and investors are wondering\n"
                "a line mentioning 2026 survives\n")
    text = read_stripped(path)
    assert "-->" not in text, text
    assert "00:00:00,080" not in text, text
    assert "semiconductor stocks" in text, text
    assert "and investors are wondering" in text, text
    assert "[00:01:05]" not in text, text
    assert "a line mentioning 2026 survives" in text, text
    # The pipe command must feed that same text, not the raw file.
    with stripped_input(path) as cmd:
        piped = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True).stdout
        assert piped == text, repr(piped)
        tmp = shlex.split(cmd)[1]
    assert not os.path.exists(tmp), "temp input leaked"
    os.remove(path)


def test_oversized_input_is_rejected_not_truncated():
    """Silent backend truncation is the failure this guard exists to prevent."""
    path = "/tmp/_oversize_check.txt"
    with open(path, "w") as f:
        f.write("word " * int(MAX_INPUT_TOKENS * CHARS_PER_TOKEN / 5) * 2)
    fits, tokens = context_check(path)
    assert not fits, tokens
    assert tokens > MAX_INPUT_TOKENS, tokens
    with open(path, "w") as f:
        f.write("[00:00:01] short transcript\n")
    fits, tokens = context_check(path)
    assert fits and tokens < 20, (fits, tokens)
    os.remove(path)


def test_timeout_is_reportable_without_enrichment():
    """The batch reporter formats these fields; unset ones killed the run."""
    e = FabricTimeout("extract_wisdom", 420, 421.0)
    assert e.transcript_kb == 0.0, e.transcript_kb
    assert e.title == "", e.title
    # Exactly the interpolation content_summary_toolkit does per timeout.
    line = (f"TIMEOUT ({e.pattern_label}, {e.elapsed:.0f}s, "
            f"{e.transcript_kb:.0f} KB) - {e.title}")
    assert line == "TIMEOUT (extract_wisdom, 421s, 0 KB) - ", line
    enriched = FabricTimeout("summarize", 420, 500.0, "Some Video", 229.4)
    assert (enriched.title, round(enriched.transcript_kb)) == ("Some Video", 229)


def test_live():
    ok, reason = fetch_transcript(
        "https://www.youtube.com/watch?v=Oz4p0ESLJV0", "/tmp/_transcript_check.txt")
    assert ok, f"fetch failed: {reason}"
    with open("/tmp/_transcript_check.txt") as f:
        head = f.readline()
    assert head.startswith("[00:00:"), head


if __name__ == "__main__":
    test_srt_to_timestamped()
    test_rolling_captions_are_merged_not_duplicated()
    print("srt parsing OK")
    test_timeout_raises_without_retrying()
    test_timeout_kills_the_whole_pipeline()
    test_default_timeout_is_seven_minutes()
    test_timeout_scales_with_input_size()
    test_strip_removes_timing_noise_and_nothing_else()
    test_oversized_input_is_rejected_not_truncated()
    test_timeout_is_reportable_without_enrichment()
    print("timeout handling OK")
    if "--live" in sys.argv:
        test_live()
        print("live fetch OK")
