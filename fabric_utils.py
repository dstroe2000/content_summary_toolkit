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

import os
import re
import subprocess
import shlex


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
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, (result.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


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
    timeout=None,
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
        success, raw = run_command(command, verbose=verbose, timeout=timeout)
        if not success:
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
