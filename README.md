# Grokbar

Omarchy bar widget for SuperGrok weekly usage, with optional Cursor monthly usage.

- **Grok** — icon, weekly pool percent, and reset (`5d` / `12h`)
- **Cursor** — off by default; enable from the panel to show Cursor Models %, Other Models %, and reset

Left click opens the usage panel. Right click refreshes. The widget hides when there is nothing to show.

Cursor usage is shown only when the local Cursor session belongs to the same account as Grok. Other Cursor logins stay hidden. The panel shows the live subscription email and SuperGrok rebill/expiry date from the Grok and Cursor APIs.

## Install

Plugin id: `rlimberger.grokbar-omarchy`. Plugins stay disabled until you enable them.

```sh
omarchy plugin add https://github.com/rlimberger/grokbar-omarchy.git --enable
```

Or add, then enable on the right of the bar:

```sh
omarchy plugin add https://github.com/rlimberger/grokbar-omarchy.git
omarchy plugin enable rlimberger.grokbar-omarchy --section right
```

Requires **Python 3** on `PATH` (stdlib only; no extra packages). Sign in with the official Grok Build CLI (`grok login`) so SuperGrok usage can load. Cursor usage additionally needs a Cursor session for the same account.

## Usage

- Bar: left click = panel, right click = refresh
- Panel: `r` or Enter refresh, Tab neighboring panel, Esc close
- **Cursor usage** toggle in the panel (off by default)

## Configure

```sh
omarchy bar set rlimberger.grokbar-omarchy showCursorUsage true --json
omarchy bar set rlimberger.grokbar-omarchy refreshIntervalSec 120 --json
```

| Key | Default | What it does |
|---|---|---|
| `showCursorUsage` | `false` | Show Cursor monthly pools on the bar |
| `refreshIntervalSec` | `300` | How often the scanners re-run |
| `authPath` | `""` | Optional Grok `auth.json` override |
| `cursorAuthPath` | `""` | Optional Cursor CLI `auth.json` override |
| `stateDbPath` | `""` | Optional Cursor `state.vscdb` override |

## Remove

```sh
omarchy plugin disable rlimberger.grokbar-omarchy
omarchy plugin remove rlimberger.grokbar-omarchy --yes
```

Removal deletes the cloned plugin folder. It does not change Grok or Cursor login files. If you also installed the older standalone `rlimberger.cursor-usage` plugin, disable that too so you do not get two Cursor clusters.

## Privacy

This plugin reads local Grok and Cursor session files on your machine to call the official usage and subscription APIs. It never logs tokens. Account emails and SuperGrok rebill/expiry are loaded from those APIs at runtime and shown in the panel. Expired Grok (and Cursor CLI) tokens may be refreshed and written back to those same local files.

## License

MIT. See [LICENSE](LICENSE).
