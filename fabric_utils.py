"""
Shared utilities for fabric-based summary generators.

Centralizes logic that was previously duplicated across
``subtitle_summary_generator.py``, ``youtube_summary_generator.py``,
``blog_summary_generator.py``, ``youtube_content_upgrader.py`` and
``youtube_summary_patcher.py``:

- Text post-processing (filter ``<think>`` blocks, promote pseudo-headers)
- Markdown TOC generation from extracted H1 headers
- Shell command execution
- Fabric pattern invocation with retry + pseudo-header fallback

The retry helper (``run_fabric_with_retry``) accepts a pluggable validator
so individual tools can layer their own quality checks on top of the
default "must contain a level-1 header" rule.
"""

import contextlib
import html
import os
import re
import shutil
import signal
import subprocess
import shlex
import tempfile
import urllib.request


# Title cleanup: unicode -> ascii (nbsp becomes a plain space).
CHAR_REP = {"\xa0": " ", "’": "'", "‘": "'",
            "“": '"', "”": '"', "…": "..."}


def clean_title(title):
    """Apply the vault-title conventions to a raw YouTube/article title.

    Ported from the ``id-missing-yt`` skill so titles fetched here land under
    the same filenames that skill would have produced -- otherwise the same
    video ingested by URL and by ``[title](url)`` becomes two different notes.

    Strips Obsidian/macOS-illegal filename chars: ``: ? ! / \\ | " < > *``.
    ``/`` would make a subfolder, ``|`` breaks wikilink aliases, a leading dot
    makes a hidden note -- so leading dots are dropped. Trailing periods are
    KEPT (full-sentence titles legitimately end in '.'). ``#`` becomes ``num ``
    because a '#' in a basename reads as a heading anchor and breaks wikilinks.

    Idempotent: cleaning an already-clean title is a no-op.

    Args:
        title (str): Raw title as published by the source.

    Returns:
        str: Title safe to use as a note/subtitle filename.
    """
    for k, v in CHAR_REP.items():
        title = title.replace(k, v)
    title = re.sub(r"\s*:\s*", " - ", title)       # any colon -> ' - '
    title = re.sub(r"\s*[?!]+\s+", " - ", title)   # '? '/'! '/'?! ' -> ' - '
    title = re.sub(r"[?!]+", "", title)            # leftover ?/! -> drop
    title = re.sub(r"[/\\|]", "-", title)          # '/' subfolder, '|' alias-break
    title = title.replace('"', "")                 # illegal; keep ' which Obsidian allows
    title = re.sub(r"[<>*]", "", title)            # remaining illegal filename chars
    title = re.sub(r"#\s*", "num ", title)         # '#' breaks wikilinks -> 'num '
    title = title.replace("[", "(").replace("]", ")")  # brackets break [title](url)
    title = re.sub(r"\s{2,}", " ", title).strip()
    return re.sub(r"^\.+", "", title).strip()      # drop leading dots; keep trailing


def page_title(url, timeout=20):
    """Fetch an article URL and return its title, or "" if it can't be read.

    Prefers ``og:title`` over ``<title>``: publishers put the bare headline in
    the Open Graph tag and append site branding ("... | BBC Future") to the
    HTML title on many templates.

    Only the first 200 KB is read -- the head is all that matters and article
    pages routinely carry hundreds of KB of inlined JSON below it.

    Args:
        url (str): Article URL.
        timeout (int): Socket timeout in seconds.

    Returns:
        str: Cleaned title, or ``""`` when the fetch or the parse fails.
    """
    try:
        # Default urllib UA is blocked by most CDNs; a browser UA gets served.
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
    except Exception as e:
        print(f"Warning: Could not fetch page title: {e}")
        return ""

    for pattern in (r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)",
                    r"<title[^>]*>(.*?)</title>"):
        m = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
        if m:
            title = clean_title(html.unescape(m.group(1)).strip())
            if title:
                return title
    return ""


