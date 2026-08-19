#!/usr/bin/env python3
"""Scan Cursor period-pool usage for the Omarchy bar widget.

Show Cursor only when that session belongs to the same account as Grok.
A second Cursor login is hidden. The Grok OIDC token is never sent to
Cursor APIs. Account identifiers are never written to scanner JSON.

Sources: ~/.config/cursor/auth.json (CLI) and Cursor state.vscdb (IDE).
Expired session JWTs are refreshed via api2.cursor.sh and written back
only to the CLI auth.json.
"""
from __future__ import annotations

import argparse
import base64
import calendar
import json
import math
import os
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_AUTH = Path.home() / ".config" / "cursor" / "auth.json"
DEFAULT_CLI_CONFIG = Path.home() / ".config" / "cursor" / "cli-config.json"
DEFAULT_GROK_AUTH = Path.home() / ".grok" / "auth.json"
DEFAULT_STATE_DB = (
  Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
)
API_BASE = "https://api2.cursor.sh/aiserver.v1.DashboardService"
TOKEN_URL = "https://api2.cursor.sh/oauth/token"
CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
CURSOR_ISS = "https://authentication.cursor.sh"
USER_AGENT = "grokbar-omarchy/1.1"
REFRESH_SKEW_SEC = 120

ALLOWED_JWT_TYPES = frozenset({"session", "web"})
X_PROVIDERS = frozenset({
  "twitter",
  "twitter-oauth",
  "twitter-oauth-2",
  "twitter-oauth2",
  "x",
  "x-oauth",
  "x-oauth2",
  "oauth_twitter",
})


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
    "rateLimitLabel": "",
    "rateLimitResetAt": "",
    "rateLimitPeriodStart": "",
    "secondaryRateLimitPercent": -1,
    "secondaryRateLimitLabel": "",
    "secondaryRateLimitResetAt": "",
    "tierLabel": "",
    "accountEmail": "",
    "usageStatusText": "",
    "authHelpText": "",
    "categories": [],
    "xLoginFound": False,
  }
  out.update(overrides)
  return out


def expand_path(value, default):
  text = str(value or "").strip()
  if not text:
    return default
  return Path(os.path.expanduser(text)).expanduser()


def emit(payload):
  print(json.dumps(payload, separators=(",", ":")))
  return 0


# Qt Text defaults to AutoText and will fetch <img src="...">. Display fields
# from Cursor APIs must stay plain text even if a QML caller forgets textFormat.
_RESOURCE_MARKUP = (
  "<img", "<image", "<object", "<embed", "<iframe", "<frame",
  "<link", "<meta", "<base", "<source", "<svg", "<script", "<style",
)


def plain_text(value, max_len=128):
  text = str(value or "").replace("\x00", "").strip()
  if not text:
    return ""
  compact = "".join(text.lower().split())
  for tag in _RESOURCE_MARKUP:
    if tag in compact:
      return ""
  if len(text) > max_len:
    return text[:max_len].rstrip()
  return text


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


def decode_jwt(token):
  text = str(token or "").strip()
  if not text:
    return None
  parts = text.split(".")
  if len(parts) < 2:
    return None
  try:
    pad = "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
  except Exception:
    return None
  return payload if isinstance(payload, dict) else None


def jwt_provider_and_sub(payload):
  sub = str((payload or {}).get("sub") or "").strip()
  if not sub:
    return "", ""
  return sub.split("|", 1)[0].strip().lower(), sub


def accept_cursor_x_jwt(token):
  """Return (ok, provider, subject, payload). ok only for Cursor X session/web."""
  payload = decode_jwt(token)
  if not payload:
    return False, "", "", None
  iss = str(payload.get("iss") or "").strip()
  if iss != CURSOR_ISS:
    return False, "", "", payload
  typ = str(payload.get("type") or "").strip().lower()
  if typ not in ALLOWED_JWT_TYPES:
    return False, "", "", payload
  provider, sub = jwt_provider_and_sub(payload)
  if provider not in X_PROVIDERS:
    return False, provider, sub, payload
  return True, provider, sub, payload


def signup_is_google(value):
  return str(value or "").strip().lower() == "google"


def signup_is_x(value):
  text = str(value or "").strip().lower().replace(" ", "-")
  if not text:
    return False
  if text in {"x", "x.com", "twitter"}:
    return True
  return text.startswith("twitter") or text.startswith("x-oauth")


def normalize_email(value):
  return str(value or "").strip().lower()


