# Chabad-Atwater-Village

## Multi-Account Gmail Access

CLI scripts that read and draft email across several Gmail accounts, using the
Gmail API with one OAuth client and a separate token file per account.

Every script prints JSON to stdout. Errors print JSON to stderr and exit
non-zero. `auth.py` is the only script that opens a browser.

### Scopes

Only these two:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.compose`

There is no send capability. Drafts are created for a human to review and send.

### Install

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Google Cloud Console setup (do this once, by hand)

1. Create a project at https://console.cloud.google.com/
2. Enable the **Gmail API** (APIs & Services → Library → Gmail API → Enable).
3. Configure the **OAuth consent screen** as **External**.
4. Add every Gmail address you plan to use as a **Test User**.
5. Create credentials → **OAuth client ID** → application type **Desktop app**.
6. Copy the client ID and client secret into `.env` (see below).

### Configure

`.env` in the project root (gitignored, never commit it):

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

`accounts.json` lists the short names you will refer to accounts by:

```
["personal", "work"]
```

### Authorize each account

```
python auth.py personal
python auth.py work
```

Each run opens a browser once, then writes `tokens/<account>.json` with mode
600. Sign in as the matching Gmail address — the short name is just a local
label, so pick the right account in the browser.

### Commands

```
python gmail.py list --account <account> [--query "is:unread"] [--max 25]
python gmail.py list --account all --query "is:unread" --max 5
python gmail.py read --account <account> --id <message-id>
python gmail.py draft --account <account> --to <addr> --subject <str> \
                      --body-file <path> [--reply-to <message-id>]
```

`--account all` fans out over every entry in `accounts.json` and prints
`{"accounts": [{"account": ..., "messages": [...]}, ...]}`. An account that
fails carries its own `error` and `action` in that list; if every account
fails, the error goes to stderr instead and the exit code is non-zero.

Draft bodies come from a file rather than a flag so newlines and long text
survive shell quoting.

### Tokens

Refreshed automatically and written back when they expire. If a token is
missing or revoked, the command exits non-zero with the exact `auth.py`
command to run — it never re-prompts on its own.

### Pitfall: 7-day refresh tokens while "Testing"

While the OAuth app's publishing status is **Testing**, Google expires refresh
tokens after 7 days and every account needs re-authorization. Once the setup
works, either publish the app (consent screen → Publish app) or, with a
Workspace account, recreate the OAuth client as **Internal**.
