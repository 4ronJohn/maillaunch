# MailLaunch

MailLaunch is a local Python CLI for personalized cold-email campaigns through the Gmail API or Microsoft Graph. It supports personalized templates, randomized sending delays, daily send limits, retries, campaign persistence, scheduling, resuming interrupted campaigns, structured logging, and OAuth token storage through the operating system keychain.

## Features

* Gmail API and Microsoft Graph email sending
* Personalized subject and body templates
* CSV recipient loading with automatic email-column detection
* UTF-8 and UTF-8 BOM CSV support
* Quoted CSV fields and commas inside values
* Configurable randomized delays between emails
* Daily successful-send limit
* Automatic retry with exponential backoff
* OAuth authentication and token refresh
* OAuth tokens stored in the OS keychain
* SQLite campaign state persistence
* Resume interrupted campaigns
* Local-process campaign scheduling
* Structured JSONL event logging
* Campaign status and log commands
* Automated test suite

---

## Requirements

* Python 3.10 or newer
* A Gmail or Microsoft account
* Gmail API credentials or a Microsoft Entra application
* Internet connection for authentication and sending

---

## Installation

Clone or download the repository and open a terminal in the project directory.

### Windows PowerShell

```powershell
cd path\to\maillaunch

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### macOS/Linux

```bash
cd path/to/maillaunch

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Copy the environment template:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS/Linux

```bash
cp .env.example .env
```

Edit `.env` and add the required provider credentials.

---

## Running MailLaunch from the CLI

MailLaunch is a command-line application and does not open a graphical window.

Open a terminal in the project directory, activate the virtual environment, and run:

```powershell
python src/main.py --help
```

If the package has been installed with its CLI entry point, you can also use:

```powershell
maillaunch --help
```

The help command displays the available commands and options.

Main commands:

```text
auth gmail
auth microsoft
send
status
resume
log
```

---

## Configuration

MailLaunch uses:

* `.env` for provider credentials and other sensitive environment variables
* `maillaunch.config.yaml` for non-sensitive application defaults

Example `.env`:

```env
GMAIL_CLIENT_ID=your-gmail-client-id
GMAIL_CLIENT_SECRET=your-gmail-client-secret
MICROSOFT_CLIENT_ID=your-microsoft-client-id
```

The `.env` file should not be committed to Git.

OAuth tokens are stored using the operating system keychain and are not stored in YAML, SQLite, logs, or normal error output.

### Optional data-path overrides

MailLaunch stores application data under `.maillaunch/` by default.

The following environment variables can be used to override the default locations:

```env
MAILLAUNCH_DATA_DIR=...
MAILLAUNCH_DB_PATH=...
MAILLAUNCH_LOG_PATH=...
```

---

# Provider Setup

## Gmail API

To use Gmail:

1. Create a project in Google Cloud.
2. Enable the Gmail API.
3. Create an OAuth client for a Desktop application.
4. Add the Gmail OAuth credentials to `.env`.
5. Authenticate MailLaunch.

### Required Gmail API scope

```text
https://www.googleapis.com/auth/gmail.send
```

Authenticate:

```powershell
python src/main.py auth gmail
```

A browser window will open for Google OAuth authentication.

After authentication, the OAuth token is stored in the operating system keychain.

---

## Microsoft Graph

To use Microsoft:

1. Register an application in Microsoft Entra ID.
2. Configure it as a public/desktop client.
3. Add the required delegated permissions.
4. Add the Microsoft client ID to `.env`.
5. Authenticate MailLaunch.

### Required Microsoft Graph delegated permissions

```text
User.Read
Mail.Send
```

No client secret is required for the public/desktop application flow.

Authenticate:

```powershell
python src/main.py auth microsoft
```

After authentication, the OAuth token information is stored in the operating system keychain.

---

# Campaign Files

Campaign CSV and template files can be stored anywhere on the computer as long as the correct path is provided.

For example, you can create a `campaigns` folder inside the project:

```text
maillaunch/
├── campaigns/
│   ├── recipients.csv
│   └── template.txt
├── src/
├── tests/
├── .env
├── maillaunch.config.yaml
└── ...
```

The `campaigns` folder is only an example. The files do not have to be located there.

---

## Recipients CSV

Example:

```csv
name,email,company
John Doe,john@example.com,ABC Corp
Jane Smith,jane@example.com,XYZ Inc
```