def emails_match(left, right):
  a = normalize_email(left)
  b = normalize_email(right)
  return bool(a and b and a == b)


def load_grok_email(grok_auth_path):
  """Email on the Grok/xAI OIDC sidecar — the user's X login identity."""
  if not grok_auth_path.is_file():
    return ""
  try:
    data = json.loads(grok_auth_path.read_text(encoding="utf-8"))
  except Exception:
    return ""
  if not isinstance(data, dict):
    return ""
  preferred = []
  others = []
  for scope, entry in data.items():
    if not isinstance(entry, dict):
      continue
    email = normalize_email(entry.get("email"))
    if not email:
      continue
    if str(scope).startswith("https://auth.x.ai") or str(entry.get("oidc_issuer") or "") == "https://auth.x.ai":
      preferred.append(email)
    else:
      others.append(email)
  return (preferred or others or [""])[0]


def load_cli_profile_email(auth_path, subject):
  """cli-config.json authInfo.email when authId matches this session subject."""
  candidates = []
  if auth_path is not None:
    candidates.append(auth_path.parent / "cli-config.json")
  candidates.append(DEFAULT_CLI_CONFIG)
  seen = set()
  for path in candidates:
    try:
      resolved = path.resolve()
    except Exception:
      resolved = path
    if resolved in seen or not path.is_file():
      continue
    seen.add(resolved)
    try:
      data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
      continue
    if not isinstance(data, dict):
      continue
    info = data.get("authInfo")
    if not isinstance(info, dict):
      continue
    auth_id = str(info.get("authId") or "").strip()
    email = info.get("email")
    if subject and auth_id and auth_id != subject:
      continue
    if email:
      return str(email).strip()
  return ""


def cursor_session_ok(payload, provider, email, grok_email):
  """Accept a Cursor session whose email matches the Grok login."""
  if not payload:
    return False
  iss = str(payload.get("iss") or "").strip()
  typ = str(payload.get("type") or "").strip().lower()
  if iss != CURSOR_ISS or typ not in ALLOWED_JWT_TYPES:
    return False
  if not grok_email:
    return False
  return emails_match(email, grok_email)


def expired_x_result(creds=None):
  return empty_result(
    xLoginFound=True,
    usageStatusText="Sign in to Cursor",
    authHelpText="Cursor session expired. Sign in to Cursor again.",
  )


def x_error_result(creds, usage_status, auth_help):
  return empty_result(
    xLoginFound=True,
    usageStatusText=usage_status,
    authHelpText=auth_help,
  )


def load_cli_auth(auth_path, grok_email=""):
  if not auth_path.is_file():
    return None
  try:
    data = json.loads(auth_path.read_text(encoding="utf-8"))
  except Exception:
    return None
  if not isinstance(data, dict) or not data:
    return None

  access = data.get("accessToken") or data.get("access_token") or ""
  refresh = data.get("refreshToken") or data.get("refresh_token") or ""
  if not access:
    return None

  ok, provider, sub, payload = accept_cursor_x_jwt(access)
  email = load_cli_profile_email(auth_path, sub)
  if not cursor_session_ok(payload, provider, email, grok_email):
    return None
  login_provider = provider if ok else "grok-matched"

  return {
    "source": "cli",
    "token": str(access),
    "refresh_token": str(refresh or ""),
    "auth_path": auth_path,
    "auth_data": data,
    "login_provider": login_provider,
    "subject": sub,
    "membership": "",
    "email": email,
  }


def read_item(conn, key):
  row = conn.execute(
    "SELECT value FROM ItemTable WHERE key = ? LIMIT 1",
    (key,),
  ).fetchone()
  if not row or row[0] is None:
    return None
  value = row[0]
  if isinstance(value, bytes):
    value = value.decode("utf-8", errors="replace")
  text = str(value).strip()
  return text or None


