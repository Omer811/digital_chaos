#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Convert City Walk recordings from WEBM to MP4 and/or MOV.

Usage:
  ./city_walk/postprocess_video.sh --input <file-or-dir> [--format mp4|mov|both] [--output-dir <dir>] [--overwrite]

Examples:
  ./city_walk/postprocess_video.sh --input ~/Downloads/city_walk_london_2026-03-09.webm --format both
  ./city_walk/postprocess_video.sh --input ~/Downloads --format mp4 --output-dir ./output/videos

Notes:
  - Requires ffmpeg in PATH.
  - If --input is a directory, all *.webm files in that directory are converted (non-recursive).
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' not found in PATH." >&2
    exit 1
  fi
}

INPUT=""
FORMAT="both"
OUTPUT_DIR=""
OVERWRITE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT="${2:-}"
      shift 2
      ;;
    --format)
      FORMAT="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --overwrite)
      OVERWRITE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$INPUT" ]]; then
  echo "Error: --input is required." >&2
  usage
  exit 1
fi

if [[ "$FORMAT" != "mp4" && "$FORMAT" != "mov" && "$FORMAT" != "both" ]]; then
  echo "Error: --format must be one of: mp4, mov, both." >&2
  exit 1
fi

require_cmd ffmpeg

collect_inputs() {
  local src="$1"
  if [[ -f "$src" ]]; then
    echo "$src"
    return
  fi
  if [[ -d "$src" ]]; then
    find "$src" -maxdepth 1 -type f -name "*.webm" | sort
    return
  fi
  echo "Error: input does not exist: $src" >&2
  exit 1
}

convert_one() {
  local in_file="$1"
  local in_dir in_base out_dir out_base ffmpeg_overwrite

  in_dir="$(dirname "$in_file")"
  in_base="$(basename "$in_file")"
  out_base="${in_base%.webm}"
  out_dir="${OUTPUT_DIR:-$in_dir}"
  mkdir -p "$out_dir"

  if [[ "$OVERWRITE" -eq 1 ]]; then
    ffmpeg_overwrite="-y"
  else
    ffmpeg_overwrite="-n"
  fi

  if [[ "$FORMAT" == "mp4" || "$FORMAT" == "both" ]]; then
    local out_mp4="$out_dir/${out_base}.mp4"
    echo "Converting to MP4: $in_file -> $out_mp4"
    ffmpeg $ffmpeg_overwrite -i "$in_file" \
      -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
      -c:a aac -b:a 192k \
      "$out_mp4"
  fi

  if [[ "$FORMAT" == "mov" || "$FORMAT" == "both" ]]; then
    local out_mov="$out_dir/${out_base}.mov"
    echo "Converting to MOV: $in_file -> $out_mov"
    ffmpeg $ffmpeg_overwrite -i "$in_file" \
      -c:v prores_ks -profile:v 3 \
      -c:a pcm_s16le \
      "$out_mov"
  fi
}

FILES=()
while IFS= read -r line; do
  [[ -n "$line" ]] && FILES+=("$line")
done < <(collect_inputs "$INPUT")

if [[ "${#FILES[@]}" -eq 0 ]]; then
  echo "No .webm files found at input: $INPUT" >&2
  exit 1
fi

for f in "${FILES[@]}"; do
  if [[ "${f##*.}" != "webm" ]]; then
    echo "Skipping non-webm file: $f"
    continue
  fi
  convert_one "$f"
done

echo "Done. Converted ${#FILES[@]} file(s)."
