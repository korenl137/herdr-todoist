#!/usr/bin/env bash
# Redraw inbox, today and upcoming (td) every REFRESH seconds. Needs td (Node >= 24) on PATH or in
# TD_HOME, and TODOIST_API_TOKEN in ~/.config/todoist/.env.
set -euo pipefail

TD_HOME="${TD_HOME:-$HOME/.local/share/td}"
ENV_FILE="${TODOIST_ENV:-$HOME/.config/todoist/.env}"
REFRESH="${REFRESH:-60}"

PATH="$TD_HOME/node_modules/.bin:$PATH"
[ -r "$ENV_FILE" ] || { echo "missing $ENV_FILE"; read -r; exit 1; }
set -a; . "$ENV_FILE"; set +a

while true; do
  out=""
  for cmd in inbox today upcoming; do
    body="$(td "$cmd" 2>&1 | grep -v '^  id:' || true)"
    # upcoming repeats the Overdue and Today groups already shown above
    [ "$cmd" = upcoming ] && body="$(awk '/^[^ ]/{skip=($0 ~ /^(Overdue|Today) \(/)} !skip' <<<"$body")"
    out+="$(printf '\033[1m== %s ==\033[0m\n%s' "$cmd" "$body")"$'\n\n'
  done
  printf '\033[H\033[2J%s\033[2mupdated %s · every %ss\033[0m\n' "$out" "$(date +%H:%M)" "$REFRESH"
  sleep "$REFRESH"
done
