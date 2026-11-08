"""Data, cart and sink layers for the Todoist picker. Stdlib only; no UI here."""
import json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

TD_HOME = Path(os.environ.get("TD_HOME", Path.home() / ".local/share/td"))
ENV_FILE = Path(os.environ.get("TODOIST_ENV", Path.home() / ".config/todoist/.env"))
CART = Path(os.environ.get("TODOIST_CART", Path.home() / ".config/herdr/plugins/config/herdr-todoist/cart.json"))
HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")


def _env():
    env = dict(os.environ, PATH=f"{TD_HOME}/node_modules/.bin:{os.environ['PATH']}", NO_COLOR="1")
    for line in ENV_FILE.read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == "TODOIST_API_TOKEN":
            env[k.strip()] = v.strip().strip("'\"")
    return env


def _td(*args):
    p = subprocess.run(["td", *args, "--json"], env=_env(), capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "td failed")
    return json.loads(p.stdout)["results"]


def _norm(t, projects):
    return {"id": t["id"], "title": t["content"], "project": projects.get(t["projectId"], ""),
            "projectId": t["projectId"], "due": (t.get("due") or {}).get("date", ""), "url": t["url"],
            "labels": t.get("labels") or [], "desc": t.get("description") or "",
            "priority": t.get("priority", 1), "parentId": t.get("parentId")}


def load_tasks(query="today | overdue"):
    projects = {p["id"]: p["name"] for p in _td("project", "list")}
    return [_norm(t, projects) for t in _td("task", "list", "--filter", query)]


BUILTIN_FILTERS = [("Inbox", "#Inbox"), ("Today", "overdue | today"), ("Next 7 days", "next 7 days")]


def with_builtin_filters(favourites):
    """Inbox, Today and Next 7 days lead the Favorites; one whose query a favourite already has is skipped."""
    have = {f["query"] for f in favourites}
    return [{"name": n, "query": q} for n, q in BUILTIN_FILTERS if q not in have] + favourites


def load_workspace():
    """Everything the tree needs: projects, favourite filters with their tasks, all open tasks."""
    from concurrent.futures import ThreadPoolExecutor
    projects = _td("project", "list")
    names = {p["id"]: p["name"] for p in projects}
    filters = with_builtin_filters([f for f in _td("filter", "list") if f.get("isFavorite")])
    with ThreadPoolExecutor() as ex:
        jobs = [ex.submit(_td, "task", "list", "--all")] + [ex.submit(_td, "task", "list", "--filter", f["query"]) for f in filters]
        results = [j.result() for j in jobs]
    for f, tasks in zip(filters, results[1:]):
        f["tasks"] = [_norm(t, names) for t in tasks]
    return {"projects": projects, "filters": filters, "tasks": [_norm(t, names) for t in results[0]]}


def load_cart():
    try:
        return json.loads(CART.read_text())
    except FileNotFoundError:
        return []


def save_cart(items):
    CART.parent.mkdir(parents=True, exist_ok=True)
    tmp = CART.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    tmp.replace(CART)


HISTORY_MAX = 100  # oldest sent carts are dropped past this


def _write_history(entries):
    """Rewrite history.jsonl from `entries`, oldest first."""
    path = CART.parent / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
    tmp.replace(path)


def archive_cart(pane_id):
    """Append the cart to history.jsonl (one line per send, newest HISTORY_MAX kept), then empty it."""
    items = load_cart()
    if items:
        entry = {"sent": datetime.now().isoformat(timespec="seconds"), "pane": pane_id, "items": items}
        _write_history((load_history()[::-1] + [entry])[-HISTORY_MAX:])
    save_cart([])


def delete_history(entry):
    """Remove one sent cart from the history."""
    _write_history([e for e in load_history()[::-1] if e != entry])


def load_history():
    """Sent carts, newest first; unreadable lines are skipped."""
    try:
        lines = (CART.parent / "history.jsonl").read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out[::-1]


def restore(entry):
    """Put a sent cart's tasks back into the cart (tasks already in it stay once)."""
    items = load_cart()
    have = {i["id"] for i in items}
    save_cart(items + [i for i in entry["items"] if i["id"] not in have])


def toggle(task):
    """Add the task to the cart or remove it; returns True when it is now in."""
    items = load_cart()
    kept = [i for i in items if i["id"] != task["id"]]
    slim = {k: task[k] for k in ("id", "title", "project", "projectId", "due", "url") if k in task}  # no description in the cart file
    save_cart(kept if len(kept) != len(items) else items + [slim])
    return len(kept) == len(items)


def matches(task, query):
    """True when every space-separated word of `query` occurs in the task's title, project, labels, description or id."""
    hay = " ".join([task["title"], task["project"], task["id"], task.get("desc", ""), *task.get("labels", [])]).lower()
    return all(w in hay for w in query.lower().split())


def arrange(tasks, collapsed=(), nested=True):
    """Order tasks so subtasks follow their parent: [(task, depth, subtask_count)]. A collapsed parent hides its subtasks."""
    if not nested:
        return [(t, 0, 0) for t in tasks]
    ids = {t["id"] for t in tasks}
    kids = {}
    for t in tasks:
        if t.get("parentId") in ids:
            kids.setdefault(t["parentId"], []).append(t)
    out = []

    def walk(t, depth):
        out.append((t, depth, len(kids.get(t["id"], []))))
        if t["id"] not in collapsed:
            for c in kids.get(t["id"], []):
                walk(c, depth + 1)
    for t in tasks:
        if t.get("parentId") not in ids:
            walk(t, 0)
    return out


def plain(markdown):
    """Description as one plain line: markdown marks dropped, whitespace collapsed."""
    return " ".join(re.sub(r"[#>*`]", "", markdown).split())


def priority_tag(priority):
    """Todoist stores p1 as 4 and p4 as 1; only p1 and p2 get a tag."""
    return {4: "P1", 3: "P2"}.get(priority, "")


def format_lines(items):
    return "\n".join(f"- {i['title']} ({i['id']}) {i['url']}" for i in items)


def format_oneline(items):
    """One line: send-text treats a newline as Enter, which would submit the first line."""
    return "Todoist tasks: " + " | ".join(f"{i['title']} ({i['id']}) {i['url']}" for i in items)


def agent_panes():
    p = subprocess.run([HERDR, "agent", "list"], capture_output=True, text=True)
    return json.loads(p.stdout)["result"]["agents"] if p.returncode == 0 else []


def send_to_pane(pane_id, text):
    """Type text into a pane. Never presses Enter: the person submits."""
    p = subprocess.run([HERDR, "pane", "send-text", pane_id, text], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())


def osc52(text):
    import base64
    sys.stdout.write("\033]52;c;" + base64.b64encode(text.encode()).decode() + "\a")
    sys.stdout.flush()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "list":
        for t in load_tasks(*sys.argv[2:3]):
            print(t["id"], t["title"], t["project"], t["due"])
    elif cmd == "toggle":
        print(toggle({"id": sys.argv[2], "title": sys.argv[3], "url": f"https://app.todoist.com/app/task/{sys.argv[2]}"}))
    elif cmd == "show":
        print(format_lines(load_cart()))
    elif cmd == "clear":
        save_cart([])
