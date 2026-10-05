#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# Ensure DISPLAY is set if in graphical session
if [ -z "$DISPLAY" ] && [ -n "$WAYLAND_DISPLAY" ]; then
    export GDK_BACKEND=x11
fi

export DISPLAY="${DISPLAY:-:1}"

exec python3 "$DIR/widget.py" "$@"
