# herdr-todoist

Todoist plugin for herdr: a read-only panel (inbox, today, next 7 days) and a picker that sends tasks to an agent pane.

Needs the [`td`](https://github.com/Doist/todoist-cli) CLI (`@doist/todoist-cli`) (Node >= 24; default `~/.local/share/td`, override with `TD_HOME`) and a token: `TODOIST_API_TOKEN=...` in `~/.config/todoist/.env` (override with `TODOIST_ENV`). The token is read by the plugin processes only; nothing is exported to the herdr session. The plugin never writes to Todoist.

```sh
herdr plugin link /path/to/herdr-todoist      # the repository root; its herdr-plugin.toml points here
herdr plugin action invoke herdr-todoist.open     # inbox + today + upcoming panel, refreshed every 60 s
herdr plugin action invoke herdr-todoist.picker   # picker popup
```

Bind the picker to a key in your herdr config by pointing a keybinding at the command `herdr-todoist.picker`.

## Picker

Favourite filters and projects as a tree on the left, tasks on the right.

| Key | Action |
| --- | --- |
| `↑↓`, `←/→`, `Tab` | move, fold subtasks, switch between tree and tasks |
| `/` | search all open tasks; `↓` leaves the search box onto the first result |
| `Space` | add or remove the task in the cart |
| `h` | sent carts: Enter puts a cart's tasks back, `d` deletes it (Korean layout keys ㅗ ㅍ ㅇ work too) |
| `v` | full task view (title, due with time, labels, url, whole description) |
| `Enter` | type the cart into an agent pane (never submits). The pane that opened the picker is preselected |
| `0` / `N`+`Enter` | jump to the cart / to tree row N |
| `^Y` / `^X` / `^R` | copy the cart (OSC 52) / clear it / refresh from Todoist |

After a send the cart is emptied and appended to `history.jsonl` next to `cart.json` in the plugin config directory (`~/.config/herdr/plugins/config/herdr-todoist/`). `^X` clears without a record. The newest 100 sends are kept.

herdr is found through `HERDR_BIN_PATH` (set by herdr), else `herdr` on `PATH`. Popup size: `width`/`height` in the root `herdr-plugin.toml`. Tests: `python3 legacy/test_tdcart.py`.

## License

MIT
