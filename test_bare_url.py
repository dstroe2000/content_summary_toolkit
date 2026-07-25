"""Self-check for bare-URL entries. Run: python test_bare_url.py

Covers the two halves of the feature: the classifier accepting a naked URL,
and clean_title() producing the same filenames the id-missing-yt skill would
have produced -- if those two drift, the same video ingested by URL and by
[title](url) becomes two notes.
"""
from content_summary_toolkit import _classify_entry
from fabric_utils import clean_title

YT = "https://www.youtube.com/watch?v=yC9cd3gKaIc"


def test_bare_youtube_url_classifies_with_no_title():
    assert _classify_entry(YT) == ("YOUTUBE", None, YT)
    assert _classify_entry(f"  {YT}  \n") == ("YOUTUBE", None, YT)
    assert _classify_entry("https://youtu.be/yC9cd3gKaIc") == (
        "YOUTUBE", None, "https://youtu.be/yC9cd3gKaIc")


def test_bare_article_url_classifies_as_blog():
    url = "https://www.bbc.com/future/article/20260513-your-car-is-spying-on-you"
    assert _classify_entry(url) == ("BLOG", None, url)


def test_markdown_entries_are_untouched():
    """The [title](url) path must keep working exactly as before."""
    assert _classify_entry(f"[From LOOPS to GRAPHS]({YT})") == (
        "YOUTUBE", "From LOOPS to GRAPHS", YT)
    assert _classify_entry("[Article](https://example.com/a)") == (
        "BLOG", "Article", "https://example.com/a")


def test_non_url_lines_stay_skip_or_invalid():
    assert _classify_entry("") == ("SKIP", None, None)
    assert _classify_entry("# Header") == ("SKIP", None, None)
    assert _classify_entry("---") == ("SKIP", None, None)
    assert _classify_entry("just some prose") == ("INVALID", None, None)
    # Prose *containing* a URL is not a bare URL -- the whole line must be one.
    assert _classify_entry(f"watch {YT} later") == ("INVALID", None, None)


def test_clean_title_matches_the_id_missing_yt_conventions():
    assert clean_title("$10K/mo | Matt Pocock") == "$10K-mo - Matt Pocock"
    assert clean_title("…we need to talk.") == "we need to talk."   # trailing '.' kept
    assert clean_title("...leading dots") == "leading dots"         # leading dots dropped
    assert clean_title("#4 Allan Guo") == "num 4 Allan Guo"         # '#' breaks wikilinks
    assert clean_title("Advanced RAG [2025]") == "Advanced RAG (2025)"
    assert clean_title('Viral "25K" List') == "Viral 25K List"
    assert clean_title("RAG:Explained") == "RAG - Explained"


def test_clean_title_is_idempotent():
    """Markdown entries arrive pre-cleaned; re-cleaning must not rename them."""
    for raw in ("$10K/mo | Matt Pocock", "RAG: Explained", "Why? Because.",
                "From LOOPS to GRAPHS - AI Agents Learn Graph-Based Error Corrections"):
        once = clean_title(raw)
        assert clean_title(once) == once, raw


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nAll bare-URL checks passed.")
