#!/bin/bash
# Regenerate yt_generated summaries from real subtitles.
# Phase A: per md -> extract YT url -> subtitle .srt in output/subtitles/ (kept there)
# Phase B: fabric summary for ONLY the matching basenames (skips existing -> resumable)
# Phase C: overwrite each original yt_generated/<base>.md with the fresh summary (keep provenance header)
# Phase D: remove all *.summary.md from subtitles (only .srt stays there)
# ponytail: sequential, resumable via existing-file skip; targets exact basenames, no wasted fabric.
set -u
ROOT="/Users/danielstroe/work/content_summary_toolkit"
YTDIR="$ROOT/output/yt_generated"
SUBDIR="$ROOT/output/subtitles"
LOG="$ROOT/output/regen_run.log"
mkdir -p "$SUBDIR"
: > "$LOG"
log(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

get_srt(){  # get_srt <url> <dest_srt>
  local url="$1" dest="$2" tmp f a; tmp="$(mktemp -d)"
  env -u NODE_OPTIONS yt-dlp --cookies-from-browser chrome \
    --write-sub --write-auto-sub --sub-lang en --convert-subs srt \
    --skip-download -o "$tmp/s.%(ext)s" "$url" >>"$LOG" 2>&1
  f="$(ls "$tmp"/*.srt 2>/dev/null | head -1)"
  if [ -n "$f" ]; then mv "$f" "$dest"; rm -rf "$tmp"; return 0; fi
  log "  no subs -> whisper fallback"
  env -u NODE_OPTIONS yt-dlp --cookies-from-browser chrome -x --audio-format mp3 \
    -o "$tmp/a.%(ext)s" "$url" >>"$LOG" 2>&1
  a="$(ls "$tmp"/a.* 2>/dev/null | head -1)"
  [ -z "$a" ] && { rm -rf "$tmp"; return 1; }
  mlx_whisper "$a" --language en --model mlx-community/whisper-small-mlx \
    --output-format srt --output-dir "$tmp" >>"$LOG" 2>&1
  f="$(ls "$tmp"/*.srt 2>/dev/null | head -1)"
  if [ -n "$f" ]; then mv "$f" "$dest"; rm -rf "$tmp"; return 0; fi
  rm -rf "$tmp"; return 1
}

override_md(){  # override_md <orig_md> <summary_md>
  local orig="$1" summ="$2" tmp; tmp="$(mktemp)"
  awk 'BEGIN{h=1} /^---[[:space:]]*$/{if(h){h=0; next}} h==1{print}' "$orig" > "$tmp"
  printf '\n---\n\n' >> "$tmp"
  cat "$summ" >> "$tmp"
  mv "$tmp" "$orig"
}

shopt -s nullglob
mds=("$YTDIR"/*.md); n=${#mds[@]}
log "=== $n notes ==="

# ---------- Phase A: subtitles ----------
log "=== PHASE A: subtitles ==="
i=0; a_ok=0; a_fail=0
for md in "${mds[@]}"; do
  i=$((i+1)); base="$(basename "$md" .md)"; srt="$SUBDIR/$base.srt"
  log "[A $i/$n] $base"
  [ -s "$srt" ] && { log "  reuse existing srt"; a_ok=$((a_ok+1)); continue; }
  url="$(grep -oiE 'https?://(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]+' "$md" | head -1)"
  [ -z "$url" ] && { log "  SKIP no url"; a_fail=$((a_fail+1)); continue; }
  if get_srt "$url" "$srt"; then log "  got srt"; a_ok=$((a_ok+1)); else log "  FAIL sub"; a_fail=$((a_fail+1)); fi
done
log "PHASE A done ok=$a_ok fail=$a_fail"

# ---------- Phase B: fabric summaries (only matching basenames, resumable) ----------
log "=== PHASE B: fabric summaries ==="
i=0; b_ok=0; b_skip=0
for md in "${mds[@]}"; do
  i=$((i+1)); base="$(basename "$md" .md)"; srt="$SUBDIR/$base.srt"; summ="$SUBDIR/$base.srt.summary.md"
  log "[B $i/$n] $base"
  [ ! -s "$srt" ]  && { log "  no srt, skip"; b_skip=$((b_skip+1)); continue; }
  [ -s "$summ" ]   && { log "  summary exists"; b_ok=$((b_ok+1)); continue; }
  PYTHONPATH="$ROOT" python - "$srt" <<'PY' >>"$LOG" 2>&1
import sys; from subtitle_summary_generator import process_subtitle_file; from pathlib import Path
r = process_subtitle_file(Path(sys.argv[1]), overwrite=True, verbose=True)
print("RESULT", r)
sys.exit(0 if r.get("success") else 1)
PY
  if [ -s "$summ" ]; then log "  summarized"; b_ok=$((b_ok+1)); else log "  FAIL summary"; b_skip=$((b_skip+1)); fi
done
log "PHASE B done ok=$b_ok skip=$b_skip"

# ---------- Phase C: overwrite originals ----------
log "=== PHASE C: overwrite originals ==="
c_ok=0; c_skip=0
for md in "${mds[@]}"; do
  base="$(basename "$md" .md)"; summ="$SUBDIR/$base.srt.summary.md"
  if [ -s "$summ" ]; then override_md "$md" "$summ"; c_ok=$((c_ok+1)); else log "  no summary: $base"; c_skip=$((c_skip+1)); fi
done
log "PHASE C done overwritten=$c_ok skipped=$c_skip"

# ---------- Phase D: keep only .srt in subtitles ----------
log "=== PHASE D: clean subtitles dir ==="
rm -f "$SUBDIR"/*.summary.md
log "PHASE D done ($(ls -1 "$SUBDIR"/*.srt 2>/dev/null | wc -l | tr -d ' ') srt remain)"
log "ALL DONE"
