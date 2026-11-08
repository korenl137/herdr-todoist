//! Core of the Todoist picker: data from the `td` CLI, the cart and its history.
//! Every public function returns plain data; `main.rs` prints it as JSON for the JS mod.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub const HISTORY_MAX: usize = 100; // oldest sent carts are dropped past this

/// A task as the picker shows it. Field names match the old picker so saved carts keep loading.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct Task {
    pub id: String,
    pub title: String,
    #[serde(default)] pub project: String,
    #[serde(default)] pub project_id: String,
    #[serde(default)] pub due: String,
    #[serde(default)] pub url: String,
    #[serde(default)] pub labels: Vec<String>,
    #[serde(default)] pub desc: String,
    #[serde(default = "one")] pub priority: u8,
    #[serde(default)] pub parent_id: Option<String>,
}
fn one() -> u8 { 1 }

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Sent { pub sent: String, pub pane: String, pub items: Vec<Task> }

/// Where the cart lives and how to reach `td`.
pub struct Env {
    pub dir: PathBuf,       // cart.json, history.jsonl
    pub td_home: PathBuf,   // has node_modules/.bin/td
    pub env_file: PathBuf,  // TODOIST_API_TOKEN=...
}

impl Env {
    fn cart(&self) -> PathBuf { self.dir.join("cart.json") }
    fn history(&self) -> PathBuf { self.dir.join("history.jsonl") }
}

/// Reads TODOIST_API_TOKEN from an env file. The token only ever goes to `td`'s environment.
pub fn read_token(file: &Path) -> Result<String> {
    let text = fs::read_to_string(file).with_context(|| format!("cannot read {}", file.display()))?;
    text.lines()
        .filter_map(|l| l.split_once('='))
        .find(|(k, _)| k.trim() == "TODOIST_API_TOKEN")
        .map(|(_, v)| v.trim().trim_matches(|c| c == '"' || c == '\'').to_string())
        .filter(|v| !v.is_empty())
        .context("TODOIST_API_TOKEN not found in the env file")
}

fn td(env: &Env, args: &[&str]) -> Result<Vec<Value>> {
    let path = format!("{}:{}", env.td_home.join("node_modules/.bin").display(), std::env::var("PATH").unwrap_or_default());
    let out = Command::new("td").args(args).arg("--json")
        .env("PATH", path).env("NO_COLOR", "1").env("TODOIST_API_TOKEN", read_token(&env.env_file)?)
        .output().context("cannot run td (set TD_HOME to the folder that has node_modules/.bin/td)")?;
    if !out.status.success() { bail!("{}", String::from_utf8_lossy(&out.stderr).trim()); }
    let v: Value = serde_json::from_slice(&out.stdout).context("td printed invalid JSON")?;
    Ok(v["results"].as_array().cloned().unwrap_or_default())
}

