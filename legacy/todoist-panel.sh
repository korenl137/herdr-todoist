#!/usr/bin/env bash
# Redraw `td today` every REFRESH seconds. Needs td (Node >= 24) on PATH or in
# TD_HOME, and TODOIST_API_TOKEN in ~/.config/todoist/.env.
set -euo pipefail

TD_HOME="${TD_HOME:-$HOME/.local/share/td}"
ENV_FILE="${TODOIST_ENV:-$HOME/.config/todoist/.env}"
REFRESH="${REFRESH:-60}"

PATH="$TD_HOME/node_modules/.bin:$PATH"
[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE"; read -r; exit 1; }
set -a; . "$ENV_FILE"; set +a

while true; do
  out="$(td today 2>&1 | grep -v '^  id:' || true)"
  printf '\033[H\033[2J%s\n\n\033[2mupdated %s · every %ss\033[0m\n' "$out" "$(date +%H:%M)" "$REFRESH"
  sleep "$REFRESH"
done