# Browser to pull YouTube auth cookies from. Many videos (age-gated, members-only,
# rate-limited, or region-restricted) now require authenticated cookies; pulling
# them straight from a logged-in browser profile avoids manual cookie exports.
# Override with env var YTDLP_COOKIES_BROWSER (e.g. firefox, brave, edge, safari)
# or set it to an empty string to disable.
YTDLP_COOKIES_BROWSER = os.environ.get("YTDLP_COOKIES_BROWSER", "chrome")


def ytdlp_cookie_opts():
    """Return yt_dlp Python-API opts dict snippet for cookies-from-browser.

    Empty dict if YTDLP_COOKIES_BROWSER is unset/empty so callers can
    unconditionally `**`-merge.
    """
    if not YTDLP_COOKIES_BROWSER:
        return {}
    return {"cookiesfrombrowser": (YTDLP_COOKIES_BROWSER,)}


def ytdlp_cookie_cli():
    """Return CLI fragment `--cookies-from-browser <browser>` (shell-quoted), or ''."""
    if not YTDLP_COOKIES_BROWSER:
        return ""
    return f"--cookies-from-browser {shlex.quote(YTDLP_COOKIES_BROWSER)}"


def ytdlp_meta_opts():
    """Return yt_dlp opts safe for metadata-only extraction (channel info, description).

    YouTube periodically changes its format manifest; yt-dlp's default format
    selector (`bestvideo*+bestaudio/best`) then raises "Requested format is not
    available" *during* `extract_info`, even with `skip_download=True`, because
    format selection runs before the download is skipped. Pinning `format='best'`
    plus `ignore_no_formats_error=True` makes metadata extraction tolerant of
    format-graph weirdness; we never need a real video stream here.
    """
    return {
        "format": "best",
        "ignore_no_formats_error": True,
        **ytdlp_cookie_opts(),
    }


# Default max attempts for fabric pattern calls when output fails validation.
# Fabric/LLM output is non-deterministic; sometimes the top ``# `` prefix is
# dropped, or the response is partially empty. We retry until validation
# passes or attempts are exhausted, then fall back to pseudo-header
# promotion.
MAX_FABRIC_ATTEMPTS = 3

# Seconds a single fabric pattern may run before it is treated as failed.
# Without this, subprocess.run(timeout=None) blocks the whole batch forever
# when the LLM backend stalls -- a 68k-token transcript against a local
# llama.cpp server is slow enough that "slow" and "hung" look identical.
# Override with env var FABRIC_TIMEOUT.
FABRIC_TIMEOUT = int(os.environ.get("FABRIC_TIMEOUT", 420))

# Generation time scales with input length, so a flat limit that fits a 100 KB
# transcript kills a 375 KB one mid-answer. Measured on a local backend:
# ~1 s/KB per pattern, extract_wisdom being the slowest. 2 s/KB leaves headroom
# without letting a genuinely hung backend hold the batch forever -- hence the
# ceiling. FABRIC_TIMEOUT stays the floor for small inputs.
FABRIC_SECONDS_PER_KB = float(os.environ.get("FABRIC_SECONDS_PER_KB", 2.0))
FABRIC_TIMEOUT_MAX = int(os.environ.get("FABRIC_TIMEOUT_MAX", 1800))


def timeout_for(path):
    """Return a size-scaled fabric timeout for the file at ``path``.

    Args:
        path (str or Path): Input file piped into fabric.

    Returns:
        int: Seconds, clamped to ``[FABRIC_TIMEOUT, FABRIC_TIMEOUT_MAX]``.
        Falls back to ``FABRIC_TIMEOUT`` if the file cannot be stat'd.
    """
    try:
        kb = os.path.getsize(path) / 1024
    except OSError:
        return FABRIC_TIMEOUT
    return int(min(FABRIC_TIMEOUT_MAX,
                   max(FABRIC_TIMEOUT, kb * FABRIC_SECONDS_PER_KB)))


# Context window of the configured backend, in tokens (LM Studio's
# loaded_context_length / Ollama's num_ctx). Override with MODEL_CONTEXT_TOKENS
# when pointing fabric at a smaller-window server -- overshooting it does not
# error, it silently truncates the transcript and yields a summary of whatever
# survived, which reads as a real note.
MODEL_CONTEXT_TOKENS = int(os.environ.get("MODEL_CONTEXT_TOKENS", 262144))

