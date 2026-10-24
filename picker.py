"""curses picker: browse favourites/projects as a tree, Tab adds tasks to a cart, Enter sends it to an agent pane."""
import curses, json, os, sys, unicodedata
import tdcart

WIDTH = 130  # cap total width: an overlay can be far wider than is readable
TREE_W = 38


def cells(ch):
    return 2 if unicodedata.east_asian_width(ch) in "WF" else (0 if unicodedata.combining(ch) else 1)


def width(text):
    return sum(cells(ch) for ch in text)


def clip(text, w):
    """Longest prefix of `text` that fits in `w` cells."""
    out, used = "", 0
    for ch in text:
        if used + cells(ch) > w:
            break
        out, used = out + ch, used + cells(ch)
    return out


def fit(text, w):
    """Pad or truncate to `w` terminal cells; a cut line ends in "…" (CJK and emoji are 2 cells wide)."""
    text = text.replace("\ufe0f", "")  # curses and the terminal disagree on the width of selector emoji
    if width(text) > w:
        text = clip(text, w - 1) + "…"
    return text + " " * (w - width(text))


def wrap(text, w, lines):
    """Break `text` into at most `lines` rows of `w` cells; the last row is cut with "…" if text remains."""
    out = []
    for _ in range(lines):
        part = clip(text, w)
        out, text = out + [part], text[len(part):]
    return [fit(r, w) for r in out[:-1]] + [fit(out[-1] + text, w)]


HELP = {
    "tree": "↑↓ move  →/Tab tasks  / search  0 cart  N+Enter jump  ^R refresh  ^Y copy  ^X clear  Esc quit",
    "tasks": "↑↓ move  ←/→ fold  Space add  Enter send  / search  0 cart  ^R refresh  ^Y copy  Tab tree  Esc back",
}


def plain_label(name):
    """Drop emoji and symbols: their cell width differs between curses and the terminal."""
    return "".join(c for c in name if unicodedata.category(c) != "So" and c != "\ufe0f").strip()


def build_rows(ws, cart_n):
    """Tree rows as (indent, label, count, node); node None = non-selectable header."""
    rows = [(0, "장바구니", cart_n, ("cart",)), (0, "즐겨찾기", None, None)]
    rows += [(1, plain_label(f["name"]), len(f["tasks"]), ("filter", f)) for f in ws["filters"]]
    rows.append((0, "프로젝트", None, None))
    own = {}
    for t in ws["tasks"]:
        own[t["projectId"]] = own.get(t["projectId"], 0) + 1

    def walk(parent, depth):
        for p in ws["projects"]:
            if p["parentId"] == parent:
                rows.append((depth, plain_label(p["name"]), own.get(p["id"], 0), ("project", p)))
                walk(p["id"], depth + 1)
    walk(None, 1)
    return rows


def subtree_ids(projects, pid):
    ids = {pid}
    for p in projects:
        if p["parentId"] in ids:
            ids |= subtree_ids(projects, p["id"])
    return ids


def node_tasks(ws, node):
    kind = node[0]
    if kind == "cart":
        return tdcart.load_cart()
    if kind == "filter":
        return node[1]["tasks"]
    ids = subtree_ids(ws["projects"], node[1]["id"])
    return [t for t in ws["tasks"] if t["projectId"] in ids]


def review(scr, items, question):
    """Show the cart and wait for Enter (True) or Esc (False)."""
    scr.erase()
    scr.addstr(0, 0, fit(f"{question}  Enter=yes  Esc=cancel", min(curses.COLS - 1, WIDTH)).rstrip(), curses.A_BOLD)
    for n, i in enumerate(items[: curses.LINES - 3]):
        scr.addstr(2 + n, 0, fit(f"- {i['title']} ({i['id']})", min(curses.COLS - 1, WIDTH)))
    while True:
        k = scr.get_wch()
        if k in ("\n", curses.KEY_ENTER):
            return True
        if k == "\x1b":
            return False


def source_pane():
    """Pane the plugin action was invoked from (the focused pane), or None."""
    try:
        return json.loads(os.environ["HERDR_PLUGIN_CONTEXT_JSON"])["focused_pane_id"]
    except (KeyError, ValueError):
        return os.environ.get("TODOIST_SRC_PANE") or None


