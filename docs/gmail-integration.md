# Optional module: Gmail integration

The public demo uses sample emails, a web form and `.eml` uploads, so visitors never have to connect a real mailbox. This module shows how the same pipeline plugs into a real Gmail inbox.

> **Status:** the message conversion (`app/gmail.py` → `raw_message_to_email`) is covered by unit tests. The sync script talks to the live Gmail API and was not exercised against a real mailbox as part of this demo.

## What it does

`scripts/gmail_sync.py`:

1. Reads unread messages from the inbox (`in:inbox is:unread`, up to 20 per run).
2. Downloads each one in `raw` format. Gmail returns RFC 822 text, the same format as a `.eml` file, so it goes through the same parser as the upload feature.
3. Stores it and runs the same AI triage (classification, extraction, validation, retry, human-review fallback).
4. Applies a Gmail label such as `Oakridge AI/viewing_request` or `Oakridge AI/needs_review` and marks the message as read.

The team keeps working in Gmail, but every message arrives sorted, and the dashboard shows the extracted data.

## Setup (about 10 minutes)

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and **enable the Gmail API**.
2. Configure the **OAuth consent screen** (External, "Testing" mode) and add your Gmail address as a test user.
3. Create an **OAuth client ID** of type *Desktop app* and download it as `credentials.json` into the project root. It is ignored by git.
4. Install the optional dependencies and run the script:

   ```bash
   pip install -e ".[gmail]"
   python scripts/gmail_sync.py
   ```

   The first run opens a browser to authorize access and saves `token.json`, which is also ignored by git.

Scope requested: `gmail.modify` (read messages, add labels, mark as read). It cannot delete emails or send mail.

## Taking it to production

- **Push instead of polling:** use `users.watch` with Google Cloud Pub/Sub so Gmail notifies the app when a message arrives, instead of running the script on a schedule.
- **Google Workspace:** for a company domain, use a service account with domain-wide delegation instead of a personal OAuth token.
- **Secrets:** keep the OAuth client and tokens in the hosting platform's secret manager, never in the repository.
- **Idempotency:** store the Gmail message ID with each email so a message is never processed twice, even if the labeling step fails.