# Share of the window the input may occupy. The rest is the model's room to
# answer: a prompt that fills the window leaves nowhere to generate.
CONTEXT_INPUT_FRACTION = float(os.environ.get("CONTEXT_INPUT_FRACTION", 0.8))
MAX_INPUT_TOKENS = int(MODEL_CONTEXT_TOKENS * CONTEXT_INPUT_FRACTION)

# Measured on gemma-4-26b-a4b against a de-timestamped transcript:
# 100 KB -> 25,854 tokens. Timestamped text runs denser (~2.9) because
# "[00:00:00] " costs ~8 tokens per line, so always measure post-strip.
CHARS_PER_TOKEN = 3.9

# Timing noise carried by transcripts: the "[hh:mm:ss] " prefix written by
# fetch_transcript, and raw SRT cue blocks (index line + "00:00:01,000 -->"
# line). Worth ~35% of a transcript's tokens -- 46k of 132k on a 4,588-line
# file -- and worth nothing to summarize/extract_wisdom. The cached file keeps
# them, because the note enrichment pass cites timestamps; only the pipe into
# fabric is stripped.
STRIP_RES = (
    re.compile(r"^\[\d\d:\d\d:\d\d\][ \t]*", re.M),   # "[00:12:34] spoken text"
    re.compile(r"^.*-->.*$\n?", re.M),                # SRT cue timing line
    # ponytail: also eats a transcript line that is nothing but digits. Cheap
    # trade for dropping every SRT index line.
    re.compile(r"^\d+$\n?", re.M),
)


def read_stripped(path):
    """Return the file's text with timing markers and SRT cue scaffolding gone.

    Args:
        path (str or Path): Input file.

    Returns:
        str: Stripped text -- exactly what ``stripped_input`` pipes to fabric,
        so token estimates taken from it match what the backend receives.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    for pattern in STRIP_RES:
        text = pattern.sub("", text)
    return text


@contextlib.contextmanager
def stripped_input(path):
    """Yield a ``cat <tmpfile>`` command feeding ``path`` minus timing noise.

    Drop-in replacement for ``cat <file>`` at the head of a fabric pipe. The
    temp file lives for the duration of the ``with`` block, so several patterns
    can share one strip pass.

    Args:
        path (str or Path): Input file.

    Yields:
        str: Shell command emitting the stripped text, already quoted.
    """
    fd, tmp = tempfile.mkstemp(prefix="fabric_in_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(read_stripped(path))
        yield f"cat {shlex.quote(tmp)}"
    finally:
        os.unlink(tmp)


def estimate_tokens(path):
    """Estimate the token count fabric will send for ``path``, post-strip.

    Args:
        path (str or Path): Input file.

    Returns:
        int: Estimated tokens, or 0 if the file cannot be read.
    """
    try:
        return int(len(read_stripped(path)) / CHARS_PER_TOKEN)
    except OSError:
        return 0


def context_check(path):
    """Check whether ``path`` fits the backend's usable context window.

    Args:
        path (str or Path): Input file destined for a fabric pipe.

    Returns:
        tuple[bool, int]: ``(fits, estimated_tokens)``. ``fits`` is False when
        the input would be silently truncated by the backend.
    """
    tokens = estimate_tokens(path)
    return tokens <= MAX_INPUT_TOKENS, tokens


class FabricTimeout(Exception):
    """Raised when a fabric pattern exceeds its timeout.

    Carries enough context for the batch runner to report *what* stalled:
    the pattern name, the limit it blew through, and how long it actually ran.

    ``title`` and ``transcript_kb`` are enriched by the caller that knows them
    (see ``youtube_summary_generator``) and default to placeholders here. They
    are formatted into the batch error line, so leaving them unset would make
    the reporter raise AttributeError while formatting its own error message --
    turning one stalled video into a dead batch.
    """

    def __init__(self, pattern_label, limit, elapsed, title="", transcript_kb=0.0):
        self.pattern_label = pattern_label
        self.limit = limit
        self.elapsed = elapsed
        self.title = title
        self.transcript_kb = transcript_kb
        super().__init__(
            f"fabric -p {pattern_label} exceeded {limit}s (ran {elapsed:.0f}s)")


def filter_think_sections(text):
    """Remove ``<think>...</think>`` blocks from LLM/fabric output.

    Args:
        text (str): Raw text possibly containing ``<think>`` sections.

    Returns:
        str: Input stripped of think blocks and surrounding whitespace.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_first_level1_header(text):
    """Return the text of the first ``# `` header, trailing colons removed.

    Args:
        text (str): Markdown content.

    Returns:
        str or None: Header text (without ``# `` prefix and without trailing
        ``:``), or None if no level-1 header is present.
    """
    if not text:
        return None
    for line in text.split("\n"):
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            header_text = match.group(1)
            return re.sub(r":+\s*$", "", header_text).strip()
    return None