pub fn normalize(t: &Value, projects: &HashMap<String, String>) -> Task {
    let s = |k: &str| t[k].as_str().unwrap_or_default().to_string();
    let pid = s("projectId");
    Task {
        id: s("id"), title: s("content"), project: projects.get(&pid).cloned().unwrap_or_default(), project_id: pid,
        due: t["due"]["date"].as_str().unwrap_or_default().to_string(), url: s("url"),
        labels: t["labels"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
        desc: s("description"), priority: t["priority"].as_u64().unwrap_or(1) as u8,
        parent_id: t["parentId"].as_str().map(String::from),
    }
}

#[derive(Serialize)]
pub struct Workspace { pub projects: Vec<Value>, pub filters: Vec<Value>, pub tasks: Vec<Task> }

/// Inbox, Today and Next 7 days lead the Favorites; one whose query a favourite already has is skipped.
fn with_builtin_filters(favourites: Vec<Value>) -> Vec<Value> {
    let mut all: Vec<Value> = [("Inbox", "#Inbox"), ("Today", "overdue | today"), ("Next 7 days", "next 7 days")].iter()
        .filter(|(_, q)| !favourites.iter().any(|f| f["query"].as_str() == Some(q)))
        .map(|(n, q)| serde_json::json!({"name": n, "query": q})).collect();
    all.extend(favourites);
    all
}

/// Favourite filters with their tasks, every project, every open task. The td calls run in parallel.
pub fn workspace(env: &Env) -> Result<Workspace> {
    let projects = td(env, &["project", "list", "--all"])?;
    let names: HashMap<String, String> = projects.iter()
        .filter_map(|p| Some((p["id"].as_str()?.to_string(), p["name"].as_str()?.to_string()))).collect();
    let favourites: Vec<Value> = td(env, &["filter", "list"])?.into_iter().filter(|f| f["isFavorite"].as_bool() == Some(true)).collect();
    let filters = with_builtin_filters(favourites);
    let (all, per_filter) = std::thread::scope(|s| -> Result<(Vec<Value>, Vec<Vec<Value>>)> {
        let all = s.spawn(|| td(env, &["task", "list", "--all"]));
        let each: Vec<_> = filters.iter().map(|f| {
            let q = f["query"].as_str().unwrap_or_default().to_string();
            s.spawn(move || td(env, &["task", "list", "--filter", &q, "--all"]))
        }).collect();
        let all = all.join().map_err(|_| anyhow::anyhow!("td thread panicked"))??;
        let mut per = vec![];
        for h in each { per.push(h.join().map_err(|_| anyhow::anyhow!("td thread panicked"))??); }
        Ok((all, per))
    })?;
    let filters = filters.into_iter().zip(per_filter).map(|(mut f, ts)| {
        f["tasks"] = serde_json::to_value(ts.iter().map(|t| normalize(t, &names)).collect::<Vec<_>>()).unwrap();
        f
    }).collect();
    Ok(Workspace { projects, filters, tasks: all.iter().map(|t| normalize(t, &names)).collect() })
}

fn write_atomic(path: &Path, text: &str) -> Result<()> {
    if let Some(d) = path.parent() { fs::create_dir_all(d)?; }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, text)?;
    fs::rename(tmp, path)?;
    Ok(())
}

pub fn load_cart(env: &Env) -> Result<Vec<Task>> {
    match fs::read_to_string(env.cart()) {
        Ok(s) => Ok(serde_json::from_str(&s).context("cart.json is invalid")?),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(vec![]),
        Err(e) => Err(e.into()),
    }
}
pub fn save_cart(env: &Env, items: &[Task]) -> Result<()> { write_atomic(&env.cart(), &serde_json::to_string_pretty(items)?) }

/// Adds the task to the cart or removes it; returns true when it is now in. The description stays out of the file.
pub fn toggle(env: &Env, task: &Task) -> Result<bool> {
    let items = load_cart(env)?;
    let kept: Vec<Task> = items.iter().filter(|i| i.id != task.id).cloned().collect();
    let added = kept.len() == items.len();
    let mut next = kept;
    if added { next.push(Task { desc: String::new(), labels: vec![], ..task.clone() }); }
    save_cart(env, &next)?;
    Ok(added)
}

/// Sent carts, newest first; unreadable lines are skipped.
pub fn history(env: &Env) -> Result<Vec<Sent>> {
    let text = match fs::read_to_string(env.history()) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
        Err(e) => return Err(e.into()),
    };
    let mut v: Vec<Sent> = text.lines().filter_map(|l| serde_json::from_str(l).ok()).collect();
    v.reverse();
    Ok(v)
}

fn write_history(env: &Env, oldest_first: &[Sent]) -> Result<()> {
    let mut text = String::new();
    for e in oldest_first { text.push_str(&serde_json::to_string(e)?); text.push('\n'); }
    write_atomic(&env.history(), &text)
}

