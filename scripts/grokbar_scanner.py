#!/usr/bin/env python3
"""Scan SuperGrok weekly usage for the Omarchy bar widget.

SuperGrok paid plans share one weekly usage pool across products (Chat, Build,
Imagine, Voice, API). There is no monthly SuperGrok pool to display.

Source (same surface used by CodexBar / GNOME SuperGrok usage extensions):
  - Weekly SuperGrok pool: gRPC-web GetGrokCreditsConfig on grok.com

Auth: ~/.grok/auth.json (written by `grok login`). Expired OIDC access tokens
are refreshed via auth.x.ai and written back atomically.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_AUTH = Path.home() / ".grok" / "auth.json"
CREDITS_URL = "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
# Same settings surface the Grok CLI uses for subscription_tier_display.
SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
USER_AGENT = "grokbar-omarchy/1.0"

# Product labels for credit-usage category enum (GetGrokCreditsConfig field 1.7).
# Confirmed against grok.com Settings → Usage (Aug 2026):
#   type 4 → Chat, type 2 → Grok Build (percentages match the official UI).
# Remaining ids are best-effort from product list order; unknown → "Category N".
CATEGORY_LABELS = {
    1: "API",
    2: "Grok Build",
    3: "Imagine",
    4: "Chat",
    5: "Voice",
}

# Legend order matching the official Usage card (Chat, then Grok Build, …).
CATEGORY_ORDER = {
    4: 0,  # Chat
    2: 1,  # Grok Build
    1: 2,  # API
    3: 3,  # Imagine
    5: 4,  # Voice
}


def empty_result(**overrides):
  out = {
    "ready": True,
    "hasLocalStats": True,
    "todayPrompts": 0,
    "todaySessions": 0,
    "todayTotalTokens": 0,
    "todayTokensByModel": {},
    "recentDays": [],
    "totalPrompts": 0,
    "totalSessions": 0,
    "activeDays": 0,
    "activeDates": [],
    "modelUsage": {},
    "rateLimitPercent": -1,
    "rateLimitLabel": "Weekly",
    "rateLimitResetAt": "",
    "rateLimitPeriodStart": "",
    "secondaryRateLimitPercent": -1,
    "secondaryRateLimitLabel": "",
    "secondaryRateLimitResetAt": "",
    "tierLabel": "",
    "usageStatusText": "",
    "authHelpText": "",
    "categories": [],
  }
  out.update(overrides)
  return out


def expand_path(value):
  text = str(value or "").strip()
  if not text:
    return DEFAULT_AUTH
  return Path(os.path.expanduser(text)).expanduser()


def emit(payload):
  print(json.dumps(payload, separators=(",", ":")))
  return 0


def parse_iso(value):
  text = str(value or "").strip()
  if not text:
    return None
  try:
    if text.endswith("Z"):
      text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt
  except Exception:
    return None


def to_iso(dt):
  if dt is None:
    return ""
  return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_auth(auth_path):
  if not auth_path.is_file():
    return None, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="Run `grok login` to sign in. Credentials are stored in ~/.grok/auth.json.",
    )

  try:
    raw = auth_path.read_text(encoding="utf-8")
    data = json.loads(raw)
  except Exception as exc:
    return None, empty_result(
      usageStatusText="Grok unavailable",
      authHelpText=f"Could not read Grok auth file: {exc}",
    )

  if not isinstance(data, dict) or not data:
    return None, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="Grok auth file is empty. Run `grok login`.",
    )

  # Prefer auth.x.ai OIDC entries (current SuperGrok / Grok Build login).
  preferred = []
  others = []
  for scope, entry in data.items():
    if not isinstance(entry, dict):
      continue
    if not entry.get("key") and not entry.get("access_token"):
      continue
    if str(scope).startswith("https://auth.x.ai"):
      preferred.append((scope, entry))
    else:
      others.append((scope, entry))

  candidates = preferred + others
  if not candidates:
    return None, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="No access token in ~/.grok/auth.json. Run `grok login`.",
    )

  scope, entry = candidates[0]
  token = entry.get("key") or entry.get("access_token")
  if not token:
    return None, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="No access token in ~/.grok/auth.json. Run `grok login`.",
    )

  creds = {
    "scope": scope,
    "entry": entry,
    "token": str(token),
    "refresh_token": entry.get("refresh_token") or "",
    "expires_at": entry.get("expires_at") or "",
    "client_id": entry.get("oidc_client_id") or "",
    "issuer": entry.get("oidc_issuer") or "https://auth.x.ai",
    "email": entry.get("email") or "",
    "team_id": entry.get("team_id") or "",
    "auth_path": auth_path,
    "auth_data": data,
  }
  return creds, None


def token_is_fresh(creds, skew_sec=120):
  exp = parse_iso(creds.get("expires_at"))
  if exp is None:
    return True  # no expiry recorded — treat as usable
  return exp > datetime.now(timezone.utc) + timedelta(seconds=skew_sec)


def save_auth(creds):
  """Atomically write refreshed tokens back to auth.json (mode 0600)."""
  path = creds["auth_path"]
  data = creds["auth_data"]
  scope = creds["scope"]
  entry = dict(data.get(scope) or {})
  entry["key"] = creds["token"]
  if creds.get("refresh_token"):
    entry["refresh_token"] = creds["refresh_token"]
  if creds.get("expires_at"):
    entry["expires_at"] = creds["expires_at"]
  data[scope] = entry

  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".auth.", suffix=".tmp", dir=str(path.parent))
    try:
      with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
      os.chmod(tmp, 0o600)
      os.replace(tmp, path)
    except Exception:
      try:
        os.unlink(tmp)
      except OSError:
        pass
      raise
  except Exception as exc:
    # Non-fatal: in-memory token still works for this scan.
    sys.stderr.write(f"grokbar-omarchy: could not write auth.json: {exc}\n")


def refresh_token(creds):
  refresh = str(creds.get("refresh_token") or "").strip()
  client_id = str(creds.get("client_id") or "").strip()
  if not refresh or not client_id:
    return False, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="Grok session expired. Run `grok login` again.",
    )

  body = urllib.parse.urlencode({
    "grant_type": "refresh_token",
    "refresh_token": refresh,
    "client_id": client_id,
  }).encode("utf-8")
  req = urllib.request.Request(
    TOKEN_URL,
    data=body,
    method="POST",
    headers={
      "Content-Type": "application/x-www-form-urlencoded",
      "Accept": "application/json",
      "User-Agent": USER_AGENT,
    },
  )
  try:
    with urllib.request.urlopen(req, timeout=20) as resp:
      payload = json.loads(resp.read().decode("utf-8", errors="replace"))
  except urllib.error.HTTPError as exc:
    raw = exc.read().decode("utf-8", errors="replace")
    if exc.code in (400, 401, 403):
      return False, empty_result(
        usageStatusText="Sign in to Grok",
        authHelpText="Grok session expired. Run `grok login` again.",
      )
    return False, empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=f"Token refresh failed (HTTP {exc.code}): {raw[:120]}",
    )
  except Exception as exc:
    return False, empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=f"Token refresh failed: {exc}",
    )

  access = payload.get("access_token")
  if not access:
    return False, empty_result(
      usageStatusText="Sign in to Grok",
      authHelpText="Token refresh returned no access_token. Run `grok login`.",
    )

  creds["token"] = access
  if payload.get("refresh_token"):
    creds["refresh_token"] = payload["refresh_token"]
  expires_in = payload.get("expires_in")
  if expires_in is not None:
    try:
      exp = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
      creds["expires_at"] = to_iso(exp)
    except Exception:
      pass
  save_auth(creds)
  return True, None


def ensure_token(creds):
  if token_is_fresh(creds):
    return True, None
  return refresh_token(creds)


def _auth_headers(token, content_type=None, extra=None):
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": content_type or "application/json",
    "User-Agent": USER_AGENT,
    # Same surface header the CLI sends so settings match the TUI.
    "x-grok-client-surface": "grok-build",
  }
  if content_type:
    headers["Content-Type"] = content_type
  if extra:
    headers.update(extra)
  return headers


def http_get_json(url, token, timeout=20):
  req = urllib.request.Request(
    url,
    method="GET",
    headers=_auth_headers(token),
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      raw = resp.read().decode("utf-8", errors="replace")
      status = getattr(resp, "status", 200)
  except urllib.error.HTTPError as exc:
    status = exc.code
    raw = exc.read().decode("utf-8", errors="replace")
    if status in (401, 403):
      return None, "auth", empty_result(
        usageStatusText="Sign in to Grok",
        authHelpText="Grok session expired. Run `grok login` again.",
      )
    return None, "http", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=f"Settings API returned HTTP {status}",
    )
  except Exception as exc:
    return None, "net", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=str(exc),
    )

  if status < 200 or status >= 300:
    return None, "http", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=f"Settings API returned HTTP {status}",
    )
  try:
    return json.loads(raw), None, None
  except Exception:
    return None, "parse", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText="Could not parse settings response.",
    )


def http_post_bytes(url, token, body, content_type, timeout=20):
  req = urllib.request.Request(
    url,
    data=body,
    method="POST",
    headers=_auth_headers(
      token,
      content_type=content_type,
      extra={"x-grpc-web": "1"},
    ),
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      return resp.read(), None, None
  except urllib.error.HTTPError as exc:
    status = exc.code
    raw = exc.read()
    if status in (401, 403):
      return None, "auth", empty_result(
        usageStatusText="Sign in to Grok",
        authHelpText="Grok session expired. Run `grok login` again.",
      )
    return None, "http", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=f"Credits API returned HTTP {status}",
    )
  except Exception as exc:
    return None, "net", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText=str(exc),
    )


# --- protobuf / gRPC-web helpers (CodexBar / GNOME extension compatible) ---

def _read_varint(buf, index):
  value = 0
  shift = 0
  while index < len(buf) and shift < 64:
    b = buf[index]
    index += 1
    value |= (b & 0x7F) << shift
    if (b & 0x80) == 0:
      return value, index
    shift += 7
  return None, index


def _grpc_web_data_frames(raw):
  frames = []
  i = 0
  while i + 5 <= len(raw):
    flags = raw[i]
    length = int.from_bytes(raw[i + 1:i + 5], "big")
    start = i + 5
    end = start + length
    if length < 0 or end > len(raw):
      return None
    if (flags & 0x80) == 0:
      frames.append(raw[start:end])
    i = end
  return frames


def _looks_like_protobuf(buf):
  if not buf:
    return False
  field = buf[0] >> 3
  wire = buf[0] & 0x07
  return field > 0 and wire in (0, 1, 2, 5)


def _scan_protobuf(buf, depth=0, path=None):
  if path is None:
    path = []
  fixed32 = []
  varints = []
  categories = []  # (type_id, percent_or_None)
  index = 0
  order = 0

  while index < len(buf):
    field_start = index
    key, index = _read_varint(buf, index)
    if key is None or key == 0:
      index = field_start + 1
      continue
    field_number = key >> 3
    wire_type = key & 0x07
    field_path = path + [field_number]

    if wire_type == 0:
      value, index = _read_varint(buf, index)
      if value is None:
        index = field_start + 1
        continue
      varints.append((field_path, value))
    elif wire_type == 1:
      if index + 8 > len(buf):
        break
      index += 8
    elif wire_type == 2:
      length, index = _read_varint(buf, index)
      if length is None or index + length > len(buf):
        index = field_start + 1
        continue
      start = index
      end = start + length
      nested = buf[start:end]
      # Category entries live at path [1, 7] as repeated messages.
      if len(field_path) == 2 and field_path[0] == 1 and field_path[1] == 7:
        cat_type = None
        cat_pct = None
        nested_fields = _scan_protobuf(nested, depth + 1, field_path)
        for p, v in nested_fields["varints"]:
          if p and p[-1] == 1:
            cat_type = int(v)
        for p, v, _ord in nested_fields["fixed32"]:
          if p and p[-1] == 2 and 0 <= v <= 100:
            cat_pct = float(v)
        if cat_type is not None:
          categories.append((cat_type, cat_pct if cat_pct is not None else 0.0))
        else:
          fixed32.extend(nested_fields["fixed32"])
          varints.extend(nested_fields["varints"])
      elif depth < 4:
        nested_fields = _scan_protobuf(nested, depth + 1, field_path)
        fixed32.extend(nested_fields["fixed32"])
        varints.extend(nested_fields["varints"])
        categories.extend(nested_fields["categories"])
      index = end
    elif wire_type == 5:
      if index + 4 > len(buf):
        break
      value = struct.unpack_from("<f", buf, index)[0]
      fixed32.append((field_path, float(value), order))
      order += 1
      index += 4
    else:
      index = field_start + 1

  return {"fixed32": fixed32, "varints": varints, "categories": categories}


def parse_credits_config(raw):
  """Return {used_fraction, reset_iso, categories[]} or None."""
  if not raw:
    return None

  frames = _grpc_web_data_frames(raw)
  if not frames:
    if _looks_like_protobuf(raw):
      frames = [raw]
    else:
      return None

  all_fixed = []
  all_varint = []
  all_cats = []
  for payload in frames:
    scan = _scan_protobuf(payload)
    all_fixed.extend(scan["fixed32"])
    all_varint.extend(scan["varints"])
    all_cats.extend(scan["categories"])

  # credit_usage_percent: fixed32 float 0–100, field number ending in 1;
  # prefer shallower paths (CodexBar: min path length, then order).
  percent_candidates = [
    (path, value, ord_)
    for path, value, ord_ in all_fixed
    if path and path[-1] == 1 and 0 <= value <= 100
  ]
  percent_candidates.sort(key=lambda item: (len(item[0]), item[2]))
  used_percent = percent_candidates[0][1] if percent_candidates else None

  # Period timestamps: start [1, 4, 1], end [1, 5, 1] (unix seconds).
  now_sec = datetime.now(timezone.utc).timestamp()
  ts_fields = [
    (path, value)
    for path, value in all_varint
    if 1_700_000_000 <= value <= 2_100_000_000
  ]
  future = [(p, v) for p, v in ts_fields if v > now_sec]
  resets_at_sec = None
  preferred_end = next(
    (v for p, v in future if len(p) == 3 and p == [1, 5, 1]),
    None,
  )
  if preferred_end is not None:
    resets_at_sec = preferred_end
  elif future:
    resets_at_sec = min(v for _, v in future)

  period_start_sec = next(
    (v for p, v in ts_fields if len(p) == 3 and p == [1, 4, 1]),
    None,
  )
  # Fallback: any past timestamp at [1, 4, *] or earliest past ts before reset.
  if period_start_sec is None:
    past = [(p, v) for p, v in ts_fields if v <= now_sec]
    preferred_start = next(
      (v for p, v in past if len(p) >= 2 and p[0] == 1 and p[1] == 4),
      None,
    )
    if preferred_start is not None:
      period_start_sec = preferred_start
    elif past and resets_at_sec is not None:
      candidates = [v for _, v in past if v < resets_at_sec]
      if candidates:
        period_start_sec = max(candidates)

  # proto3 omits zero floats — period present + no % → 0% used.
  has_usage_period = any(
    (len(p) >= 2 and p[0] == 1 and p[1] == 6)
    or (len(p) == 3 and p[0] == 1 and p[1] == 8 and p[2] == 1 and v in (1, 2))
    for p, v in all_varint
  )
  if used_percent is None and not all_fixed and resets_at_sec is not None and has_usage_period:
    used_percent = 0.0

  if used_percent is None:
    return None

  reset_iso = ""
  if resets_at_sec is not None:
    reset_iso = to_iso(datetime.fromtimestamp(resets_at_sec, timezone.utc))

  period_start_iso = ""
  if period_start_sec is not None:
    period_start_iso = to_iso(datetime.fromtimestamp(period_start_sec, timezone.utc))
  elif resets_at_sec is not None:
    # Weekly pool fallback: 7 days before reset.
    period_start_iso = to_iso(
      datetime.fromtimestamp(resets_at_sec, timezone.utc) - timedelta(days=7)
    )

  categories = []
  for type_id, pct in all_cats:
    type_id = int(type_id)
    label = CATEGORY_LABELS.get(type_id, f"Category {type_id}")
    categories.append({
      "title": label,
      "type": type_id,
      "percent": float(pct) / 100.0,
    })
  categories.sort(
    key=lambda c: (
      CATEGORY_ORDER.get(c["type"], 99),
      -c["percent"],
      c["title"],
    )
  )

  return {
    "used_fraction": float(used_percent) / 100.0,
    "reset_iso": reset_iso,
    "period_start_iso": period_start_iso,
    "categories": categories,
  }


def fetch_weekly(creds):
  # Empty gRPC-web message: flags=0, length=0, no payload.
  body = b"\x00\x00\x00\x00\x00"
  raw, kind, err = http_post_bytes(
    CREDITS_URL,
    creds["token"],
    body,
    "application/grpc-web+proto",
    timeout=20,
  )
  if err is not None:
    return None, kind, err
  parsed = parse_credits_config(raw)
  if parsed is None:
    return None, "parse", empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText="Could not parse SuperGrok credits response.",
    )
  return parsed, None, None


def fetch_tier_label(creds):
  """Return subscription display name from the CLI settings API.

  This is the same `subscription_tier_display` field the Grok CLI surfaces
  (e.g. "SuperGrok Heavy"). Failures are non-fatal — weekly usage still works.
  """
  payload, kind, err = http_get_json(SETTINGS_URL, creds["token"], timeout=15)
  if err is not None:
    return "", kind, err
  if not isinstance(payload, dict):
    return "", "parse", None
  label = str(payload.get("subscription_tier_display") or "").strip()
  return label, None, None


def jwt_tier_fallback(token):
  """Best-effort tier from the OIDC access-token claim (numeric).

  Used only when /v1/settings is unavailable. The claim is authoritative for
  auth.x.ai, but the display string is preferred when the settings API works.
  """
  try:
    parts = str(token or "").split(".")
    if len(parts) < 2:
      return ""
    import base64

    pad = "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
  except Exception:
    return ""

  # Prefer a string claim if ever present.
  for key in ("subscription_tier_display", "subscription_tier", "tier_name", "plan"):
    val = payload.get(key)
    if isinstance(val, str) and val.strip():
      return val.strip()

  # Numeric `tier` claim observed in auth.x.ai access tokens.
  # Verified against Grok CLI settings for this account (5 → SuperGrok Heavy).
  # Keep the mapping conservative: only known values, else empty.
  tier = payload.get("tier")
  try:
    tier_n = int(tier)
  except (TypeError, ValueError):
    return ""
  # Confirmed via /v1/settings subscription_tier_display for tier==5.
  # Other values intentionally unmapped until verified against the settings API.
  known = {
    5: "SuperGrok Heavy",
  }
  return known.get(tier_n, "")


def build_result(weekly, tier_label=""):
  # Shared weekly pool only — no monthly SuperGrok limit.
  return empty_result(
    rateLimitPercent=weekly["used_fraction"],
    rateLimitLabel="Weekly",
    rateLimitResetAt=weekly.get("reset_iso") or "",
    rateLimitPeriodStart=weekly.get("period_start_iso") or "",
    secondaryRateLimitPercent=-1,
    secondaryRateLimitLabel="",
    secondaryRateLimitResetAt="",
    tierLabel=tier_label or "",
    categories=weekly.get("categories") or [],
  )


def with_auth_retry(creds, fetch_fn):
  """Call fetch_fn(creds); on auth failure refresh once and retry."""
  result, kind, err = fetch_fn(creds)
  if kind != "auth":
    return result, kind, err
  ok, refresh_err = refresh_token(creds)
  if not ok:
    return None, "auth", refresh_err
  return fetch_fn(creds)


def main(argv=None):
  parser = argparse.ArgumentParser(description="Scan SuperGrok weekly usage")
  parser.add_argument(
    "--auth",
    default=os.environ.get("GROK_AUTH_PATH", str(DEFAULT_AUTH)),
    help="Path to Grok auth.json (default: ~/.grok/auth.json)",
  )
  args = parser.parse_args(argv)

  auth_path = expand_path(args.auth)
  creds, error = load_auth(auth_path)
  if error is not None:
    return emit(error)

  ok, error = ensure_token(creds)
  if not ok:
    return emit(error)

  weekly, kind, err = with_auth_retry(creds, fetch_weekly)
  if weekly is None:
    return emit(err or empty_result(
      usageStatusText="Grok limits unavailable",
      authHelpText="Could not load SuperGrok weekly usage.",
    ))

  # Tier is best-effort; never fail the scan if settings is down.
  tier_label = ""
  tier, tier_kind, _tier_err = with_auth_retry(creds, fetch_tier_label)
  if tier_kind != "auth" and tier:
    tier_label = tier
  if not tier_label:
    tier_label = jwt_tier_fallback(creds.get("token"))

  return emit(build_result(weekly, tier_label=tier_label))


if __name__ == "__main__":
  sys.exit(main())
