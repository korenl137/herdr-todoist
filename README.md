# herdr-todoist

Read-only Todoist "today" panel for herdr. Token: `TODOIST_API_TOKEN` in `~/.config/todoist/.env`. Needs `td` (Node >= 24; default `~/.local/share/td`).

```sh
herdr plugin link ~/Projects/herdr-todoist
herdr plugin action invoke herdr-todoist.open
```

## Picker

`herdr plugin action invoke herdr-todoist.picker` (bound to `prefix+t` / `prefix+ㅓ`): tree of favourite filters and projects on the left, tasks on the right. Space adds a task to the cart, Enter types the cart into a chosen agent pane (never submits), Ctrl+Y copies, Ctrl+X clears. Popup size: `width`/`height` in `herdr-plugin.toml`.
