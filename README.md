# MailLaunch

MailLaunch is a local Python CLI for personalized cold-email campaigns through Gmail API or Microsoft Graph. It stores campaign state in SQLite, stores OAuth tokens in the OS keychain, enforces a daily send limit, retries transient failures, and can resume interrupted campaigns.

## Setup

Requires Python 3.10 or newer.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Copy `maillaunch.config.yaml` and adjust non-sensitive defaults. Put provider client IDs and secrets in `.env`:

```dotenv
GMAIL_CLIENT_ID=your-client-id.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=your-client-secret
MICROSOFT_CLIENT_ID=your-public-client-id
```

The `.env` file is ignored by Git. Tokens are stored with `keyring`, never in YAML, SQLite, logs, or normal error output.

## Provider setup

For Gmail, create a Google OAuth desktop application and enable the Gmail API. The application needs the `https://www.googleapis.com/auth/gmail.send` scope.

For Microsoft, register a public/desktop Entra application with delegated `User.Read` and `Mail.Send` permissions. No client secret is required.

Authenticate once:

```bash
python src/main.py auth gmail
python src/main.py auth microsoft
```

After installing the package, the equivalent command is `maillaunch ...`.

## Sending a campaign

CSV files must contain a header with a column containing `email` or `mail`. All columns can be used in templates.

```csv
name,email,company
John,john@example.com,ABC Corp
Sarah,sarah@example.com,XYZ Inc
```

```bash
python src/main.py send \
	--provider gmail \
	--csv recipients.csv \
	--subject "Hi {{name}}, quick note about {{company}}" \
	--body-file template.txt \
	--min-delay 60 \
	--max-delay 180
```

CSV parsing supports UTF-8, BOM-prefixed files, quoted commas, and empty rows. Missing template variables stop campaign creation with an actionable error.

## Campaign commands

```bash
python src/main.py status
python src/main.py resume
python src/main.py resume c_20260922_120000_abc123
python src/main.py log
```

The default daily limit is 100 successful sends. Delays are uniformly random within the configured bounds. Failed sends use exponential backoff and the configured retry count. HTTP 401 responses are treated as authentication failures and stop the campaign when a refresh is unavailable or unsuccessful.

SQLite and structured JSONL logs are stored in `.maillaunch/` by default. Override locations with `MAILLAUNCH_DATA_DIR`, `MAILLAUNCH_DB_PATH`, and `MAILLAUNCH_LOG_PATH`.

## Tests

Tests never call provider APIs or wait for real delays:

```bash
python -m pytest -q
```

The suite covers CSV edge cases, email-column detection, template rendering, SQLite daily counts and resume behavior, retry/backoff, provider payloads, and structured logs.

## Design decisions

- **Python:** Python's standard library provides reliable CSV, MIME, SQLite, and CLI primitives while the OAuth libraries cover provider-specific login flows.
- **SQLite:** A local database gives atomic status updates and queryable campaign history without requiring a server.
- **Keychain:** `keyring` delegates token protection to the operating system rather than writing credentials to configuration files.
- **Provider adapters:** Gmail uses RFC 2822 MIME and URL-safe base64 at `users/me/messages/send`; Graph uses the required JSON `me/sendMail` request. Both are hidden behind the sending engine.
- **Testability:** Provider, sleep, and random-delay functions are injectable, so retry and throttling tests are fast and deterministic.

## Future improvements

Potential follow-ups include a more complete provider token-refresh implementation, optional scheduled execution, HTML templates and attachments, unsubscribe/compliance workflows, and opt-in live integration tests.
