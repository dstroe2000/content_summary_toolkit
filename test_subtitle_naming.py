"""Self-check for subtitle output naming. Run: python test_subtitle_naming.py

Covers the two derivations that have caller contracts attached: the default
`.summary.md` name (/ingest-vid cats and rm's it by that exact name) and the
sibling-video path used by --source-video.
"""
from pathlib import Path

from subtitle_summary_generator import source_video_path, summary_path


def test_default_name_is_stable():
    """/ingest-vid depends on this exact name -- do not flip the default."""
    assert summary_path(Path("/s/video.en.srt")) == Path("/s/video.en.srt.summary.md")
    assert summary_path(Path("/s/video.srt")) == Path("/s/video.srt.summary.md")


def test_flat_md_drops_the_summary_infix():
    assert summary_path(Path("/s/video.en.srt"), flat_md=True) == Path("/s/video.en.md")
    assert summary_path(Path("/s/video.srt"), flat_md=True) == Path("/s/video.md")


def test_source_video_survives_dotted_titles():
    """with_suffix('') twice turned 'Ep. 3 - Intro.srt' into 'Ep.mp4'."""
    assert source_video_path(Path("/s/video.en.srt")) == Path("/s/video.mp4")
    assert source_video_path(Path("/s/video.en-US.srt")) == Path("/s/video.mp4")
    assert source_video_path(Path("/s/video.srt")) == Path("/s/video.mp4")
    assert source_video_path(Path("/s/Ep. 3 - Intro.srt")) == Path("/s/Ep. 3 - Intro.mp4")
    assert source_video_path(Path("/s/GPT-4.5 review.vtt")) == Path("/s/GPT-4.5 review.mp4")


if __name__ == "__main__":
    test_default_name_is_stable()
    test_flat_md_drops_the_summary_infix()
    test_source_video_survives_dotted_titles()
    print("subtitle naming OK")
