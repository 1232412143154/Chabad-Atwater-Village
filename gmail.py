#!/usr/bin/env python3
"""Read and draft Gmail across several accounts, one OAuth token per account.

Prints JSON to stdout. Errors go to stderr as JSON with a non-zero exit.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ACCOUNTS_FILE = ROOT / "accounts.json"
TOKENS_DIR = ROOT / "tokens"

ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class Failure(Exception):
    """An error worth reporting to the user as JSON on stderr."""

    def __init__(self, message: str, **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra

    def payload(self) -> dict:
        return {"error": self.message, **self.extra}


def die(exc: Failure) -> "NoReturn":  # noqa: F821 - runtime-only annotation
    json.dump(exc.payload(), sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
    raise SystemExit(1)


def emit(payload: object) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


# --- configuration -----------------------------------------------------------


def load_env() -> dict[str, str]:
    """Read KEY=VALUE pairs from .env, letting the real environment win."""
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def find_client_file() -> Path | None:
    """Locate a client-secret JSON as downloaded from the Cloud Console."""
    override = os.environ.get("GOOGLE_CLIENT_SECRETS")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    named = ROOT / "credentials.json"
    if named.is_file():
        return named
    matches = sorted(ROOT.glob("client_secret*.json"))
    return matches[0] if matches else None


def credentials_from_file(path: Path) -> tuple[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Failure(f"Could not read {path.name}: {exc}") from exc
    section = data.get("installed") or data.get("web") or {}
    client_id = section.get("client_id", "")
    client_secret = section.get("client_secret", "")
    if not client_id or not client_secret:
        raise Failure(
            f"{path.name} has no client_id/client_secret.",
            hint="Download the JSON for a Desktop app OAuth client.",
        )
    return client_id, client_secret


def client_credentials() -> tuple[str, str]:
    """Prefer .env; otherwise fall back to a downloaded client-secret JSON."""
    env = load_env()
    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")
    if client_id and client_secret:
        return client_id, client_secret

    client_file = find_client_file()
    if client_file:
        return credentials_from_file(client_file)

    raise Failure(
        "No OAuth client credentials found.",
        hint=(
            "Drop the client-secret JSON you downloaded from the Cloud Console "
            "next to gmail.py (credentials.json or client_secret*.json), or put "
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env."
        ),
    )


def client_config() -> dict:
    client_id, client_secret = client_credentials()
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def valid_account(account: str) -> str:
    if not ACCOUNT_RE.match(account):
        raise Failure(
            "Invalid account name.",
            account=account,
            hint="Use letters, digits, dot, dash or underscore only.",
        )
    return account


def token_path(account: str) -> Path:
    return TOKENS_DIR / f"{valid_account(account)}.json"


def load_accounts() -> list[str]:
    if not ACCOUNTS_FILE.exists():
        raise Failure(
            "accounts.json not found.",
            hint='Create it with a list of short names, e.g. ["personal","work"].',
        )
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Failure(f"accounts.json is not valid JSON: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise Failure("accounts.json must be a JSON list of strings.")
    if not data:
        raise Failure(
            "accounts.json is empty.",
            hint='Add at least one short name, e.g. ["personal"].',
        )
    return [valid_account(name) for name in data]


# --- credentials -------------------------------------------------------------


def write_token(account: str, creds) -> None:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(TOKENS_DIR, 0o700)
    path = token_path(account)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def load_credentials(account: str):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path(account)
    reauth = f"python auth.py {account}"
    if not path.exists():
        raise Failure(
            f"No token for account '{account}'.",
            account=account,
            action=reauth,
        )
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, json.JSONDecodeError) as exc:
        raise Failure(
            f"Token for account '{account}' is unreadable: {exc}",
            account=account,
            action=reauth,
        ) from exc

    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise Failure(
            f"Token for account '{account}' cannot be refreshed.",
            account=account,
            action=reauth,
        )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise Failure(
            f"Token for account '{account}' was revoked or has expired: {exc}",
            account=account,
            action=reauth,
        ) from exc
    write_token(account, creds)
    return creds


def service_for(account: str):
    from googleapiclient.discovery import build

    creds = load_credentials(account)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def api_failure(account: str, exc: Exception) -> Failure:
    from googleapiclient.errors import HttpError

    if isinstance(exc, HttpError):
        status = getattr(getattr(exc, "resp", None), "status", None)
        detail = getattr(exc, "reason", None) or str(exc)
        if status in (401, 403):
            return Failure(
                f"Gmail API rejected the request for '{account}': {detail}",
                account=account,
                action=f"python auth.py {account}",
            )
        return Failure(
            f"Gmail API error for '{account}': {detail}",
            account=account,
            status=status,
        )
    return Failure(f"Gmail request failed for '{account}': {exc}", account=account)


# --- message helpers ---------------------------------------------------------


def header(payload: dict, name: str) -> str:
    wanted = name.lower()
    for item in payload.get("headers", []) or []:
        if item.get("name", "").lower() == wanted:
            return item.get("value", "")
    return ""


class _TextExtractor(HTMLParser):
    """Collect visible text, turning block tags into line or paragraph breaks."""

    SKIP = {"script", "style", "head", "title"}
    LINE = {"br", "li", "tr", "dt", "dd"}
    PARAGRAPH = {
        "p", "div", "table", "blockquote", "ul", "ol", "pre",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def _break(self, tag: str) -> None:
        if tag in self.PARAGRAPH:
            self.parts.append("\n\n")
        elif tag in self.LINE:
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skipping += 1
        else:
            self._break(tag)

    def handle_startendtag(self, tag, attrs):
        self._break(tag)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self.PARAGRAPH:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode_part(part: dict) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def extract_body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        subparts = part.get("parts") or []
        if subparts:
            for sub in subparts:
                walk(sub)
            return
        if part.get("filename"):
            return
        if mime == "text/plain":
            plain.append(decode_part(part))
        elif mime == "text/html":
            html.append(decode_part(part))

    walk(payload)
    if any(chunk.strip() for chunk in plain):
        return "\n".join(plain).strip()
    if any(chunk.strip() for chunk in html):
        return html_to_text("\n".join(html))
    return ""


# --- commands ----------------------------------------------------------------


def list_one(account: str, query: str | None, maximum: int) -> dict:
    try:
        service = service_for(account)
        users = service.users()
        listing = users.messages().list(
            userId="me",
            q=query or None,
            maxResults=maximum,
        ).execute()
        messages = []
        for stub in listing.get("messages", []) or []:
            detail = users.messages().get(
                userId="me",
                id=stub["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            payload = detail.get("payload", {})
            messages.append(
                {
                    "id": detail.get("id", stub["id"]),
                    "from": header(payload, "From"),
                    "subject": header(payload, "Subject"),
                    "date": header(payload, "Date"),
                    "snippet": detail.get("snippet", ""),
                }
            )
    except Failure:
        raise
    except Exception as exc:  # noqa: BLE001 - reported as JSON
        raise api_failure(account, exc) from exc
    return {"account": account, "messages": messages}


def cmd_list(args: argparse.Namespace) -> None:
    if args.max < 1:
        raise Failure("--max must be at least 1.")
    if args.account == "all":
        results = []
        problems = []
        for account in load_accounts():
            try:
                results.append(list_one(account, args.query, args.max))
            except Failure as exc:
                problems.append(exc.payload())
                results.append({"account": account, "messages": [], **exc.payload()})
        if problems and len(problems) == len(results):
            raise Failure("Every account failed.", accounts=problems)
        emit({"accounts": results})
        return
    emit(list_one(args.account, args.query, args.max))


def cmd_read(args: argparse.Namespace) -> None:
    if args.account == "all":
        raise Failure("read needs one account, not 'all'.")
    try:
        message = service_for(args.account).users().messages().get(
            userId="me", id=args.id, format="full"
        ).execute()
    except Failure:
        raise
    except Exception as exc:  # noqa: BLE001 - reported as JSON
        raise api_failure(args.account, exc) from exc
    payload = message.get("payload", {})
    emit(
        {
            "id": message.get("id", args.id),
            "from": header(payload, "From"),
            "to": header(payload, "To"),
            "subject": header(payload, "Subject"),
            "date": header(payload, "Date"),
            "body": extract_body(payload),
        }
    )


def cmd_draft(args: argparse.Namespace) -> None:
    if args.account == "all":
        raise Failure("draft needs one account, not 'all'.")
    body_file = Path(args.body_file)
    if not body_file.is_file():
        raise Failure(f"Body file not found: {body_file}")
    body = body_file.read_text(encoding="utf-8")

    try:
        service = service_for(args.account)
        users = service.users()
        profile = users.getProfile(userId="me").execute()

        message = EmailMessage()
        message["To"] = args.to
        message["From"] = profile.get("emailAddress", "me")
        message["Subject"] = args.subject
        message.set_content(body)

        draft_body: dict = {}
        if args.reply_to:
            original = users.messages().get(
                userId="me",
                id=args.reply_to,
                format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject"],
            ).execute()
            original_payload = original.get("payload", {})
            parent_id = header(original_payload, "Message-ID")
            if parent_id:
                message["In-Reply-To"] = parent_id
                references = header(original_payload, "References")
                message["References"] = (
                    f"{references} {parent_id}".strip() if references else parent_id
                )
            thread_id = original.get("threadId")
            if thread_id:
                draft_body["threadId"] = thread_id

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        draft_body["raw"] = raw
        draft = users.drafts().create(userId="me", body={"message": draft_body}).execute()
    except Failure:
        raise
    except Exception as exc:  # noqa: BLE001 - reported as JSON
        raise api_failure(args.account, exc) from exc

    emit({"draft_id": draft.get("id", ""), "status": "created"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail.py", description="Read and draft Gmail across several accounts."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="List messages.")
    listing.add_argument("--account", required=True, help="Short name, or 'all'.")
    listing.add_argument("--query", default=None, help='Gmail search, e.g. "is:unread".')
    listing.add_argument("--max", type=int, default=25, help="Max messages (default 25).")
    listing.set_defaults(func=cmd_list)

    read = sub.add_parser("read", help="Read one message as plain text.")
    read.add_argument("--account", required=True)
    read.add_argument("--id", required=True, help="Gmail message id.")
    read.set_defaults(func=cmd_read)

    draft = sub.add_parser("draft", help="Create a draft.")
    draft.add_argument("--account", required=True)
    draft.add_argument("--to", required=True)
    draft.add_argument("--subject", required=True)
    draft.add_argument("--body-file", required=True, dest="body_file")
    draft.add_argument("--reply-to", default=None, dest="reply_to")
    draft.set_defaults(func=cmd_draft)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except Failure as exc:
        die(exc)


if __name__ == "__main__":
    main()