/// Records the cart as sent to `pane` (newest HISTORY_MAX kept) and empties it.
pub fn archive(env: &Env, pane: &str) -> Result<usize> {
    let items = load_cart(env)?;
    if !items.is_empty() {
        let mut all = history(env)?;
        all.reverse();
        all.push(Sent { sent: chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(), pane: pane.into(), items: items.clone() });
        let skip = all.len().saturating_sub(HISTORY_MAX);
        write_history(env, &all[skip..])?;
    }
    save_cart(env, &[])?;
    Ok(items.len())
}

pub fn delete_history(env: &Env, sent: &str) -> Result<()> {
    let mut all = history(env)?;
    all.reverse();
    all.retain(|e| e.sent != sent);
    write_history(env, &all)
}

/// Puts a sent cart's tasks back (tasks already in the cart stay once).
pub fn restore(env: &Env, sent: &str) -> Result<usize> {
    let entry = history(env)?.into_iter().find(|e| e.sent == sent).context("no such sent cart")?;
    let mut items = load_cart(env)?;
    let have: Vec<String> = items.iter().map(|i| i.id.clone()).collect();
    let back: Vec<Task> = entry.items.into_iter().filter(|i| !have.contains(&i.id)).collect();
    let n = back.len();
    items.extend(back);
    save_cart(env, &items)?;
    Ok(n)
}

/// One line: a newline in pasted text would act as Enter and submit the first task alone.
pub fn format_oneline(items: &[Task]) -> String {
    "Todoist tasks: ".to_string() + &items.iter().map(|i| format!("{} ({}) {}", i.title, i.id, i.url)).collect::<Vec<_>>().join(" | ")
}
pub fn format_lines(items: &[Task]) -> String {
    items.iter().map(|i| format!("- {} ({}) {}", i.title, i.id, i.url)).collect::<Vec<_>>().join("\n")
}

