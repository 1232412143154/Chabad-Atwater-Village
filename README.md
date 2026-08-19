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

There is no API for creating OAuth clients, so these steps are browser-only.

1. Create a project at https://console.cloud.google.com/ — note its name, and
   check the top-left project picker before every later step. The console
   switches projects silently, and the project name is not in the URL.
2. Enable the **Gmail API** (search "Gmail API" → Enable).
3. Configure the consent screen (**APIs & Services → OAuth consent screen**,
   newer consoles call this **Google Auth Platform**).
   - **Internal** audience, if offered, means a Google Workspace domain: no
     token expiry and no test-user list, but *only* accounts inside that domain
     can be authorized.
   - **External** is required as soon as one personal `@gmail.com` is involved.
     Then **publish the app** (Audience → Publish app) so the publishing status
     reads *In production*. Unverified is fine — you click past one "Google
     hasn't verified this app" warning per account. Leaving it in *Testing*
     is what causes refresh tokens to die after 7 days.
4. **Credentials → + Create Credentials → OAuth client ID**, application type
   **Desktop app**. Not a service account — a service account cannot read a
   personal Gmail inbox at all.
5. **Download JSON** from the dialog.

If the **Application type** dropdown is missing, the selected project has no
consent screen configured — you are in the wrong project.

### Configure

Either drop the downloaded file into the project root — `credentials.json` or
any `client_secret*.json` is picked up automatically, and both are gitignored —
or put the two values in `.env`:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

`.env` wins if both are present. Set `GOOGLE_CLIENT_SECRETS=/path/to/file.json`
to point somewhere else entirely.

`accounts.json` lists the short names you refer to accounts by. The name is a
local label only — what matters is which Google account you sign into during
`auth.py`:

```
["info", "rabbi", "somename"]
```

### Where to run this

`auth.py` opens a browser, so authorization has to happen on a machine with
one. Remote or headless sessions can run `list`, `read` and `draft` against
tokens that already exist, but cannot create them.

### Check the setup

```
python doctor.py
```

Reports what is configured and prints the single next thing to do. Contacts
nothing and prints no secret values. Run it whenever something looks wrong.

### Authorize each account

```
python auth.py info          # one account
python auth.py all           # every account still missing a token
```

Each run opens a browser once, then writes `tokens/<account>.json` with mode
600. Sign in as the matching Gmail address — the short name is just a local
label, so pick the right account in the browser. `all` skips accounts that
already have a token, so it is safe to re-run.

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

An **External** app whose publishing status is **Testing** has its refresh
tokens expired by Google after 7 days, forcing re-authorization of every
account. Publishing the app (Audience → Publish app) removes that limit
without needing verification. **Internal** apps are never subject to it.

If you are stuck re-authorizing weekly, check the publishing status first —
that is almost always the cause.
