# herdr-todoist

Todoist task picker for [herdr-app](https://herdr.dev). A Rust binary (`herdr-todoist`) does the work;
a JavaScript mod (`mods/todoist`) draws the dialog and calls it.

Favourite filters and projects as a tree on the left, tasks on the right. Pick tasks into a cart,
copy the cart as one line, paste it into an agent. The plugin never writes to Todoist.

## Needs

- the [`td`](https://github.com/Doist/todoist-cli) CLI (`@doist/todoist-cli`, Node >= 24); default `~/.local/share/td`, override with `TD_HOME`
- `TODOIST_API_TOKEN=...` in `~/.config/todoist/.env` (override with `TODOIST_ENV`); only the binary reads it and passes it to `td`
- `wl-copy` (package `wl-clipboard`) for the clipboard

## Install

```sh
cargo install --path .                          # herdr-todoist into ~/.cargo/bin
herdr-mod-manager install . --accept            # or copy mods/todoist to ~/.config/herdr-app/mods/
```

Bind a key in `~/.config/herdr-app/keys.json`: `"ctrl-alt-o": "mod.open:todoist"`.

## Keys

| Key | Action |
| --- | --- |
| `↑↓`, `→`/`Tab`, `←` | move, enter the task list, fold subtasks, back to the tree |
| `/` | search all open tasks (title, project, labels, description, id) |
| `Space` or click | add or remove the task in the cart |
| `v` | full task view |
| `Enter` | copy the cart as one line, record it in history, empty the cart |
| `h` | sent carts: `Enter` puts one back, `d` deletes it |
| `Ctrl+R` / `Ctrl+X` | refresh from Todoist / clear the cart without a record |

The old picker typed the cart into an agent pane without pressing Enter. herdr-app has no way to do
that (`hc send` always submits, `hc keys` cannot type Korean), so the cart goes to the clipboard.

Cart and history live in `~/.config/herdr-todoist/` (`cart.json`, `history.jsonl`, newest 100 sends).
The first run copies the old plugin's files from `~/.config/herdr/plugins/config/herdr-todoist/`.

## CLI

`herdr-todoist workspace | cart | toggle <json> | clear | history | restore <sent> | delete-history <sent> | archive <pane> | text [--lines]`
prints JSON. `cargo test` covers the cart, history and formatting.

`legacy/` holds the old plugin (Python curses picker) for the previous `herdr` server.

## License

MIT