def load_ide_auth(state_db, grok_email=""):
  if not state_db.is_file():
    return None

  try:
    uri = state_db.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
  except sqlite3.Error:
    return None

  try:
    conn.execute("PRAGMA query_only = ON")
    access = read_item(conn, "cursorAuth/accessToken")
    refresh = read_item(conn, "cursorAuth/refreshToken")
    membership = read_item(conn, "cursorAuth/stripeMembershipType")
    signup = read_item(conn, "cursorAuth/cachedSignUpType")
    cached_email = read_item(conn, "cursorAuth/cachedEmail")
  except sqlite3.Error:
    return None
  finally:
    conn.close()

  if not access:
    return None

  ok, provider, sub, payload = accept_cursor_x_jwt(access)
  email = cached_email or ""
  if not cursor_session_ok(payload, provider, email, grok_email):
    return None
  login_provider = provider if ok else "grok-matched"

  return {
    "source": "ide",
    "token": str(access),
    "refresh_token": str(refresh or ""),
    "auth_path": None,
    "auth_data": None,
    "login_provider": login_provider,
    "subject": sub,
    "membership": membership or "",
    "email": email,
  }


def pick_x_credentials(auth_path, state_db, grok_email=""):
  cli = load_cli_auth(auth_path, grok_email=grok_email)
  ide = load_ide_auth(state_db, grok_email=grok_email)
  if cli and ide:
    if cli.get("subject") and ide.get("subject") and cli["subject"] != ide["subject"]:
      return ide
    if not cli.get("membership") and ide.get("membership"):
      cli["membership"] = ide["membership"]
    if not cli.get("email") and ide.get("email"):
      cli["email"] = ide["email"]
    return cli
  return cli or ide


def access_needs_refresh(token, skew_sec=REFRESH_SKEW_SEC):
  payload = decode_jwt(token)
  if not payload:
    return True
  exp = payload.get("exp")
  if exp is None or exp == "":
    return False
  try:
    exp_dt = datetime.fromtimestamp(int(float(exp)), timezone.utc)
  except Exception:
    return True
  return exp_dt <= datetime.now(timezone.utc) + timedelta(seconds=skew_sec)


def access_is_expired(token):
  payload = decode_jwt(token)
  if not payload:
    return True
  exp = payload.get("exp")
  if exp is None or exp == "":
    return False
  try:
    exp_dt = datetime.fromtimestamp(int(float(exp)), timezone.utc)
  except Exception:
    return True
  return exp_dt <= datetime.now(timezone.utc)


def save_cli_auth(creds):
  """Atomically write refreshed tokens back to CLI auth.json (mode 0600)."""
  if not creds or creds.get("source") != "cli":
    return
  path = creds.get("auth_path")
  if path is None:
    return
  data = creds.get("auth_data")
  if not isinstance(data, dict):
    data = {}
  else:
    data = dict(data)
  data["accessToken"] = creds["token"]
  if creds.get("refresh_token"):
    data["refreshToken"] = creds["refresh_token"]
  creds["auth_data"] = data

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
    sys.stderr.write(f"grokbar-omarchy: could not write cursor auth.json: {exc}\n")


def refresh_token(creds):
  refresh = str(creds.get("refresh_token") or "").strip()
  if not refresh:
    return False, "no_refresh"

  body = json.dumps({
    "grant_type": "refresh_token",
    "client_id": CLIENT_ID,
    "refresh_token": refresh,
  }).encode("utf-8")
  req = urllib.request.Request(
    TOKEN_URL,
    data=body,
    method="POST",
    headers={
      "Content-Type": "application/json",
      "Accept": "application/json",
      "User-Agent": USER_AGENT,
    },
  )
  try:
    with urllib.request.urlopen(req, timeout=20) as resp:
      payload = json.loads(resp.read().decode("utf-8", errors="replace"))
  except urllib.error.HTTPError as exc:
    if exc.code in (400, 401, 403):
      return False, "auth"
    return False, "http"
  except Exception:
    return False, "net"

  if not isinstance(payload, dict):
    return False, "parse"
  if payload.get("shouldLogout") is True:
    return False, "logout"

  access = payload.get("access_token") or payload.get("accessToken") or ""
  if not access:
    return False, "parse"

  ok, provider, sub, decoded = accept_cursor_x_jwt(access)
  if ok:
    login_provider = provider
  elif decoded and creds.get("login_provider") in {"grok-matched", "x-linked"}:
    old_sub = str(creds.get("subject") or "")
    if old_sub and sub and old_sub != sub:
      return False, "logout"
    login_provider = "grok-matched"
  else:
    return False, "logout"

  creds["token"] = str(access)
  creds["login_provider"] = login_provider
  creds["subject"] = sub
  new_refresh = payload.get("refresh_token") or payload.get("refreshToken")
  if new_refresh:
    creds["refresh_token"] = str(new_refresh)
  save_cli_auth(creds)
  return True, None


