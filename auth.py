#!/usr/bin/env python3
"""Run the OAuth flow for one Gmail account and store its token.

The only interactive script here: it opens a browser once, then writes
tokens/<account>.json (mode 600).
"""

from __future__ import annotations

import argparse
import sys

from gmail import (
    SCOPES,
    Failure,
    client_config,
    die,
    emit,
    load_accounts,
    token_path,
    valid_account,
    write_token,
)


def authorize(account: str) -> dict:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
    try:
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    except Exception as exc:  # noqa: BLE001 - reported as JSON
        raise Failure(f"OAuth flow failed for '{account}': {exc}") from exc

    if not creds.refresh_token:
        raise Failure(
            f"Google returned no refresh token for '{account}'.",
            hint="Revoke this app's access at myaccount.google.com/permissions, "
            "then run auth again.",
        )

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        email = service.users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception as exc:  # noqa: BLE001 - reported as JSON
        raise Failure(f"Authorized, but the Gmail profile lookup failed: {exc}") from exc

    write_token(account, creds)
    return {"account": account, "email": email, "status": "ok"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="auth.py", description="Authorize one Gmail account."
    )
    parser.add_argument(
        "account", help="Short name from accounts.json, or 'all' for every account."
    )
    args = parser.parse_args(argv)

    try:
        known = load_accounts()
        if args.account == "all":
            targets = [name for name in known if not token_path(name).exists()]
            if not targets:
                emit({"accounts": [], "status": "ok", "note": "every account already has a token"})
                return
        else:
            account = valid_account(args.account)
            if account not in known:
                raise Failure(
                    f"Account '{account}' is not listed in accounts.json.",
                    known=known,
                )
            targets = [account]

        client_config()  # fail before opening a browser if .env is not ready

        results = []
        for name in targets:
            print(f"Authorizing {name} - a browser window will open.", file=sys.stderr)
            results.append(authorize(name))
            print(f"Token written to {token_path(name)}", file=sys.stderr)
    except Failure as exc:
        die(exc)

    emit(results[0] if len(results) == 1 and args.account != "all" else {"accounts": results})


if __name__ == "__main__":
    main()
