#!/bin/bash
# Fix notes that failed regen (long/oversized transcript -> exceeded model context).
# For each yt_generated md lacking "### TOC": build a CLEAN transcript (strip srt timecodes +
# dedup rolling captions; whisper fallback if no valid srt), truncate if still oversized,
# re-run fabric, overwrite the md (keep provenance header). .srt kept in subtitles.
# ponytail: cleaning cuts autosub bloat ~60-70%; hard char cap is the ceiling, chunking is the upgrade path.
set -u
ROOT="/Users/danielstroe/work/content_summary_toolkit"
YTDIR="$ROOT/output/yt_generated"
SUBDIR="$ROOT/output/subtitles"
LOG="$ROOT/output/fix_long.log"
MAXCHARS=420000   # ~105k tokens, under gemma-4 ctx; ponytail: truncation ceiling, map-reduce if lossy matters
: > "$LOG"
log(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

clean_srt(){  # clean_srt <srt> <out_txt> ; returns 1 if empty/binary
  awk 'BEGIN{prev=""} { if($0 ~ /^[0-9]+\r?$/) next; if($0 ~ /-->/) next;
        gsub(/^[ \t]+|[ \t\r]+$/,""); if($0=="") next;
        if($0!=prev){print; prev=$0} }' "$1" > "$2" 2>/dev/null
  [ -s "$2" ]
}

whisper_txt(){  # whisper_txt <url> <srt_dest> ; download audio -> srt
  local url="$1" dest="$2" tmp a f; tmp="$(mktemp -d)"
  env -u NODE_OPTIONS yt-dlp --cookies-from-browser chrome -x --audio-format mp3 \
    -o "$tmp/a.%(ext)s" "$url" >>"$LOG" 2>&1
  a="$(ls "$tmp"/a.* 2>/dev/null | head -1)"; [ -z "$a" ] && { rm -rf "$tmp"; return 1; }
  mlx_whisper "$a" --language en --model mlx-community/whisper-small-mlx \
    --output-format srt --output-dir "$tmp" >>"$LOG" 2>&1
  f="$(ls "$tmp"/*.srt 2>/dev/null | head -1)"
  if [ -n "$f" ]; then mv "$f" "$dest"; rm -rf "$tmp"; return 0; fi
  rm -rf "$tmp"; return 1
}

override_md(){ local orig="$1" summ="$2" tmp; tmp="$(mktemp)"
  awk 'BEGIN{h=1} /^---[[:space:]]*$/{if(h){h=0; next}} h==1{print}' "$orig" > "$tmp"
  printf '\n---\n\n' >> "$tmp"; cat "$summ" >> "$tmp"; mv "$tmp" "$orig"; }

shopt -s nullglob
i=0; ok=0; fail=0
for md in "$YTDIR"/*.md; do
  grep -q '### TOC' "$md" && continue   # already regenerated
  i=$((i+1)); base="$(basename "$md" .md)"; srt="$SUBDIR/$base.srt"
  log "[$i] $base"
  url="$(grep -oiE 'https?://(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]+' "$md" | head -1)"
  clean="$(mktemp --suffix=.txt 2>/dev/null || mktemp)"

  if [ -s "$srt" ] && clean_srt "$srt" "$clean"; then
    :
  else
    log "  no valid srt -> whisper"
    [ -z "$url" ] && { log "  FAIL no url"; fail=$((fail+1)); rm -f "$clean"; continue; }
    if whisper_txt "$url" "$srt" && clean_srt "$srt" "$clean"; then :; else
      log "  FAIL transcript"; fail=$((fail+1)); rm -f "$clean"; continue; fi
  fi

  cc=$(wc -c < "$clean")
  if [ "$cc" -gt "$MAXCHARS" ]; then
    log "  truncate $cc -> $MAXCHARS chars (long video, tail dropped)"
    head -c "$MAXCHARS" "$clean" > "$clean.t" && mv "$clean.t" "$clean"
  fi

  summ="$clean.summary.md"
  PYTHONPATH="$ROOT" python - "$clean" <<'PY' >>"$LOG" 2>&1
import sys; from subtitle_summary_generator import process_subtitle_file; from pathlib import Path
print("RESULT", process_subtitle_file(Path(sys.argv[1]), overwrite=True, verbose=True))
PY
  if [ -s "$summ" ]; then override_md "$md" "$summ"; rm -f "$summ" "$clean"; log "  OK"; ok=$((ok+1))
  else log "  FAIL fabric"; rm -f "$clean"; fail=$((fail+1)); fi
done
log "FIX DONE ok=$ok fail=$fail"
