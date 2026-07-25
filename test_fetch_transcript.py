"""Self-check for transcript fetching. Run: python test_fetch_transcript.py

Offline by default (SRT parsing only). Pass --live to also hit YouTube.
"""
import sys
import time
from fabric_utils import (
    FABRIC_TIMEOUT,
    FabricTimeout,
    _srt_to_timestamped,
    fetch_transcript,
    run_fabric_with_retry,
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
        "[00:00:02] Well guys, semiconductor stocks completely crashed this week",
        "[00:01:05] and investors are wondering",
    ], lines
    assert _srt_to_timestamped("") == []


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


def test_default_timeout_is_seven_minutes():
    assert FABRIC_TIMEOUT == 420, FABRIC_TIMEOUT


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
    print("srt parsing OK")
    test_timeout_raises_without_retrying()
    test_default_timeout_is_seven_minutes()
    test_timeout_is_reportable_without_enrichment()
    print("timeout handling OK")
    if "--live" in sys.argv:
        test_live()
        print("live fetch OK")
