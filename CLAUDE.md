# Multi-Account Gmail Access

Build a small set of CLI scripts that let Claude Code read and draft email
across several Gmail accounts, using the Gmail API directly with per-account
OAuth tokens.

Do NOT use the native Claude email connector. It authenticates one account
at a time, which is the limitation this project exists to work around.

## Constraints

- Python 3.11+. Dependencies: `google-auth-oauthlib`, `google-api-python-client`.
- Every script is non-interactive except `auth.py`, which opens a browser once.
- Every script prints JSON to stdout and nothing else. Errors go to stderr with
  a non-zero exit code. No progress chatter, no banners, no emoji.
- Never print full message bodies, tokens, client IDs, or client secrets to
  stdout unless the command's documented purpose is to return that content.
- One OAuth client (one ID/secret pair) is shared by all accounts. Each account
  gets its own token file.

## Scopes

Request exactly these, no more:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.compose`

Do not add `gmail.send` or `mail.google.com`. Drafts are created and reviewed
by a human before sending. If I later ask for send capability, treat that as a
separate change and confirm before widening scopes.

## Layout

```
.env                 # GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
.gitignore           # must contain .env and tokens/
accounts.json        # list of account short names, e.g. ["personal","work"]
tokens/              # <account>.json, one per account, created by auth.py
auth.py
gmail.py
```

Create `.gitignore` with `.env` and `tokens/` in it BEFORE creating any other
file, and do not run `git init` unless I ask.

## Commands

```
python auth.py <account>
    Runs the OAuth flow for one account. Writes tokens/<account>.json.
    Prints {"account": "...", "email": "...", "status": "ok"}.

python gmail.py list --account <account> [--query "is:unread"] [--max 25]
    Prints {"account": "...", "messages": [{id, from, subject, date, snippet}]}.
    --account all fans out across every entry in accounts.json.

python gmail.py read --account <account> --id <message-id>
    Prints {"id", "from", "to", "subject", "date", "body"} with body as plain
    text. Strip HTML if the message is HTML-only.

python gmail.py draft --account <account> --to <addr> --subject <str> \
                      --body-file <path> [--reply-to <message-id>]
    Creates a draft. Prints {"draft_id": "...", "status": "created"}.
    Body comes from a file, not a flag, so newlines survive.
```

Use `--body-file` rather than inline body text — long or multi-line bodies get
mangled through shell quoting.

## Token handling

- Refresh tokens automatically when expired; write the refreshed token back.
- If a token is missing or revoked, exit non-zero with a JSON error telling me
  to run `python auth.py <account>`. Do not silently re-prompt.
- Token files are chmod 600.

## Known pitfall to warn me about

While the Google Cloud OAuth app's publishing status is "Testing", refresh
tokens expire after 7 days and every account needs re-authentication. After
setup works, remind me to either publish the app or, if I have Workspace,
recreate the OAuth client as Internal.

## Setup order

1. Write `.gitignore`, then the scripts, then `requirements.txt`.
2. Stop and tell me to do the Google Cloud Console steps: create project,
   enable Gmail API, configure OAuth consent screen (External), create a
   Desktop App OAuth client, add every Gmail address as a Test User.
3. Tell me exactly what to paste into `.env`.
4. When I confirm `.env` is filled in, walk me through `auth.py` per account.
5. Verify with `gmail.py list --account all --query "is:unread" --max 5`.

Do not attempt step 2 yourself and do not guess at credentials.

## Behavior in normal chat

When I ask about my email — "any unread?", "summarize my inbox", "draft a reply
to X" — use these scripts without being told. Default to `--account all` for
reads. Always show me a draft before I send it; you have no send capability.
