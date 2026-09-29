#!/bin/sh
set -eu

skill_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    echo "Bundled FFmpeg requires macOS arm64; this bundle does not support this platform." >&2
    exit 1
fi
export FFMPEG_PATH="$skill_root/bin/macos-arm64/ffmpeg"
export FFPROBE_PATH="$skill_root/bin/macos-arm64/ffprobe"
if [ ! -x "$FFMPEG_PATH" ] || [ ! -x "$FFPROBE_PATH" ]; then
    echo "Bundled FFmpeg/FFprobe is missing or not executable." >&2
    exit 1
fi
if [ "$#" -eq 0 ]; then
    printf 'FFMPEG_PATH=%s\nFFPROBE_PATH=%s\n' "$FFMPEG_PATH" "$FFPROBE_PATH"
    exit 0
fi
case "$1" in
    ffmpeg) shift; exec "$FFMPEG_PATH" "$@" ;;
    ffprobe) shift; exec "$FFPROBE_PATH" "$@" ;;
    *) exec "$@" ;;
esac
