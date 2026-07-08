#!/usr/bin/env bash
# Trim and re-encode the raw Playwright .webm captures into web-ready demo
# loops: a small H.264 MP4 (universal), an optional VP9 WebM (shipped only when
# smaller), and a WebP poster from the final frame.
#
# Dev-only. Requires ffmpeg (for video) and the docs-site sharp dep (for the
# WebP poster — this ffmpeg build has no libwebp encoder). Called by
# record_demos.sh after recording.
set -euo pipefail

cd "$(dirname "$0")/.."      # -> docs-site
RAW_DIR="_demos/raw"
OUT_DIR="public/assets/demos"
CRF="${DEMO_CRF:-28}"             # H.264 quality; higher = smaller
MAX_BYTES=$((1500 * 1024))        # 1.5 MB hard cap per plan

mkdir -p "$OUT_DIR"

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg required (brew install ffmpeg)." >&2; exit 1; }

sizeof() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1"; }

for webm in "$RAW_DIR"/*.webm; do
  [ -f "$webm" ] || { echo "No raw captures in $RAW_DIR" >&2; exit 1; }
  name="$(basename "${webm%.webm}")"
  echo "── $name ──"

  mp4="$OUT_DIR/$name.mp4"
  vp9="$OUT_DIR/$name.webm"
  poster="$OUT_DIR/$name-poster.webp"
  poster_png="$RAW_DIR/$name-poster.png"

  # Trim window: prefer the recorder's measured sidecar (skips the page-load
  # lead-in), fall back to a small fixed trim.
  meta="$RAW_DIR/$name.json"
  if [ -f "$meta" ]; then
    start="$(node -e "process.stdout.write(String(require('./$meta').trimStart))")"
    dur="$(node -e "process.stdout.write(String(require('./$meta').duration))")"
    trim_args=(-ss "$start" -t "$dur")
  else
    trim_args=(-ss 0.7)
  fi

  # H.264 MP4 — yuv420p for universal playback, faststart for streaming, no audio.
  ffmpeg -y -loglevel error "${trim_args[@]}" -i "$webm" \
    -c:v libx264 -crf "$CRF" -preset slow -pix_fmt yuv420p \
    -movflags +faststart -an "$mp4"

  # VP9 WebM — keep only if it beats the MP4 on size.
  ffmpeg -y -loglevel error "${trim_args[@]}" -i "$webm" \
    -c:v libvpx-vp9 -crf 36 -b:v 0 -an "$vp9"
  if [ "$(sizeof "$vp9")" -ge "$(sizeof "$mp4")" ]; then
    echo "  webm not smaller than mp4 — dropping webm"
    rm -f "$vp9"
  fi

  # Poster: the trimmed video's final frame → PNG (ffmpeg) → WebP q82 (sharp;
  # this ffmpeg build has no libwebp encoder). Seek to the end of the trim
  # window so the poster matches the video's last frame exactly.
  if [ -f "$meta" ]; then
    poster_at="$(node -e "const m=require('./$meta');process.stdout.write(String(m.trimStart+m.duration-0.15))")"
    ffmpeg -y -loglevel error -ss "$poster_at" -i "$webm" -vframes 1 -c:v png "$poster_png"
  else
    ffmpeg -y -loglevel error -sseof -0.35 -i "$webm" -vframes 1 -c:v png "$poster_png"
  fi
  node -e "require('sharp')('$poster_png').resize({width:1280,withoutEnlargement:true}).webp({quality:72}).toFile('$poster').then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1)})"
  rm -f "$poster_png"

  mp4_bytes="$(sizeof "$mp4")"
  printf "  mp4:    %s KB\n" "$((mp4_bytes / 1024))"
  [ -f "$vp9" ] && printf "  webm:   %s KB\n" "$(( $(sizeof "$vp9") / 1024))"
  printf "  poster: %s KB\n" "$(( $(sizeof "$poster") / 1024))"
  if [ "$mp4_bytes" -gt "$MAX_BYTES" ]; then
    echo "  ⚠ $name.mp4 exceeds 1.5 MB cap — raise DEMO_CRF or shorten the scene." >&2
  fi
done

echo "Encoded demos → $OUT_DIR"
