use anyhow::Result;
use clap::{Parser, Subcommand};
use herdr_todoist as h;
use std::path::PathBuf;

/// Todoist picker core. Every command prints JSON; errors print {"error": "..."} and exit 1.
#[derive(Parser)]
struct Cli {
    #[arg(long, env = "TODOIST_CART_DIR")] dir: Option<PathBuf>,
    #[arg(long, env = "TD_HOME")] td_home: Option<PathBuf>,
    #[arg(long, env = "TODOIST_ENV")] env_file: Option<PathBuf>,
    #[command(subcommand)] cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Projects, favourite filters with their tasks, and all open tasks.
    Workspace,
    /// The cart.
    Cart,
    /// Add or remove one task (JSON on the command line).
    Toggle { task: String },
    /// Empty the cart without a record.
    Clear,
    /// Sent carts, newest first.
    History,
    /// Put a sent cart back into the cart (by its `sent` stamp).
    Restore { sent: String },
    /// Delete one sent cart.
    DeleteHistory { sent: String },
    /// Record the cart as sent to a terminal, then empty it.
    Archive { pane: String },
    /// The cart as text: one line, or a bullet list with --lines.
    Text { #[arg(long)] lines: bool },
}

fn run(c: Cli) -> Result<serde_json::Value> {
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    let env = h::Env {
        dir: c.dir.unwrap_or_else(|| home.join(".config/herdr-todoist")),
        td_home: c.td_home.unwrap_or_else(|| home.join(".local/share/td")),
        env_file: c.env_file.unwrap_or_else(|| home.join(".config/todoist/.env")),
    };
    h::migrate_old(&env, &home.join(".config/herdr/plugins/config/herdr-todoist"));
    Ok(match c.cmd {
        Cmd::Workspace => serde_json::to_value(h::workspace(&env)?)?,
        Cmd::Cart => serde_json::to_value(h::load_cart(&env)?)?,
        Cmd::Toggle { task } => serde_json::json!({ "in": h::toggle(&env, &serde_json::from_str(&task)?)? }),
        Cmd::Clear => { h::save_cart(&env, &[])?; serde_json::json!({ "ok": true }) }
        Cmd::History => serde_json::to_value(h::history(&env)?)?,
        Cmd::Restore { sent } => serde_json::json!({ "restored": h::restore(&env, &sent)? }),
        Cmd::DeleteHistory { sent } => { h::delete_history(&env, &sent)?; serde_json::json!({ "ok": true }) }
        Cmd::Archive { pane } => serde_json::json!({ "archived": h::archive(&env, &pane)? }),
        Cmd::Text { lines } => {
            let items = h::load_cart(&env)?;
            serde_json::json!({ "text": if lines { h::format_lines(&items) } else { h::format_oneline(&items) }, "count": items.len() })
        }
    })
}

fn main() {
    match run(Cli::parse()) {
        Ok(v) => println!("{v}"),
        Err(e) => { println!("{}", serde_json::json!({ "error": format!("{e:#}") })); std::process::exit(1) }
    }
}