def ensure_token(creds):
  if not access_needs_refresh(creds.get("token")):
    return True, None
  ok, reason = refresh_token(creds)
  if ok:
    return True, None
  if reason == "logout" or access_is_expired(creds.get("token")):
    return False, reason or "auth"
  # Access JWT still valid enough to try the usage call.
  return True, None


def http_post_json(url, token, body, timeout=20):
  headers = {
    "Content-Type": "application/json",
    "Connect-Protocol-Version": "1",
    "User-Agent": USER_AGENT,
  }
  if token:
    headers["Authorization"] = f"Bearer {token}"
  req = urllib.request.Request(
    url,
    data=json.dumps(body).encode("utf-8"),
    method="POST",
    headers=headers,
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      raw = resp.read().decode("utf-8", errors="replace")
      status = getattr(resp, "status", 200)
  except urllib.error.HTTPError as exc:
    status = exc.code
    try:
      exc.read()
    except Exception:
      pass
    if status in (401, 403):
      return None, "auth", None
    return None, "http", f"Usage API returned HTTP {status}"
  except Exception as exc:
    return None, "net", str(exc)

  if status < 200 or status >= 300:
    return None, "http", f"Usage API returned HTTP {status}"
  try:
    parsed = json.loads(raw)
  except Exception:
    return None, "parse", "Could not parse usage response."
  return parsed, None, None


def fetch_period_usage(creds):
  return http_post_json(
    f"{API_BASE}/GetCurrentPeriodUsage",
    creds["token"],
    {},
    timeout=20,
  )


def fetch_plan_name(creds):
  payload, kind, _err = http_post_json(
    f"{API_BASE}/GetPlanInfo",
    creds["token"],
    {},
    timeout=15,
  )
  if kind is not None or not isinstance(payload, dict):
    return ""
  info = payload.get("planInfo")
  if not isinstance(info, dict):
    return ""
  return str(info.get("planName") or "").strip()


def fetch_account_email(creds):
  payload, kind, _err = http_post_json(
    f"{API_BASE}/GetMe",
    creds["token"],
    {},
    timeout=15,
  )
  if kind is not None or not isinstance(payload, dict):
    return ""
  return str(payload.get("email") or "").strip()


def with_auth_retry(creds, fetch_fn):
  result, kind, err = fetch_fn(creds)
  if kind != "auth":
    return result, kind, err
  ok, _reason = refresh_token(creds)
  if not ok:
    return None, "auth", None
  return fetch_fn(creds)


def parse_when(value):
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    number = float(value)
    if not math.isfinite(number):
      return None
    seconds = number / 1000.0 if abs(number) >= 1e11 else number
    try:
      return datetime.fromtimestamp(seconds, timezone.utc)
    except (OverflowError, OSError, ValueError):
      return None

  text = str(value).strip()
  if not text:
    return None
  if text.isdigit() or (text[0] in "+-" and text[1:].isdigit()):
    return parse_when(float(text))
  try:
    as_float = float(text)
  except (TypeError, ValueError):
    as_float = None
  if as_float is not None and math.isfinite(as_float):
    # Numeric strings only — ISO dates fail float() or are not plain numbers.
    stripped = text[1:] if text[0] in "+-" else text
    if stripped.replace(".", "", 1).isdigit():
      return parse_when(as_float)
  return parse_iso(text)


def add_months(dt, months):
  month_index = dt.month - 1 + months
  year = dt.year + month_index // 12
  month = month_index % 12 + 1
  last = calendar.monthrange(year, month)[1]
  return dt.replace(year=year, month=month, day=min(dt.day, last))


def format_tier(value):
  text = str(value or "").strip()
  if not text:
    return ""
  if any(ch.isupper() for ch in text) and " " in text:
    return text
  if any(ch.isupper() for ch in text) and "_" not in text:
    return text
  return " ".join(part.capitalize() for part in text.replace("_", " ").split())


def percent_from_plan(plan, key):
  if key not in plan or plan.get(key) is None:
    return 0.0
  try:
    number = float(plan.get(key))
  except (TypeError, ValueError):
    return 0.0
  if not math.isfinite(number):
    return 0.0
  return number / 100.0


def cents_or_none(*values):
  for value in values:
    if value is None or value == "":
      continue
    try:
      number = float(value)
    except (TypeError, ValueError):
      continue
    if not math.isfinite(number):
      continue
    return int(round(number))
  return None


def build_result(creds, payload, tier_label=""):
  if not isinstance(payload, dict):
    return x_error_result(
      creds,
      "Cursor limits unavailable",
      "Usage response was not a JSON object.",
    )

  plan = payload.get("planUsage")
  if not isinstance(plan, dict):
    return x_error_result(
      creds,
      "Cursor limits unavailable",
      "Usage response did not include plan usage.",
    )

  reset_dt = parse_when(payload.get("billingCycleEnd"))
  start_dt = parse_when(payload.get("billingCycleStart"))
  if start_dt is None and reset_dt is not None:
    start_dt = add_months(reset_dt, -1)

  reset_iso = to_iso(reset_dt)
  start_iso = to_iso(start_dt)

  membership = (
    tier_label
    or creds.get("membership")
    or payload.get("membershipType")
    or ""
  )

  out = empty_result(
    rateLimitPercent=percent_from_plan(plan, "autoPercentUsed"),
    rateLimitLabel="Cursor Models",
    rateLimitResetAt=reset_iso,
    rateLimitPeriodStart=start_iso,
    secondaryRateLimitPercent=percent_from_plan(plan, "apiPercentUsed"),
    secondaryRateLimitLabel="Other Models",
    secondaryRateLimitResetAt=reset_iso,
    tierLabel=plain_text(format_tier(membership), max_len=80),
    accountEmail=plain_text(creds.get("account_email"), max_len=254),
    xLoginFound=True,
  )

  included = cents_or_none(plan.get("includedSpend"), payload.get("includedSpend"))
  spend_limit = cents_or_none(
    plan.get("spendLimit"),
    plan.get("limit"),
    payload.get("spendLimit"),
  )
  spend_remaining = cents_or_none(
    plan.get("spendRemaining"),
    plan.get("remaining"),
    payload.get("spendRemaining"),
  )
  if included is not None:
    out["includedSpend"] = included
  if spend_limit is not None:
    out["spendLimit"] = spend_limit
  if spend_remaining is not None:
    out["spendRemaining"] = spend_remaining
  return out


def main(argv=None):
  parser = argparse.ArgumentParser(description="Scan Cursor period-pool usage (X-login only)")
  parser.add_argument(
    "--auth",
    default=os.environ.get("CURSOR_AUTH_PATH", str(DEFAULT_AUTH)),
    help="Path to Cursor CLI auth.json (default: ~/.config/cursor/auth.json)",
  )
  parser.add_argument(
    "--state-db",
    default=os.environ.get("CURSOR_STATE_DB", str(DEFAULT_STATE_DB)),
    help="Path to Cursor state.vscdb (read-only)",
  )
  parser.add_argument(
    "--grok-auth",
    default=os.environ.get("GROK_AUTH_PATH", str(DEFAULT_GROK_AUTH)),
    help="Path to Grok auth.json used to match the Grok account",
  )
  parser.add_argument(
    "--probe",
    action="store_true",
    help="Print ready/absent if an X-login token exists (no usage API)",
  )
  args = parser.parse_args(argv)

  auth_path = expand_path(args.auth, DEFAULT_AUTH)
  state_db = expand_path(args.state_db, DEFAULT_STATE_DB)
  grok_auth = expand_path(args.grok_auth, DEFAULT_GROK_AUTH)
  grok_email = load_grok_email(grok_auth)
  creds = pick_x_credentials(auth_path, state_db, grok_email=grok_email)

  if args.probe:
    print("ready" if creds else "absent")
    return 0

  if not creds:
    return emit(empty_result())

  # Defense in depth: never call Cursor APIs with an unrelated account.
  allowed = set(X_PROVIDERS)
  allowed.add("grok-matched")
  if creds.get("login_provider") not in allowed:
    return emit(empty_result())

  ok, _reason = ensure_token(creds)
  if not ok:
    return emit(expired_x_result(creds))
  if creds.get("login_provider") not in allowed:
    return emit(empty_result())

  payload, kind, err = with_auth_retry(creds, fetch_period_usage)
  if kind == "auth":
    return emit(expired_x_result(creds))
  if payload is None:
    return emit(x_error_result(
      creds,
      "Cursor limits unavailable",
      err or "Could not load Cursor period usage.",
    ))

  # Plan name and account email are best-effort; period usage still stands.
  tier_label = fetch_plan_name(creds)
  creds["account_email"] = fetch_account_email(creds)

  return emit(build_result(creds, payload, tier_label=tier_label))


if __name__ == "__main__":
  sys.exit(main())