MailLaunch automatically detects the recipient email column.

The CSV must contain a column whose name includes:

```text
email
```

or

```text
mail
```

The check is case-insensitive.

Examples of valid email column names include:

```text
email
Email
EMAIL
email_address
work_email
mail
customer_mail
```

All other CSV columns are available for use as template variables.

### CSV support

MailLaunch supports:

* UTF-8 CSV files
* UTF-8 BOM
* Quoted fields
* Commas inside quoted values
* Empty rows

---

# Email Templates

Templates use double curly braces:

```text
{{name}}
{{company}}
```

Example `campaigns/template.txt`:

```text
Hi {{name}},

I came across {{company}} and wanted to reach out regarding a potential opportunity.

Best regards,
Your Name
```

The values are taken from the corresponding CSV columns.

For example:

```csv
name,email,company
John Doe,john@example.com,ABC Corp
```

produces:

```text
Hi John Doe,

I came across ABC Corp and wanted to reach out regarding a potential opportunity.

Best regards,
Your Name
```

Subject lines also support templates.

Example:

```text
Quick note for {{name}} at {{company}}
```

If a template references a variable that does not exist in the CSV, campaign creation stops and MailLaunch reports the missing variable instead of starting a partially configured campaign.

---

# Sending a Campaign

From the MailLaunch project directory:

### Gmail

Windows PowerShell:

```powershell
python src/main.py send `
  --provider gmail `
  --csv campaigns\recipients.csv `
  --subject "Quick note for {{name}} at {{company}}" `
  --body-file campaigns\template.txt `
  --min-delay 60 `
  --max-delay 180
```

macOS/Linux:

```bash
python src/main.py send \
  --provider gmail \
  --csv campaigns/recipients.csv \
  --subject "Quick note for {{name}} at {{company}}" \
  --body-file campaigns/template.txt \
  --min-delay 60 \
  --max-delay 180
```

### Microsoft

Windows PowerShell:

```powershell
python src/main.py send `
  --provider microsoft `
  --csv campaigns\recipients.csv `
  --subject "Quick note for {{name}} at {{company}}" `
  --body-file campaigns\template.txt `
  --min-delay 60 `
  --max-delay 180
```

The `--min-delay` and `--max-delay` values are in seconds.

MailLaunch randomly selects a delay between the configured values before sending the next recipient.

For example:

```text
--min-delay 60
--max-delay 180
```

results in a random delay between 60 and 180 seconds.

---

## Using Absolute File Paths

CSV and template files can also be stored outside the project.

Example:

```powershell
python src/main.py send `
  --provider gmail `
  --csv "C:\Users\YourName\Documents\recipients.csv" `
  --subject "Quick note for {{name}}" `
  --body-file "C:\Users\YourName\Documents\template.txt"
```

---

# Scheduling a Campaign

MailLaunch supports scheduling a campaign using the `--at` option.

Example:

```powershell
python src/main.py send `
  --provider gmail `
  --csv campaigns\recipients.csv `
  --subject "Quick note for {{name}}" `
  --body-file campaigns\template.txt `
  --min-delay 60 `
  --max-delay 180 `
  --at "2026-09-23 09:00"
