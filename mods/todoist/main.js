// Todoist picker. Left: Cart, favourite filters, projects. Right: tasks.
// Space adds a task to the cart, Enter copies the cart as one line (paste it into an agent yourself).
// All data and the cart live in the `herdr-todoist` binary (Rust); this file only draws and calls it.
import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input } from "gpui-base";
import { exec, focused, notify, props, closeOverlay, theme } from "herdr";

const BIN = "herdr-todoist";
const W = 1000, H = 620, TREE_W = 250;

// The binary prints JSON for success and for failure ({"error": ...}).
async function call(args) {
  try {
    const r = await exec(BIN, args);
    try { return JSON.parse(r.stdout); } catch { return { error: (r.stderr || r.stdout || "no output").trim() }; }
  } catch (e) {
    return { error: `cannot run ${BIN}: ${e}. Install: cargo install --path ~/Projects/herdr-todoist` };
  }
}

// wl-copy keeps its pipes open while it owns the clipboard; the redirects let exec return at once.
async function copy(text) {
  const r = await exec("sh", ["-c", 'wl-copy -- "$1" >/dev/null 2>&1 </dev/null', "_", text]);
  if (r.code !== 0) throw new Error("wl-copy failed (is wl-clipboard installed?)");
}

const words = (q) => q.toLowerCase().split(/\s+/).filter(Boolean);
const matches = (t, q) => {
  const hay = [t.title, t.project, t.id, t.desc ?? "", ...(t.labels ?? [])].join(" ").toLowerCase();
  return words(q).every((w) => hay.includes(w));
};
const plain = (md) => (md ?? "").replace(/[#>*`]/g, "").split(/\s+/).filter(Boolean).join(" ");
const tag = (p) => (p === 4 ? "P1" : p === 3 ? "P2" : "");

// Subtasks follow their parent; a collapsed parent hides them. -> [{t, depth, kids}]
function arrange(tasks, collapsed, nested) {
  if (!nested) return tasks.map((t) => ({ t, depth: 0, kids: 0 }));
  const ids = new Set(tasks.map((t) => t.id));
  const kids = new Map();
  for (const t of tasks) if (t.parentId && ids.has(t.parentId)) (kids.get(t.parentId) ?? kids.set(t.parentId, []).get(t.parentId)).push(t);
  const out = [];
  const walk = (t, depth) => {
    out.push({ t, depth, kids: (kids.get(t.id) ?? []).length });
    if (!collapsed.has(t.id)) for (const c of kids.get(t.id) ?? []) walk(c, depth + 1);
  };
  for (const t of tasks) if (!t.parentId || !ids.has(t.parentId)) walk(t, 0);
  return out;
}

export default class Todoist extends View {
  init(_props, cx) {
    this.ws = null;            // {projects, filters, tasks}
    this.cart = [];
    this.history = [];
    this.mode = "tasks";       // tasks | history | detail
    this.focus = "tree";       // tree | tasks
    this.tsel = 1;             // selected tree row (index into this.rows())
    this.sel = 0;              // selected task row
    this.hsel = 0;
    this.collapsed = new Set();
    this.query = "";
    this.msg = "loading…";
    this.busy = false;
    this.input = InputState.new({ value: "" });
    this.input.on("change", (_e, cx) => { this.query = this.input.value(); this.sel = 0; cx.notify(); });
    this.input.on("submit", (_e, cx) => { this.handle.focus(); this.focus = "tasks"; cx.notify(); });
    this.handle = cx.focus_handle();
    this.handle.focus();
    cx.timer.after(300, () => this.handle.focus());
    this.reload(cx, true);
  }

  // One binary call at a time; `done` runs with the parsed result.
  act(cx, args, done, then) {
    if (this.busy) return;
    this.busy = true; cx.notify();
    cx.spawn(async (cx) => {
      const r = await call(args);
      this.busy = false;
      if (r.error) this.msg = r.error; else done?.(r);
      cx.notify();
      if (!r.error && then) then(cx);
    });
  }

  reload(cx, first) {
    cx.spawn(async (cx) => {
      const [ws, cart] = await Promise.all([call(["workspace"]), call(["cart"])]);
      if (ws.error) this.msg = ws.error;
      else { this.ws = ws; this.msg = first ? "" : "refreshed"; }
      if (!cart.error) this.cart = cart;
      cx.notify();
    });
  }

  refreshCart(cx) { cx.spawn(async (cx) => { const c = await call(["cart"]); if (!c.error) this.cart = c; cx.notify(); }); }

  // Tree rows: {indent, label, count, node}; node null = header
  rows() {
    const rows = [{ indent: 0, label: "Cart", count: this.cart.length, node: { kind: "cart" } }, { indent: 0, label: "Favorites" }];
    if (!this.ws) return rows;
    for (const f of this.ws.filters) rows.push({ indent: 1, label: f.name, count: f.tasks.length, node: { kind: "filter", f } });
    rows.push({ indent: 0, label: "Projects" });
    const own = new Map();
    for (const t of this.ws.tasks) own.set(t.projectId, (own.get(t.projectId) ?? 0) + 1);
    const walk = (parent, depth) => {
      for (const p of this.ws.projects) if ((p.parentId ?? null) === parent) {
        rows.push({ indent: depth, label: p.name, count: own.get(p.id) ?? 0, node: { kind: "project", p } });
        walk(p.id, depth + 1);
      }
    };
    walk(null, 1);
    return rows;
  }

  subtree(pid) {
    const ids = new Set([pid]);
    let grew = true;
    while (grew) { grew = false; for (const p of this.ws.projects) if (p.parentId && ids.has(p.parentId) && !ids.has(p.id)) { ids.add(p.id); grew = true; } }
    return ids;
  }


  current() {
    const rows = this.rows();
    const row = rows[Math.min(this.tsel, rows.length - 1)];
    const node = row?.node ?? rows[0].node;
    const searching = this.query.trim() !== "";
    let base = [];
    if (this.ws) {
      if (searching) base = this.ws.tasks;
      else if (node.kind === "cart") base = this.cart;
      else if (node.kind === "filter") base = node.f.tasks;
      else { const ids = this.subtree(node.p.id); base = this.ws.tasks.filter((t) => ids.has(t.projectId)); }
    }
    const found = base.filter((t) => matches(t, this.query));
    return { node, searching, title: searching ? `Search: ${this.query}  (${found.length})` : (row?.label ?? ""), shown: arrange(found, this.collapsed, !searching) };
  }

  moveTree(d) {
    const rows = this.rows();
    let i = this.tsel;
    do { i += d; } while (i >= 0 && i < rows.length && !rows[i].node);
    if (i >= 0 && i < rows.length) { this.tsel = i; this.sel = 0; this.input.set_value(""); this.query = ""; }
  }

  toggleCart(cx, t) {
    this.act(cx, ["toggle", JSON.stringify(t)], null, (cx) => this.refreshCart(cx));
  }

  // Copies the cart as one line, records it as sent, empties it.
  send(cx) {
    if (!this.cart.length) { this.msg = "cart is empty"; return cx.notify(); }
    const target = focused()?.agent ?? focused()?.terminal ?? "clipboard";
    cx.spawn(async (cx) => {
      const r = await call(["text"]);
      if (r.error) { this.msg = r.error; return cx.notify(); }
      try { await copy(r.text); } catch (e) { this.msg = String(e.message ?? e); return cx.notify(); }
      const a = await call(["archive", target]);
      if (a.error) this.msg = a.error;
      else { this.msg = `Copied ${r.count} tasks. Paste into your agent (Ctrl+Shift+V); restore from History (h).`; notify({ title: "Todoist", body: `Copied ${r.count} tasks`, timeout: 2500 }); }
      this.refreshCart(cx);
      cx.notify();
    });
  }

  openHistory(cx) {
    this.act(cx, ["history"], (r) => { this.history = r; this.hsel = 0; this.mode = "history"; if (!r.length) { this.mode = "tasks"; this.msg = "no history yet"; } });
  }

  key(e, cx) {
    const k = e.key;
    const done = () => { cx.stop_propagation(); cx.notify(); };
    if (this.mode === "detail") { if (k === "escape" || k === "v" || k === "enter") { this.mode = "tasks"; } else return; return done(); }
    if (this.mode === "history") {
      const n = this.history.length;
      if (k === "escape") this.mode = "tasks";
      else if (k === "down") this.hsel = Math.min(this.hsel + 1, n - 1);
      else if (k === "up") this.hsel = Math.max(this.hsel - 1, 0);
      else if (k === "enter" && n) { const s = this.history[this.hsel].sent; this.mode = "tasks"; this.act(cx, ["restore", s], (r) => { this.msg = `Put ${r.restored} tasks back in the cart`; }, (cx) => this.refreshCart(cx)); }
      else if (k === "d" && n) { const s = this.history[this.hsel].sent; this.act(cx, ["delete-history", s], null, (cx) => this.act(cx, ["history"], (r) => { this.history = r; this.hsel = Math.min(this.hsel, Math.max(r.length - 1, 0)); if (!r.length) this.mode = "tasks"; })); }
      else return;
      return done();
    }
    // tasks mode
    const cur = this.current();
    const row = cur.shown[Math.min(this.sel, cur.shown.length - 1)];
    if (k === "escape") { if (this.query) { this.input.set_value(""); this.query = ""; } else if (this.focus === "tasks") this.focus = "tree"; else return closeOverlay(props().overlay); }
    else if (k === "/") { this.focus = "tasks"; this.input.focus(); }
    else if (k === "r" && e.ctrl) this.reload(cx, false);
    else if (k === "x" && e.ctrl) this.act(cx, ["clear"], null, (cx) => this.refreshCart(cx));
    else if (this.focus === "tree") {
      if (k === "down") this.moveTree(1);
      else if (k === "up") this.moveTree(-1);
      else if (k === "right" || k === "tab" || k === "enter") this.focus = "tasks";
      else if (k === "h") this.openHistory(cx);
      else return;
    } else {
      if (k === "down") this.sel = Math.min(this.sel + 1, cur.shown.length - 1);
      else if (k === "up") this.sel = Math.max(this.sel - 1, 0);
      else if (k === "right" && row?.kids) this.collapsed.delete(row.t.id);
      else if (k === "left" && row?.kids && !this.collapsed.has(row.t.id) && !cur.searching) this.collapsed.add(row.t.id);
      else if (k === "left" || k === "tab") this.focus = "tree";
      else if (k === " " && row) this.toggleCart(cx, row.t);
      else if (k === "enter") this.send(cx);
      else if (k === "v" && row) this.mode = "detail";
      else if (k === "h") this.openHistory(cx);
      else return;
    }
    done();
  }

  render(cx) {
    const t = theme();
    const root = v_flex().id("todoist").track_focus(this.handle).on_key_down((e, cx) => this.key(e, cx))
      .w(W).h(H).min_h(0).p(14).gap(8).bg(t.popover).text_size(13).text_color(t.foreground);
    const header = h_flex().items_center().gap(10)
      .child(div().text_size(15).font_semibold().child("Todoist"))
      .child(div().text_size(11).text_color(t.dim).child(`cart ${this.cart.length}${this.busy ? " · working…" : ""}`))
      .child(div().flex_1().text_size(11).text_color(t.dim).truncate().child("↑↓ move · →/Tab tasks · Space cart · Enter copy · / search · v detail · h history · ^R refresh · ^X clear cart · Esc"));
    const status = div().h(16).text_size(11.5).text_color(t.muted).truncate().child(this.msg);

    if (this.mode === "history") {
      return root.child(header).child(div().text_color(t.muted).child("Sent carts: Enter puts a cart back, d deletes it, Esc returns"))
        .child(v_flex().flex_1().min_h(0).overflow_y_scrollbar().gap(2).children(this.history.map((e, i) =>
          h_flex().id(`h-${e.sent}`).gap(10).px(8).py(5).rounded(7).bg(i === this.hsel ? t.selected : t.popover).hover((s) => s.bg(t.hover))
            .on_click(() => { this.hsel = i; cx.notify(); })
            .child(div().w(150).text_color(t.dim).child(e.sent.replace("T", " ")))
            .child(div().w(70).text_color(t.dim).truncate().child(e.pane))
            .child(div().flex_1().truncate().child(`${e.items.length} tasks: ${e.items.map((x) => x.title).join(", ")}`)))))
        .child(status);
    }

    const cur = this.current();
    const sel = Math.min(this.sel, Math.max(cur.shown.length - 1, 0));
    const picked = cur.shown[sel]?.t;

    if (this.mode === "detail" && picked) {
      const full = this.ws?.tasks.find((x) => x.id === picked.id) ?? picked;
      const meta = [["project", full.project], ["due", full.due], ["priority", tag(full.priority) || "-"], ["labels", (full.labels ?? []).join(", ")], ["id", full.id], ["url", full.url]].filter(([, v]) => v);
      return root.child(header)
        .child(v_flex().flex_1().min_h(0).overflow_y_scrollbar().gap(6)
          .child(div().text_size(15).font_semibold().child(full.title))
          .children(meta.map(([k, v]) => div().text_color(t.muted).child(`${k}: ${v}`)))
          .child(div().pt(6).text_color(t.foreground).child(full.desc || "(no description)")))
        .child(div().text_size(11).text_color(t.dim).child("Esc closes")).child(status);
    }

    const tree = v_flex().w(TREE_W).h_full().min_h(0).overflow_y_scrollbar().gap(1).children(this.rows().map((r, i) => {
      const on = r.node && i === this.tsel;
      const el = h_flex().id(`tr-${i}`).gap(6).px(8).py(4).rounded(7).items_center()
        .bg(on ? (this.focus === "tree" ? t.selected : t.hover) : t.popover)
        .child(div().w(r.indent * 14).h(1))
        .child(div().flex_1().truncate().text_color(r.node ? t.foreground : t.dim).text_size(r.node ? 13 : 11).child(r.label))
        .child(div().text_size(11).text_color(t.dim).child(r.count ? String(r.count) : ""));
      return r.node ? el.hover((s) => s.bg(t.hover)).on_click(() => { this.tsel = i; this.sel = 0; this.focus = "tasks"; cx.notify(); }) : el;
    }));

    const showProject = cur.searching || cur.node.kind !== "project";
    const list = v_flex().flex_1().min_h(0).overflow_y_scrollbar().gap(1).children(cur.shown.map(({ t: x, depth, kids }, i) => {
      const inCart = this.cart.some((c) => c.id === x.id);
      const p = tag(x.priority);
      return h_flex().id(`tk-${x.id}`).gap(8).px(8).py(4).rounded(7).items_center()
        .bg(i === sel && this.focus === "tasks" ? t.selected : t.popover).hover((s) => s.bg(t.hover))
        .on_click(() => { this.sel = i; this.focus = "tasks"; this.toggleCart(cx, x); })
        .child(div().w(14).text_color(t.accent).child(inCart ? "✓" : ""))
        .child(div().w(22).text_size(11).font_semibold().text_color(p === "P1" ? t.blocked : t.working).child(p))
        .child(div().w(depth * 16).h(1))
        .child(div().flex_1().truncate().child((kids ? (this.collapsed.has(x.id) ? "+ " : "- ") : "") + x.title))
        .when(showProject, (el) => el.child(div().w(130).truncate().text_size(11.5).text_color(t.dim).child(x.project)))
        .child(div().w(44).text_size(11.5).text_color(t.dim).child((x.due ?? "").slice(5, 10)));
    }));

    const detail = v_flex().h(74).gap(2).pt(6)
      .child(div().font_semibold().truncate().child(picked?.title ?? ""))
      .child(div().text_size(11).text_color(t.dim).truncate().child(picked ? [picked.project, picked.due, picked.id].filter(Boolean).join(" · ") : ""))
      .child(div().text_size(11.5).text_color(t.muted).max_h(32).overflow_hidden().child(plain(picked?.desc)));

    return root.child(header)
      .child(h_flex().flex_1().min_h(0).gap(10)
        .child(tree)
        .child(v_flex().flex_1().min_h(0).gap(6)
          .child(h_flex().items_center().gap(8)
            .child(div().flex_1().text_color(t.muted).truncate().child(cur.title))
            .child(Input.new(this.input).w(260).h(30).px(10).rounded(8).border_1().border_color(this.query ? t.accent : t.input).bg(t.background).text_size(12.5).text_color(t.foreground)))
          .child(list).child(detail)))
      .child(status);
  }
}