def generate_toc(headers):
    """Build an Obsidian-style TOC block from a list of header texts.

    Args:
        headers (list[str or None]): Headers for each section. ``None``
            entries (sections that failed to produce a header) are dropped.

    Returns:
        str: Multi-line TOC markdown starting with ``### TOC``, or empty
        string when no valid headers are supplied.
    """
    valid_headers = [h for h in headers if h is not None]
    if not valid_headers:
        return ""
    toc_lines = ["### TOC"]
    for header in valid_headers:
        toc_lines.append(f"- [[#{header}]]")
    return "\n".join(toc_lines)


def promote_pseudo_header(text):
    """Promote a plain heading-shaped first line to a level-1 header.

    Handles the case where fabric drops the leading ``# `` on its top
    header — e.g. outputting ``ONE SENTENCE SUMMARY:`` as plain text.
    Only inspects the first 5 non-empty lines and only promotes lines that
    look like uppercase headings (<=80 chars, uppercase letters/spaces/
    digits/hyphen, optional trailing colon). If the content already has a
    ``# `` header earlier, nothing is changed.

    Args:
        text (str): Filtered fabric output lacking a level-1 header.

    Returns:
        tuple[str, str | None]: ``(patched_text, header)`` where ``header``
        is the promoted text (colons stripped) or ``None`` if no suitable
        line was found — in which case ``patched_text`` equals the input.
    """
    if not text:
        return text, None

    lines = text.split("\n")
    seen_non_empty = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        seen_non_empty += 1
        if seen_non_empty > 5:
            break
        if stripped.startswith("#"):
            return text, None
        if len(stripped) <= 80 and re.match(r"^[A-Z][A-Z0-9 \-]+:?$", stripped):
            header_text = re.sub(r":+\s*$", "", stripped).strip()
            lines[idx] = f"# {stripped}"
            return "\n".join(lines), header_text

    return text, None


def run_command(command, verbose=False, timeout=None):
    """Execute a shell command and return ``(success, output_or_error)``.

    Args:
        command (str): Shell command line to run.
        verbose (bool): Print the command before executing.
        timeout (int or None): Seconds before SIGKILL. ``None`` = no limit.

    Returns:
        tuple[bool, str]: ``(success, output)``. On success, ``output`` is
        the stripped stdout. On failure (non-zero exit, timeout, exception),
        ``success`` is ``False`` and ``output`` contains the error text
        from stderr/exception.
    """
    try:
        if verbose:
            print(f"  Running: {command}")
        # ponytail: Popen + killpg rather than subprocess.run(timeout=...).
        # run() kills only the shell, so `cat x | fabric` leaves `fabric`
        # reparented to init, still holding its HTTP connection to the model
        # backend until fabric's own (much longer) internal timeout fires.
        # Own session => one killpg reaps the whole pipeline.
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            return False, "Command timed out"
        if proc.returncode == 0:
            return True, out.strip()
        return False, (err or "").strip()
    except Exception as e:
        return False, str(e)


