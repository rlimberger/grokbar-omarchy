# Grokbar (Omarchy)

Omarchy bar widget for SuperGrok and Cursor usage:

- **Grok** — icon + weekly SuperGrok pool % (shared across Chat, Grok Build, Imagine, Voice, API) + reset (`5d` when ≥1 day left, `12h` when under a day)
- **Cursor** — icon + Cursor Models % + Other Models % + reset

Each cluster shows only when that provider has data.

Click the panel for provider cards:

- **Grok** — weekly %, reset, segmented bar, product legend (e.g. Chat 11% · Grok Build 8%) from the same credits API as grok.com Settings → Usage
- **Cursor** — two independent monthly meters (Cursor Models, Other Models) with a pace marker. No day ticks.

**Cursor is shown only when it matches Grok.** The Cursor account email
must be the same as `~/.grok/auth.json`. Any other Cursor login is hidden.

Self-hides per provider when that account is missing or has no period-pool data. The widget hides entirely if neither has data. Left click opens the usage panel; right click refreshes.

## Interactions

- Bar widget: left = panel · right = refresh
- Panel: `r` or Enter refresh · Tab neighboring panel · Esc close

## Install

Plugins land disabled until you enable them. Plugin id: `rlimberger.grokbar-omarchy`.

**Preferred** — add from GitHub, then enable:

```bash
omarchy plugin add https://github.com/rlimberger/grokbar-omarchy.git
omarchy plugin enable rlimberger.grokbar-omarchy --section right
```

Or add and enable in one step:

```bash
omarchy plugin add https://github.com/rlimberger/grokbar-omarchy.git --enable
```

**Hand-install** — clone or copy into a folder that matches the manifest id, then rescan and enable:

```bash
git clone https://github.com/rlimberger/grokbar-omarchy.git \
  ~/.config/omarchy/plugins/rlimberger.grokbar-omarchy
omarchy-shell shell rescanPlugins
omarchy plugin enable rlimberger.grokbar-omarchy --section right
```

Disable:

```bash
omarchy plugin disable rlimberger.grokbar-omarchy
```

If you also have the older standalone plugin `rlimberger.cursor-usage`, disable it so you do not get two Cursor clusters:

```bash
omarchy plugin disable rlimberger.cursor-usage
```

After QML or scanner edits, reload the shell:

```bash
omarchy-shell shell rescanPlugins
omarchy restart shell
```

## Auth

**Grok** — sign in with the official Grok Build CLI so the scanner can read credentials:

```bash
grok login
```

Tokens live in `~/.grok/auth.json` (mode `0600`). The scanner refreshes expired
OIDC access tokens via `auth.x.ai` and writes them back atomically.

**Cursor** — sign in with the same account as Grok (same email). Tokens live
in `~/.config/cursor/auth.json` or the IDE `state.vscdb`. A different Cursor
login is ignored.

## Settings

Settings live in the widget's entry in `~/.config/omarchy/shell.json`.
Set them with `omarchy bar set rlimberger.grokbar-omarchy <key> <value>`:

| Key | Default | What it does |
|---|---|---|
| `refreshIntervalSec` | `300` | How often the scanner re-runs |
| `authPath` | `""` | Override Grok `auth.json` path |
| `cursorAuthPath` | `""` | Override Cursor CLI `auth.json` path |
| `stateDbPath` | `""` | Override Cursor `state.vscdb` path |

Numbers need `--json`, or they land in `shell.json` as strings:

```bash
omarchy bar set rlimberger.grokbar-omarchy refreshIntervalSec 120 --json
```

## Data sources

| What | Endpoint | Notes |
|---|---|---|
| **Weekly pool** | `POST https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig` | Shared weekly pool (gRPC-web protobuf) + product breakdown |
| **Plan name** | `GET https://cli-chat-proxy.grok.com/v1/settings` | `subscription_tier_display` (same field the Grok CLI shows, e.g. SuperGrok Heavy) |
| **Cursor monthly pools** | `POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage` | Cursor Models + Other Models (X-login only) |

## Files

- `BarWidget.qml` — bar widget, timers, and click actions
- `Panel.qml` — Grok card and/or Cursor card
- `scripts/grokbar_scanner.py` — SuperGrok weekly usage scanner
- `scripts/cursor_usage_scanner.py` — Cursor monthly-pool scanner (X-login only)
- `assets/grok.svg` — white Grok icon; recolored to `bar.foreground`
- `assets/grok-light.svg` — dark Grok icon for light popup surfaces
- `assets/cursor.svg` — white Cursor icon; recolored to `bar.foreground`
- `assets/cursor-light.svg` — dark Cursor icon for light popup surfaces