```

The scheduled time uses the local time of the computer running MailLaunch.

### Important scheduling behavior

MailLaunch's scheduler is a **local-process scheduler**.

It does not use:

* Windows Task Scheduler
* cron
* a background service
* a daemon
* a web server

The Python process must remain open while waiting for the scheduled time.

The campaign is saved to SQLite before MailLaunch begins waiting, so the scheduled campaign state is persisted.

### Cancelling a scheduled campaign

Press:

```text
Ctrl+C
```

while MailLaunch is waiting.

No recipients are sent while the process is waiting.

The campaign is restored to its normal pending state and remains available for later resumption.

Scheduled campaigns remain separate from other interrupted campaigns.

Each CLI process handles one scheduled campaign at a time, so another terminal/process can be used for another campaign.

---

# Campaign Commands

## Check campaign status

```powershell
python src/main.py status
```

Example:

```text
Today's successful sends: 20 / 100
Active campaign: c_20260922_092836_2fbfb3
Pending: 3
Sent: 1
Failed: 0
```

The status command reads campaign state from SQLite.

---

## Resume a Campaign

Resume the active campaign:

```powershell
python src/main.py resume
```

Resume a specific campaign:

```powershell
python src/main.py resume c_20260922_120000_abc123
```

Campaign state is stored in SQLite, so an interrupted campaign can continue without starting from the beginning.

Campaigns are tracked separately by their campaign ID.

---

## View Logs

```powershell
python src/main.py log
```

MailLaunch stores structured JSONL event logs.

Example event:

```json
{"timestamp":"2026-09-22T12:00:00","status":"SENT","provider":"gmail","email":"john@example.com","name":"John Doe","campaign_id":"c_20260922_120000_abc123","attempt":1}
```

Retry example:

```json
{"timestamp":"2026-09-22T12:01:00","status":"RETRY","provider":"microsoft","email":"john@example.com","name":"John Doe","campaign_id":"c_20260922_120000_abc123","error":"Temporary server error","attempt":1}
```

Older log entries created before provider information was added may not contain the `provider` field.

---

# Daily Send Limit

MailLaunch enforces a daily limit on **successful sends**.

The default limit is:

```text
100 successful sends per day
```

The limit is tracked through SQLite and persists across CLI processes.

A failed email does not count as a successful send.

When the limit is reached, the campaign stops without sending additional emails.

The engine reports the appropriate `LIMIT_REACHED` status.

---

# Retry and Error Handling

MailLaunch includes retry handling for transient failures.

Features include:

* Configurable retry count
* Exponential backoff
* Retry event logging
* Authentication failure handling
* Campaign state persistence
* Graceful interruption

Transient failures can be retried automatically.

HTTP `401` authentication failures are treated as authentication errors. MailLaunch attempts to refresh authentication when possible. If authentication cannot be refreshed successfully, the campaign stops instead of repeatedly attempting unauthorized requests.

Failed recipients are recorded in campaign state and logs.

---

# Authentication and Token Storage

MailLaunch uses OAuth for both providers.

### Gmail

Gmail messages are sent through the Gmail API using:

```text
POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send
```

Messages are constructed as RFC 2822/MIME email and encoded using URL-safe Base64 before being sent through the Gmail API.

### Microsoft

Microsoft messages are sent through Microsoft Graph using:

```text
POST /v1.0/me/sendMail
```

The Microsoft implementation uses the Graph JSON `sendMail` format.

### Token storage

OAuth credentials are stored through the operating system's keychain using Python's `keyring` library.

Tokens are not stored in:

* `maillaunch.config.yaml`
* SQLite campaign data
* JSONL logs
* normal error messages

On Windows, Microsoft token data is stored using Windows Credential Manager with chunked storage to accommodate credential size limits.

---

# Persistence and Resume

MailLaunch uses SQLite as the source of truth for campaign state.

Campaign data includes information such as:

* Campaign ID
* Provider
* Recipient
* Recipient status
* Attempts
* Campaign progress
* Scheduling information

This allows campaigns to be resumed after an interruption.

Structured JSONL logs provide an event history for sending, retries, failures, and successful deliveries.

Application data is stored under:

```text
.maillaunch/
```

unless the data paths are overridden through environment variables.

---

# Sending Flow

A typical campaign follows this process:

```text
CSV
 │
 ▼
Validate recipient data
 │
 ▼
Validate subject/body templates
 │
 ▼
Create campaign in SQLite
 │
 ▼
Check daily send limit
 │
 ▼
Render recipient-specific subject/body
 │
 ▼
Apply configured delay
 │
 ▼
Authenticate / refresh token
 │
 ▼
Send through Gmail or Microsoft Graph
 │
 ├── Success ──► Record SENT
 │
 └── Failure
       │
       ▼
    Retry with backoff
       │
       ├── Success ──► Record SENT
       └── Final failure ──► Record FAILED
```

The SQLite state and structured logs are updated as the campaign progresses.

---

# Project Structure

```text
maillaunch/
├── maillaunch.config.yaml
├── requirements.txt
├── pyproject.toml
├── .env.example
│
├── src/
│   ├── main.py
│   │
│   ├── auth/
│   │   ├── gmail.py
│   │   ├── microsoft.py
│   │   └── storage.py
│   │
│   ├── sender/
│   │   ├── gmail.py
│   │   ├── microsoft.py
│   │   └── engine.py
│   │
│   ├── campaign/
│   │   ├── database.py
│   │   ├── campaign.py
│   │   └── resume.py
│   │
│   └── utils/
│       ├── config.py
│       ├── csv_parser.py
│       └── logger.py
│
└── tests/
    ├── test_auth_storage.py
    ├── test_csv_parser.py
    ├── test_daily_limit.py
    ├── test_engine_progress_and_auth.py
    ├── test_logger.py
    ├── test_main_settings.py
    ├── test_provider_payloads.py
    ├── test_resume.py
    ├── test_retry.py
    ├── test_scheduling.py
    └── test_template.py