def choose_agent(scr, agents):
    src = source_pane()
    sel = next((n for n, a in enumerate(agents) if a["pane_id"] == src), 0)  # default: the pane that opened the picker
    while True:
        scr.erase()
        scr.addstr(0, 0, "Send to which agent? (Enter=send, Esc=back)")
        for n, a in enumerate(agents):
            line = f"{a['pane_id']:8} {a['agent']:7} {a['agent_status']:8} {a.get('terminal_title_stripped', '')}"
            scr.addstr(2 + n, 0, line[: curses.COLS - 1], curses.A_REVERSE if n == sel else 0)
        for n, i in enumerate(tdcart.load_cart()[: max(curses.LINES - len(agents) - 6, 0)]):
            scr.addstr(len(agents) + 4 + n, 0, fit(f"- {i['title']}", min(curses.COLS - 1, WIDTH)))
        k = scr.get_wch()
        if k == "\x1b":
            return None
        if k in ("\n", curses.KEY_ENTER):
            return agents[sel]
        sel = (sel + (k == curses.KEY_DOWN) - (k == curses.KEY_UP)) % len(agents)


def window(sel, n, h):
    """First visible index so that `sel` stays on screen in a list of n rows, h tall."""
    return max(0, min(sel - h + 1, n - h)) if sel >= h else 0