/// The first run after moving from the old plugin brings its cart and history along.
pub fn migrate_old(env: &Env, old_dir: &Path) {
    if env.dir.exists() || !old_dir.is_dir() { return; }
    let _ = fs::create_dir_all(&env.dir);
    for f in ["cart.json", "history.jsonl"] { let _ = fs::copy(old_dir.join(f), env.dir.join(f)); }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn env() -> (tempfile::TempDir, Env) {
        let t = tempfile::tempdir().unwrap();
        let e = Env { dir: t.path().join("d"), td_home: t.path().into(), env_file: t.path().join(".env") };
        (t, e)
    }
    fn task(id: &str) -> Task { Task { id: id.into(), title: format!("task {id}"), url: format!("https://x/{id}"), desc: "long text".into(), ..Default::default() } }

    #[test]
    fn token_is_read_from_the_env_file() {
        let (_t, e) = env();
        fs::write(&e.env_file, "OTHER=1\nTODOIST_API_TOKEN='abc123'\n").unwrap();
        assert_eq!(read_token(&e.env_file).unwrap(), "abc123");
        fs::write(&e.env_file, "TODOIST_API_TOKEN=\n").unwrap();
        assert!(read_token(&e.env_file).is_err());
    }

    #[test]
    fn builtin_filters_lead_and_skip_a_query_a_favourite_has() {
        let names = |v: Vec<Value>| v.iter().map(|f| f["name"].as_str().unwrap().to_string()).collect::<Vec<_>>();
        assert_eq!(names(with_builtin_filters(vec![])), ["Inbox", "Today", "Next 7 days"]);
        let fav = vec![json!({"name": "다음 7일", "query": "next 7 days"})];
        assert_eq!(names(with_builtin_filters(fav)), ["Inbox", "Today", "다음 7일"]);
    }

    #[test]
    fn normalize_maps_td_fields() {
        let names = HashMap::from([("p1".to_string(), "Inbox".to_string())]);
        let t = normalize(&json!({"id":"9","content":"Buy","projectId":"p1","due":{"date":"2026-11-02"},"url":"u","labels":["a"],"priority":4,"parentId":"8"}), &names);
        assert_eq!((t.project.as_str(), t.due.as_str(), t.priority, t.parent_id.as_deref()), ("Inbox", "2026-11-02", 4, Some("8")));
        let bare = normalize(&json!({"id":"1","content":"x","projectId":"zz"}), &names);
        assert_eq!((bare.due.as_str(), bare.priority, bare.project.as_str()), ("", 1, ""));
    }

    #[test]
    fn toggle_adds_then_removes_and_drops_the_description() {
        let (_t, e) = env();
        assert!(toggle(&e, &task("1")).unwrap());
        assert_eq!(load_cart(&e).unwrap()[0].desc, "");
        assert!(!toggle(&e, &task("1")).unwrap());
        assert!(load_cart(&e).unwrap().is_empty());
    }

    #[test]
    fn archive_records_history_and_empties_the_cart() {
        let (_t, e) = env();
        toggle(&e, &task("1")).unwrap();
        toggle(&e, &task("2")).unwrap();
        assert_eq!(archive(&e, "t7").unwrap(), 2);
        assert!(load_cart(&e).unwrap().is_empty());
        let h = history(&e).unwrap();
        assert_eq!((h.len(), h[0].pane.as_str(), h[0].items.len()), (1, "t7", 2));
        assert_eq!(archive(&e, "t7").unwrap(), 0); // an empty cart leaves no record
        assert_eq!(history(&e).unwrap().len(), 1);
    }

    #[test]
    fn history_keeps_the_newest_hundred() {
        let (_t, e) = env();
        let old: Vec<Sent> = (0..HISTORY_MAX).map(|i| Sent { sent: format!("2026-01-01T00:00:{i:02}"), pane: "t1".into(), items: vec![task("o")] }).collect();
        write_history(&e, &old).unwrap();
        toggle(&e, &task("new")).unwrap();
        archive(&e, "t2").unwrap();
        let h = history(&e).unwrap();
        assert_eq!(h.len(), HISTORY_MAX);
        assert_eq!(h[0].items[0].id, "new");               // newest first
        assert!(h.iter().all(|s| s.sent != "2026-01-01T00:00:00")); // the oldest was dropped
    }

    #[test]
    fn restore_skips_tasks_already_in_the_cart_and_delete_removes_an_entry() {
        let (_t, e) = env();
        toggle(&e, &task("1")).unwrap();
        toggle(&e, &task("2")).unwrap();
        archive(&e, "t3").unwrap();
        toggle(&e, &task("2")).unwrap();
        let sent = history(&e).unwrap()[0].sent.clone();
        assert_eq!(restore(&e, &sent).unwrap(), 1);
        assert_eq!(load_cart(&e).unwrap().len(), 2);
        delete_history(&e, &sent).unwrap();
        assert!(history(&e).unwrap().is_empty());
        assert!(restore(&e, "nope").is_err());
    }

    #[test]
    fn text_formats_keep_to_one_line_when_asked() {
        let items = vec![task("1"), task("2")];
        assert_eq!(format_oneline(&items), "Todoist tasks: task 1 (1) https://x/1 | task 2 (2) https://x/2");
        assert!(!format_oneline(&items).contains('\n'));
        assert_eq!(format_lines(&items).lines().count(), 2);
    }

    #[test]
    fn old_cart_and_history_move_over_once() {
        let (t, e) = env();
        let old = t.path().join("old");
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("cart.json"), r#"[{"id":"5","title":"kept"}]"#).unwrap();
        migrate_old(&e, &old);
        assert_eq!(load_cart(&e).unwrap()[0].title, "kept"); // fields the old file lacked take defaults
        fs::write(old.join("cart.json"), "[]").unwrap();
        migrate_old(&e, &old); // the new folder exists now: nothing is copied again
        assert_eq!(load_cart(&e).unwrap().len(), 1);
    }
}