def youtube_meta(video_url):
    """Fetch uploader, channel URL, description and title in a single extraction.

    Channel info, description and title come out of the same yt-dlp payload, so
    asking for them separately doubles the requests YouTube sees per video --
    which is exactly what gets a batch rate-limited. The title rides along free
    so a bare-URL entry can be named without a second lookup.

    Prefers the modern handle URL (``/@name``) over the legacy ``/channel/UC...``.

    Args:
        video_url (str): YouTube video URL.

    Returns:
        tuple[str, str, str, str]: ``(author_name, channel_url, description, title)``.
        ``title`` is raw (uncleaned) -- run it through ``clean_title`` before
        using it as a filename. Falls back to ``("Unknown", "", "", "")`` if
        extraction fails.
    """
    try:
        import yt_dlp

        ydl_opts = {"quiet": True, "no_warnings": True,
                    "skip_download": True, **ytdlp_meta_opts()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False) or {}

        author = info.get("uploader") or info.get("channel") or "Unknown"
        uploader_url = info.get("uploader_url") or ""
        channel_url = info.get("channel_url") or ""
        # Handle format lives in whichever field actually carries the '@'.
        if "/@" in uploader_url:
            channel_url = uploader_url
        elif "/@" not in channel_url and uploader_url:
            channel_url = uploader_url

        return (author, channel_url, (info.get("description") or "").strip(),
                (info.get("title") or "").strip())
    except Exception as e:
        print(f"Warning: Could not extract video metadata: {e}")
        return "Unknown", "", "", ""


_VIDEO_ID_RE = re.compile(r"(?:youtube\.com/watch\?(?:[^ ]*&)?v=|youtu\.be/)([\w-]{11})")


def video_id(video_url):
    """Extract the 11-char YouTube video id, or ``None`` if the URL has none.

    Transcripts are cached by this rather than by title. Two different videos can
    share a title -- this vault has 22 such pairs -- and a title-keyed cache made
    the second ingest silently reuse the first video's transcript, so fabric wrote
    a note whose content belonged to a different video entirely. The id is the only
    stable identity YouTube gives us.
    """
    m = _VIDEO_ID_RE.search(video_url or "")
    return m.group(1) if m else None


