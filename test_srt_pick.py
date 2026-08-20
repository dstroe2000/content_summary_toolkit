"""Self-check: fetch_transcript must pick the biggest srt, not the first alphabetically."""
import os, tempfile, sys
sys.path.insert(0, '/Users/danielstroe/work/content_summary_toolkit')
import fabric_utils as fu

STUB = "1\n00:00:00,000 --> 00:00:04,250\n[NO SPEECH]\n"
REAL = "".join(
    f"{i}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\nreal caption line number {i} with words\n\n"
    for i in range(1, 12))

def test():
    d = tempfile.mkdtemp()
    # '-' < '.', so the stub sorts first alphabetically -- the original bug.
    open(os.path.join(d, "s.en-en-XYZ.srt"), "w").write(STUB)
    open(os.path.join(d, "s.en.srt"), "w").write(REAL)
    names = sorted((f for f in os.listdir(d) if f.endswith(".srt")),
                   key=lambda f: os.path.getsize(os.path.join(d, f)), reverse=True)
    assert names[0] == "s.en.srt", f"picked {names[0]}, want s.en.srt"

    # the stub alone must be rejected, not summarized
    lines = fu._srt_to_timestamped(STUB)
    assert sum(len(l.split("] ", 1)[-1]) for l in lines) < 200, "stub should fail the floor"
    # a real transcript must clear it
    lines = fu._srt_to_timestamped(REAL)
    assert sum(len(l.split("] ", 1)[-1]) for l in lines) >= 200, "real transcript rejected"
    print("ok")

test()
