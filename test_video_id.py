"""Self-check for the transcript cache key. Run: python test_video_id.py

The cache used to be keyed by video title. fetch_transcript() reuses any non-empty
dest_path, so a second video sharing a title reused the first one's transcript and
fabric summarized the wrong video into the new note. These asserts pin the id
extraction that replaced it.
"""
from fabric_utils import video_id


def test_extracts_from_both_url_shapes():
    assert video_id("https://www.youtube.com/watch?v=ZF3XcIyUsAM") == "ZF3XcIyUsAM"
    assert video_id("https://youtu.be/13HP_bSeNjU") == "13HP_bSeNjU"
    assert video_id("http://m.youtube.com/watch?v=4OW6gU3y_rc") == "4OW6gU3y_rc"


def test_survives_extra_query_params():
    """Playlist and timestamp params sit either side of v= in real vault links."""
    assert video_id("https://www.youtube.com/watch?list=PLabc&v=ZF3XcIyUsAM") == "ZF3XcIyUsAM"
    assert video_id("https://www.youtube.com/watch?v=ZF3XcIyUsAM&t=42s") == "ZF3XcIyUsAM"


def test_ids_with_hyphen_and_underscore_survive():
    """`13HP_bSeNjU` and `y0EcjtOB_uU` are real ids; a \\w-only class drops the hyphen."""
    assert video_id("https://www.youtube.com/watch?v=y0EcjtOB_uU") == "y0EcjtOB_uU"
    assert video_id("https://www.youtube.com/watch?v=k69UeA__HYA") == "k69UeA__HYA"


def test_no_id_falls_back_to_none():
    """Callers fall back to title-keyed naming only when this returns None."""
    assert video_id("https://example.com/post") is None
    assert video_id("") is None
    assert video_id(None) is None


def test_two_titles_that_collide_get_different_keys():
    """The actual bug: same title, different videos, one shared cache file."""
    a = video_id("https://www.youtube.com/watch?v=4OW6gU3y_rc")   # Luma
    b = video_id("https://www.youtube.com/watch?v=ZF3XcIyUsAM")   # OrcDev
    assert a != b and a and b


if __name__ == "__main__":
    test_extracts_from_both_url_shapes()
    test_survives_extra_query_params()
    test_ids_with_hyphen_and_underscore_survive()
    test_no_id_falls_back_to_none()
    test_two_titles_that_collide_get_different_keys()
    print("video id keying OK")
