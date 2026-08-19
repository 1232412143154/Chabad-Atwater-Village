#!/usr/bin/env python3
"""Report setup state and the single next thing to do.

Prints JSON to stdout. Never contacts Google, never prints secret values.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from gmail import (
    ACCOUNTS_FILE,
    ENV_FILE,
    ROOT,
    TOKENS_DIR,
    Failure,
    find_client_file,
    load_env,
    token_path,
)


def redact(value: str) -> str:
    """Enough to recognise a value, not enough to use it."""
    if not value:
        return ""
    return f"{value[:6]}..." if len(value) > 10 else "set"


def check_dependencies() -> tuple[bool, dict]:
    missing = []
    for module, package in (
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("googleapiclient", "google-api-python-client"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return not missing, {"ok": not missing, "missing": missing}


def check_credentials() -> tuple[bool, dict]:
    env = load_env()
    env_id = env.get("GOOGLE_CLIENT_ID", "")
    env_secret = env.get("GOOGLE_CLIENT_SECRET", "")
    if env_id and env_secret:
        return True, {
            "ok": True,
            "source": str(ENV_FILE.name),
            "client_id": redact(env_id),
        }
    client_file = find_client_file()
    if client_file:
        try:
            from gmail import credentials_from_file

            client_id, _ = credentials_from_file(client_file)
        except Failure as exc:
            return False, {"ok": False, "source": client_file.name, "problem": exc.message}
        return True, {
            "ok": True,
            "source": client_file.name,
            "client_id": redact(client_id),
        }
    return False, {
        "ok": False,
        "problem": "no OAuth client credentials found",
        "looked_for": [
            str(ENV_FILE.name),
            "credentials.json",
            "client_secret*.json",
        ],
    }


def check_accounts() -> tuple[bool, dict, list[str]]:
    if not ACCOUNTS_FILE.exists():
        return False, {"ok": False, "problem": "accounts.json is missing"}, []
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, {"ok": False, "problem": f"accounts.json is not valid JSON: {exc}"}, []
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        return False, {"ok": False, "problem": "accounts.json must be a list of strings"}, []
    if not data:
        return False, {"ok": False, "problem": "accounts.json is empty"}, []
    placeholder = data == ["personal", "work"]
    return True, {"ok": True, "accounts": data, "placeholder": placeholder}, data


def check_tokens(accounts: list[str]) -> tuple[bool, dict]:
    present, missing, insecure = [], [], []
    for account in accounts:
        path = token_path(account)
        if not path.exists():
            missing.append(account)
            continue
        present.append(account)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            insecure.append({"account": account, "mode": oct(mode)})
    detail = {"ok": not missing, "authorized": present, "missing": missing}
    if insecure:
        detail["insecure_permissions"] = insecure
    return not missing, detail


def main() -> None:
    checks: dict[str, dict] = {}

    deps_ok, checks["dependencies"] = check_dependencies()
    creds_ok, checks["oauth_client"] = check_credentials()
    accounts_ok, checks["accounts"], accounts = check_accounts()
    if accounts_ok:
        tokens_ok, checks["tokens"] = check_tokens(accounts)
    else:
        tokens_ok, checks["tokens"] = False, {"ok": False, "problem": "accounts unknown"}

    if not deps_ok:
        packages = " ".join(checks["dependencies"]["missing"])
        next_action = f"pip install {packages}"
    elif not accounts_ok:
        next_action = "Fix accounts.json: a JSON list of short names, e.g. [\"info\",\"rabbi\"]"
    elif checks["accounts"].get("placeholder"):
        next_action = (
            "Edit accounts.json - it still holds the placeholder names "
            '["personal","work"]'
        )
    elif not creds_ok:
        next_action = (
            "Add OAuth client credentials: drop the client-secret JSON from the "
            "Cloud Console into this folder, or fill in .env"
        )
    elif not tokens_ok:
        missing = checks["tokens"]["missing"]
        next_action = f"python auth.py {missing[0]}" if len(missing) == 1 else "python auth.py all"
    else:
        next_action = 'python gmail.py list --account all --query "is:unread" --max 5'

    ready = deps_ok and creds_ok and accounts_ok and tokens_ok
    json.dump(
        {"ready": ready, "checks": checks, "next_action": next_action},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