```

---

# Testing

Run the complete test suite from the project directory:

```powershell
python -m pytest -q
```

The current test suite contains **48 passing tests**.

The tests cover:

* CSV parsing
* Email-column detection
* Template rendering
* Missing template variables
* SQLite campaign state
* Daily send limits
* Campaign resume
* Retry and exponential backoff
* Provider payload construction
* Authentication/storage behavior
* Structured logging
* Scheduling
* CLI settings and configuration
* Campaign progress

The tests are designed to exercise the core logic without requiring real email delivery for normal test execution.

---

# Security

MailLaunch is designed to keep authentication credentials separate from campaign data.

### Credentials

Sensitive provider credentials are stored in `.env`.

Do not commit `.env` to Git.

### OAuth tokens

OAuth tokens are stored in the operating system keychain using `keyring`.

They are not written to:

```text
maillaunch.config.yaml
SQLite
JSONL logs
normal error output
```

### API permissions

Only the required provider permissions are requested:

**Gmail**

```text
https://www.googleapis.com/auth/gmail.send
```

**Microsoft Graph**

```text
User.Read
Mail.Send
```

---

# Design Decisions

## Python CLI

A local Python CLI was selected to keep the application simple to run, easy to test, and suitable for automation.

## SQLite

SQLite provides persistent campaign state without requiring an external database server.

## OS Keychain

OAuth tokens are stored using the operating system's credential/keychain facilities instead of plain-text files.

## Provider Adapters

Gmail and Microsoft sending are separated into provider-specific modules so that the campaign engine can handle common sending logic independently from provider API details.

## Structured Logging

JSONL logs provide machine-readable campaign events while keeping the application local and easy to inspect.

## Testable Components

CSV parsing, templating, retry behavior, database operations, provider payload generation, authentication storage, scheduling, and CLI configuration are separated into testable components.

---

# Limitations

* Scheduling is local-process based. The Python process must remain open until the scheduled time.
* No external task scheduler or background service is required or included.
* Normal tests do not send real emails.
* HTML email templates and attachments are not currently part of the core workflow.
* Unsubscribe/compliance workflows are not implemented.
* Live provider integration testing requires real Gmail or Microsoft credentials.
* The application is intended for controlled email campaigns and should be used in accordance with applicable email, privacy, and anti-spam requirements.

---

# Quick Start

For a quick setup, the basic workflow is:

```text
1. Open a terminal in the MailLaunch directory
2. Create and activate the Python virtual environment
3. Install dependencies
4. Create and configure .env
5. Configure Gmail or Microsoft API credentials
6. Authenticate the provider
7. Create recipients.csv
8. Create template.txt
9. Run a campaign
10. Check status/logs
```

Example:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python src/main.py auth gmail

python src/main.py send `
  --provider gmail `
  --csv campaigns\recipients.csv `
  --subject "Quick note for {{name}}" `
  --body-file campaigns\template.txt `
  --min-delay 60 `
  --max-delay 180
```

Check the campaign:

```powershell
python src/main.py status
```

View the event log:

```powershell
python src/main.py log
```

Resume an interrupted campaign:

```powershell
python src/main.py resume
```

Run the tests:

```powershell
python -m pytest -q
```




# Additional Documentation

## What I Would Improve With More Time

Potential future improvements include:

* A more robust background scheduler so scheduled campaigns can run without keeping the CLI process open.
* Optional HTML email templates and attachment support.
* More comprehensive live integration tests using sandbox/test accounts for Gmail and Microsoft Graph.
* Additional campaign filtering and management commands for handling multiple campaigns.
* More detailed reporting and campaign statistics.
* Expanded email compliance features such as unsubscribe handling and configurable suppression lists.
* Additional provider-specific error handling and diagnostics.

These are intentionally outside the current assignment scope so the implementation remains focused on the required CLI functionality.
