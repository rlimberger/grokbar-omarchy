# Grok Usage

Omarchy bar widget for SuperGrok / Grok Build usage:

- **Icon + %** — weekly SuperGrok pool (shared across Chat, Grok Build, Imagine, Voice, API)
- **Reset** — `5d` when ≥1 day left, `12h` when under a day

Click the panel for a Usage-style card: total weekly %, reset countdown, segmented
bar, and product legend (e.g. Chat 11% · Grok Build 8%) from the same credits API
as grok.com Settings → Usage.

Self-hides when you are not signed in to Grok (`~/.grok/auth.json`) or when no
period-pool data is available. Left click opens a Grok-only usage panel; right
click refreshes.

## Interactions

- Bar widget: left = panel · right = refresh
- Panel: `r` or Enter refresh · Tab neighboring panel · Esc close

## Install

Plugins land disabled until you enable them. Plugin id: `rlimberger.grok-usage`.

**Preferred** — add from GitHub, then enable:

```bash
omarchy plugin add https://github.com/rlimberger/omarchy-grok-usage.git
omarchy plugin enable rlimberger.grok-usage --section right
```

Or add and enable in one step:

```bash
omarchy plugin add https://github.com/rlimberger/omarchy-grok-usage.git --enable
```

**Hand-install** — clone or copy into a folder that matches the manifest id, then rescan and enable:

```bash
git clone https://github.com/rlimberger/omarchy-grok-usage.git \
  ~/.config/omarchy/plugins/rlimberger.grok-usage
omarchy-shell shell rescanPlugins
omarchy plugin enable rlimberger.grok-usage --section right
```

Disable:

```bash
omarchy plugin disable rlimberger.grok-usage
```

After QML or scanner edits, reload the shell:

```bash
omarchy-shell shell rescanPlugins
omarchy restart shell
```

## Auth

Sign in with the official Grok Build CLI so the scanner can read credentials:

```bash
grok login
```

Tokens live in `~/.grok/auth.json` (mode `0600`). The scanner refreshes expired
OIDC access tokens via `auth.x.ai` and writes them back atomically.

## Settings

Settings live in the widget's entry in `~/.config/omarchy/shell.json`.
Set them with `omarchy bar set rlimberger.grok-usage <key> <value>`:

| Key | Default | What it does |
|---|---|---|
| `refreshIntervalSec` | `300` | How often the scanner re-runs |
| `authPath` | `""` | Override Grok `auth.json` path |

Numbers need `--json`, or they land in `shell.json` as strings:

```bash
omarchy bar set rlimberger.grok-usage refreshIntervalSec 120 --json
```

## Data sources

| What | Endpoint | Notes |
|---|---|---|
| **Weekly pool** | `POST https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig` | Shared weekly pool (gRPC-web protobuf) + product breakdown |
| **Plan name** | `GET https://cli-chat-proxy.grok.com/v1/settings` | `subscription_tier_display` (same field the Grok CLI shows, e.g. SuperGrok Heavy) |

## Files

- `BarWidget.qml` — bar widget, timers, and click actions
- `Panel.qml` — Grok-only usage panel (weekly pool + product breakdown)
- `scripts/grok_usage_scanner.py` — SuperGrok weekly usage scanner
- `assets/grok.svg` — white Grok icon; recolored to `bar.foreground`
- `assets/grok-light.svg` — dark icon for light popup surfaces