def fetch_transcript(video_url, dest_path):
    """Download a YouTube transcript to ``dest_path`` as ``[HH:MM:SS] text`` lines.

    Uses yt-dlp with browser cookies instead of ``fabric -y``: fabric's internal
    fetcher carries no cookies and gets "YouTube rate limit exceeded" on most
    requests, writing an empty file that downstream patterns then summarize into
    fabricated content.

    Args:
        video_url (str): YouTube video URL.
        dest_path (str): File to write the timestamped transcript to.

    A non-empty ``dest_path`` is reused as-is, making reruns resumable and free.
    Delete the file to force a re-download.

    Returns:
        tuple[bool, str]: ``(success, error_reason)``. ``error_reason`` is ``""``
        on success.
    """
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        print(f"... reusing cached transcript {dest_path}")
        return True, ""

    tmpdir = tempfile.mkdtemp(prefix="transcript_")
    try:
        def _ytdlp(cookie_cli, extra=""):
            # ponytail: same yt-dlp recipe regen_from_subs.sh already proved works.
            # `env -u NODE_OPTIONS` stops a sandboxed node from breaking the n-challenge solver.
            return run_command(
                f"env -u NODE_OPTIONS yt-dlp {cookie_cli} {extra} "
                # ponytail: an explicit list, not `en.*`. The regex is matched
                # case-insensitively, so it also pulled `en-ar`/`en-zh`/... -- English
                # machine-translated *from* 11 other languages. yt-dlp downloaded all
                # 13 tracks in alphabetical order, 429'd on `en-ar`, and aborted before
                # ever reaching `en-orig`. Ceiling: a rarer region tag (`en-NZ`, `en-IE`)
                # is not listed; add it here if one ever shows up.
                f"--write-sub --write-auto-sub --convert-subs srt "
                f"--sub-lang 'en-orig,en,en-US,en-GB,en-AU,en-CA,en-IN' "
                f"--skip-download --ignore-no-formats-error "
                f"-o {shlex.quote(os.path.join(tmpdir, 's.%(ext)s'))} {shlex.quote(video_url)}",
                timeout=300,
            )

        def _srts():
            # ponytail: biggest, not alphabetically first. `--sub-lang 'en.*'` also
            # matches ASR side-tracks like `en-en-<id>` that hold a single
            # "[NO SPEECH]" cue; those sort ahead of `s.en.srt` ('-' < '.') and the
            # 45-byte stub then passed the non-empty check and got summarized.
            # ponytail: `en.*` also matches `en-ar`/`en-zh` -- English *translated
            # from* another language's captions, a round trip that mangles names and
            # jargon. Rank the native tracks ahead of those, then biggest first.
            def _rank(f):
                tag = f[len("s."):-len(".srt")]
                native = 0 if tag in ("en-orig", "en") or tag.startswith("en-US") \
                    or tag.startswith("en-GB") else 1
                return (native, -os.path.getsize(os.path.join(tmpdir, f)))

            return sorted(
                (f for f in os.listdir(tmpdir) if f.endswith(".srt")),
                key=_rank,
            )

        def _best_lines():
            """Best available track as timestamped lines, or [] if none is usable."""
            for name in _srts():
                with open(os.path.join(tmpdir, name), "r",
                          encoding="utf-8", errors="replace") as f:
                    lines = _srt_to_timestamped(f.read())
                # ponytail: a caption track can be present but hold nothing to
                # summarize (YouTube's "[NO SPEECH]" ASR stub). Anything this short
                # is not a transcript, and fabric turns it into a confident fake.
                if sum(len(l.split("] ", 1)[-1]) for l in lines) >= 200:
                    return lines
            return []

        ok, err = _ytdlp(ytdlp_cookie_cli())
        lines = _best_lines()

        # ponytail: YouTube gates real auto-captions behind a PO token on the
        # cookie-authenticated path. The gate shows up two ways: no subtitle file
        # at all, or -- worse -- only the "[NO SPEECH]" ASR side-tracks, which look
        # like success. Retry anonymously on BOTH, since the anonymous path still
        # serves the real track. Cookies stay the default because they're what
        # keeps the *metadata* calls off the rate limiter. Upgrade path if the
        # anonymous path starts getting throttled: supply a real PO token instead.
        if not lines and ytdlp_cookie_cli():
            print("... no usable subtitles with cookies (PO token gate); retrying anonymously")
            ok, err = _ytdlp("")
            lines = _best_lines()

        # ponytail: last rung -- the `android`/`ios` players still hand out the
        # real `en-orig` track when both the cookie'd and anonymous `web`/`tv`
        # players are PO-token gated down to translated-only captions.
        if not lines:
            print("... still gated; retrying with android/ios player client")
            ok, err = _ytdlp("", "--extractor-args 'youtube:player_client=android,ios'")
            lines = _best_lines()

        if not lines:
            if _srts():
                return False, "no usable transcript (caption track has no speech)"
            return False, (err or "yt-dlp produced no subtitle file").splitlines()[-1][:200]

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _srt_to_timestamped(srt_text):
    """Convert SRT text to ``[HH:MM:SS] caption`` lines, dropping rolling repeats.

    YouTube auto-subs repeat the previous cue's text at the top of the next cue;
    consecutive duplicates are collapsed so the transcript reads once through.

    Some videos roll the caption a line at a time, so a cue is the previous
    cue's tail plus a few new words rather than an exact repeat. Dropping only
    whole duplicates leaves those transcripts at double length, which doubles
    the token bill and makes one utterance's keywords score twice.
    """
    out = []
    for block in re.split(r"\n\s*\n", srt_text.strip()):
        rows = [r for r in block.splitlines() if r.strip()]
        stamp = next((r for r in rows if "-->" in r), None)
        if stamp is None:
            continue
        text = " ".join(rows[rows.index(stamp) + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text).strip()
        prev = out[-1].split("] ", 1)[-1] if out else ""
        text = " ".join(text.split()[_overlap_words(prev, text):])
        if not text:
            continue
        out.append(f"[{stamp.split('-->')[0].strip().split(',')[0]}] {text}")
    return out


def _overlap_words(prev, text):
    """How many leading words of ``text`` repeat the tail of ``prev``.

    Word-level, not character-level: a character overlap happily cuts "and"
    down to "nd" when the previous cue merely ended in "a".
    """
    p, t = prev.split(), text.split()
    # ponytail: O(cue length^2), and a cue is a dozen words. Revisit only if
    # cues ever get long.
    for k in range(min(len(p), len(t)), 0, -1):
        if p[-k:] == t[:k]:
            return k
    return 0


def _default_validator(filtered_text):
    """Default fabric-output validator: require a level-1 header.

    Returns:
        tuple[bool, str]: ``(is_valid, reason)``.
    """
    if extract_first_level1_header(filtered_text) is None:
        return False, "no H1 header"
    return True, ""


def run_fabric_with_retry(
    command,
    pattern_label,
    verbose=False,
    max_attempts=MAX_FABRIC_ATTEMPTS,
    validate=None,
    timeout=FABRIC_TIMEOUT,
    retry_delay=0,
):
    """Run a fabric command with retry + pseudo-header promotion fallback.

    Pipeline per attempt:
        1. Run ``command`` via ``run_command``.
        2. If shell-success: strip ``<think>`` blocks via
           ``filter_think_sections``.
        3. Apply ``validate(filtered)`` — default requires a level-1
           header. Return the filtered text if validation passes.
        4. Otherwise loop up to ``max_attempts`` times.

    After all attempts fail, ``promote_pseudo_header`` tries to promote a
    plain heading-shaped line to ``# ...``. If that yields a valid H1 the
    call is considered successful.

    Args:
        command (str): Fabric shell command (typically ``cat file | fabric -p X``).
        pattern_label (str): Human label for log output (e.g. "summarize").
        verbose (bool): Emit per-attempt diagnostics.
        max_attempts (int): Upper bound on attempts; >= 1.
        validate (callable or None): ``(filtered_text) -> (is_valid, reason)``.
            Defaults to requiring an H1 header.
        timeout (int or None): Per-attempt timeout in seconds.
        retry_delay (int): Seconds to sleep between failed attempts.

    Returns:
        tuple[bool, str, str | None]: ``(success, filtered_output, header)``
        where ``success`` is True iff at least one attempt ran and the final
        output (possibly patched) contains a usable header. ``header`` is
        the extracted or promoted H1 text, or ``None`` if none could be
        produced.
    """
    if validate is None:
        validate = _default_validator

    import time

    last_output = ""
    last_header = None
    any_success = False

    for attempt in range(1, max_attempts + 1):
        started = time.time()
        success, raw = run_command(command, verbose=verbose, timeout=timeout)
        if not success:
            # A timeout means the model never answered. Retrying just burns
            # another full `timeout` on the same oversized input, so give up
            # immediately and let the caller count it as its own failure class.
            if raw == "Command timed out":
                raise FabricTimeout(pattern_label, timeout, time.time() - started)
            if verbose:
                snippet = raw[:100] if raw else ""
                print(f"  [{pattern_label}] attempt {attempt}/{max_attempts}: fabric failed ({snippet})")
            if attempt < max_attempts and retry_delay > 0:
                time.sleep(retry_delay)
            continue

        any_success = True
        filtered = filter_think_sections(raw)
        is_valid, reason = validate(filtered)
        last_output = filtered
        last_header = extract_first_level1_header(filtered)

        if is_valid:
            if verbose and attempt > 1:
                print(f"  [{pattern_label}] recovered on attempt {attempt}")
            return True, filtered, last_header

        if verbose:
            print(f"  [{pattern_label}] attempt {attempt}/{max_attempts}: {reason}, retrying")
        if attempt < max_attempts and retry_delay > 0:
            time.sleep(retry_delay)

    if any_success:
        # Last-resort: promote a plain heading-like first line to H1.
        # Handles deterministic fabric failures where retries cannot help.
        patched, promoted_header = promote_pseudo_header(last_output)
        if promoted_header is not None:
            if verbose:
                print(
                    f"  [{pattern_label}] promoted pseudo-header "
                    f"'{promoted_header}' after {max_attempts} failed attempts"
                )
            return True, patched, promoted_header
        if verbose:
            print(
                f"  [{pattern_label}] warning: no H1 after {max_attempts} attempts "
                "and no promotable line, using raw output"
            )
    return any_success, last_output, last_header