def main(scr):
    curses.curs_set(0)
    curses.set_escdelay(25)
    colors = {}
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for n, (tag, fg) in enumerate((("P1", curses.COLOR_RED), ("P2", curses.COLOR_YELLOW)), 1):
            curses.init_pair(n, fg, -1)
            colors[tag] = curses.color_pair(n) | curses.A_BOLD
    scr.addstr(0, 0, "loading Todoist…"); scr.refresh()
    ws, msg = tdcart.load_workspace(), ""
    cart_ids = {i["id"] for i in tdcart.load_cart()}
    focus, text, filtering, tsel, sel, jump, collapsed = "tree", "", False, 0, 0, "", set()
    while True:
        h, W = curses.LINES - 2, min(curses.COLS - 1, WIDTH)
        rows = build_rows(ws, len(cart_ids))
        picks = [n for n, r in enumerate(rows) if r[3]]
        tsel = min(tsel, len(picks) - 1)
        node = rows[picks[tsel]][3]
        searching = bool(text or filtering)  # "/" searches every open task, not just the selected node
        found = [t for t in (ws["tasks"] if searching else node_tasks(ws, node)) if tdcart.matches(t, text)]
        shown = tdcart.arrange(found, collapsed, nested=not searching)
        sel = min(sel, max(len(shown) - 1, 0))
        scr.erase()
        scr.addstr(0, 0, fit(f"[cart {len(cart_ids)}]  {HELP[focus]}", W).rstrip())
        top = window(picks[tsel], len(rows), h)
        for n, (ind, label, count, nd) in enumerate(rows[top : top + h]):
            on = nd and picks[tsel] == top + n
            attr = (curses.A_REVERSE if focus == "tree" else curses.A_BOLD) if on else (0 if nd else curses.A_DIM)
            num = picks.index(top + n) if nd else None
            scr.addstr(1 + n, 0, fit(f"{num if num is not None else '':>2} {'  ' * ind}{label}", TREE_W - 5), attr)
            # count at an absolute column: emoji widths differ between curses and the terminal and would shift it
            scr.addstr(1 + n, TREE_W - 5, (f"{count}" if count else "").rjust(5), attr)
        x0, rw = TREE_W + 2, W - TREE_W - 2
        title = f"🔍 {text}{'_' if filtering else ''}  ({len(found)} of all tasks)" if searching else rows[picks[tsel]][1]
        scr.addstr(1, x0, fit(title, rw), curses.A_UNDERLINE)
        D = 5  # detail strip: 2 title lines, meta line, 2 description lines
        list_h = h - 1 - D
        top = window(sel, len(shown), list_h)
        due_w = 5
        side_w = 18 if searching or node[0] in ("filter", "cart") else 0  # project column only where tasks of many projects mix
        lw = rw - due_w - side_w - 2
        for n, (t, depth, kids) in enumerate(shown[top : top + list_h]):
            attr = curses.A_REVERSE if focus == "tasks" and top + n == sel else 0
            y, tag = 2 + n, tdcart.priority_tag(t.get("priority", 1))
            fold = ("+ " if t["id"] in collapsed else "- ") if kids else ""
            scr.addstr(y, x0, " " * rw, attr)
            scr.addstr(y, x0, "✓" if t["id"] in cart_ids else " ", attr)
            scr.addstr(y, x0 + 2, tag or "  ", (attr | colors.get(tag, 0)))
            scr.addstr(y, x0 + 5, fit("  " * depth + fold + t["title"], lw - 5), attr)
            if side_w:
                scr.addstr(y, x0 + 1 + lw, fit(t["project"], side_w), attr | curses.A_DIM)
            scr.addstr(y, x0 + 1 + lw + side_w, t["due"][5:10].rjust(due_w), attr | curses.A_DIM)
        if shown:
            t = shown[sel][0]
            for n, line in enumerate(wrap(t["title"], rw, 2)):
                scr.addstr(2 + list_h + n, x0, line, curses.A_BOLD)
            scr.addstr(2 + list_h + 2, x0, fit(" · ".join(x for x in (t["project"], t["due"], t["id"]) if x), rw), curses.A_DIM)
            for n, line in enumerate(wrap(tdcart.plain(t.get("desc", "")), rw, 2)):
                scr.addstr(2 + list_h + 3 + n, x0, line.rstrip().ljust(rw), curses.A_DIM)
        for y in range(1, h + 1):
            scr.addstr(y, TREE_W, "│", curses.A_DIM)
        scr.addstr(curses.LINES - 1, 0, (f"jump: {jump}_  (Enter=go)" if jump else msg)[: W])
        msg = ""
        k = scr.get_wch()
        if filtering:
            if k == "\x1b":
                text, filtering = "", False
            elif k in ("\n", curses.KEY_ENTER, curses.KEY_DOWN):
                filtering = False  # Down leaves the search box with the first result selected
            elif k in ("\x7f", curses.KEY_BACKSPACE):
                text = text[:-1]
            elif k == "\x15":
                text = ""
            elif isinstance(k, str) and k.isprintable():
                text, sel = text + k, 0
        elif k == "\x1b" and jump:
            jump = ""
        elif isinstance(k, str) and k.isdigit() or k in ("\n", curses.KEY_ENTER) and jump:
            # numbers label the tree rows; "0" is the cart. Commit once the number is unambiguous or on Enter.
            jump = jump + k if k.isdigit() else jump
            if int(jump) >= len(picks):
                jump = k if k.isdigit() else ""
            if k not in "0123456789" or jump == "0" or int(jump) * 10 >= len(picks):
                tsel, sel, text, jump = int(jump), 0, "", ""
        elif k == "\x1b":
            if focus == "tree":
                return
            focus, text = "tree", ""
        elif k == "\x12":
            try:
                ws = tdcart.load_workspace()
                cart_ids = {i["id"] for i in tdcart.load_cart()}
                msg = "refreshed"
            except (RuntimeError, OSError) as e:
                msg = f"refresh failed: {e}"
        elif k == "\x18":
            tdcart.save_cart([])
            cart_ids = set()
        elif k == "\x19":
            items = tdcart.load_cart()
            if not items:
                msg = "cart empty"
            elif review(scr, items, f"Copy {len(items)} tasks to the clipboard?"):
                tdcart.osc52(tdcart.format_lines(items))
                msg = "copied (OSC 52)"
        elif focus == "tree":
            if k in (curses.KEY_DOWN, curses.KEY_UP):
                tsel = min(max(tsel + (k == curses.KEY_DOWN) - (k == curses.KEY_UP), 0), len(picks) - 1)
                sel, text = 0, ""
            elif k in (curses.KEY_RIGHT, "\t", "\n", curses.KEY_ENTER):
                focus = "tasks"
            elif k == "/":
                focus, filtering = "tasks", True
        else:
            cur = shown[sel] if shown else None
            if k in (curses.KEY_DOWN, curses.KEY_UP):
                sel = min(max(sel + (k == curses.KEY_DOWN) - (k == curses.KEY_UP), 0), max(len(shown) - 1, 0))
            elif k == curses.KEY_RIGHT and cur and cur[2] and cur[0]["id"] in collapsed:
                collapsed.discard(cur[0]["id"])
            elif k == curses.KEY_LEFT and cur and cur[2] and cur[0]["id"] not in collapsed and not searching:
                collapsed.add(cur[0]["id"])
            elif k in (curses.KEY_LEFT, "\t"):
                focus = "tree"
            elif k == "/":
                filtering = True
            elif k == " " and cur:
                tdcart.toggle(cur[0])
                cart_ids = {i["id"] for i in tdcart.load_cart()}
            elif k in ("\n", curses.KEY_ENTER):
                agents = tdcart.agent_panes()
                if not cart_ids or not agents:
                    msg = "cart empty" if not cart_ids else "no agent panes"
                    continue
                a = choose_agent(scr, agents)
                if a:
                    tdcart.send_to_pane(a["pane_id"], tdcart.format_oneline(tdcart.load_cart()))
                    tdcart.archive_cart(a["pane_id"])
                    cart_ids = set()
                    msg = f"typed into {a['pane_id']} (not submitted); cart archived"


if __name__ == "__main__":
    curses.wrapper(main)
