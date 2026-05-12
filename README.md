# MPS Assistant

MPS Assistant is a restricted-source retrieval app for Medical Protection South Africa. It crawls the public South Africa section of the official MPS website, downloads supported linked documents, extracts their text into a local knowledge base, and answers questions only from retrieved MPS passages.

## What it does

- Crawls `https://www.medicalprotection.org/southafrica`
- Prioritises the South Africa join/member-type pages so membership application guidance is captured early
- Follows South Africa HTML pages on `www.medicalprotection.org`
- Renders and extracts the public MPS application flows on `apply.medicalprotection.org`
- Captures application bootstrap metadata such as scheme settings, route maps, upload limits, and field inventories from the official application host
- Downloads linked public resources such as PDF, DOCX, XLSX, CSV, TXT, and PPTX files on `*.medicalprotection.org`
- Extracts text plus source metadata:
  - URL
  - page title
  - document title
  - section heading
  - date downloaded
  - file name
  - page number where applicable
- Stores the content in a local SQLite knowledge base with full-text search and optional embeddings
- Automatically syncs local files under `manual_files/` into the knowledge base as priority material
- Answers using a strict retrieval-only prompt and refuses when support is insufficient
- Lets you upload additional documents that become part of the same searchable knowledge base
- Includes an `Apply in chat` mode for the South Africa onboarding journey, with live quote lookups and draft application submission
- Keeps the official site content local in SQLite and refreshes it on a schedule or on demand

## Guardrails

- No general knowledge answers
- No unofficial sources
- No invented rules, dates, prices, benefits, or policy terms
- High-stakes topics stay conservative
- If support is insufficient, the app returns:
  - `I don't have enough MPS-provided information to answer that confidently.`

## Requirements

- Python 3.13
- An OpenAI API key for embeddings and answer generation
- Google Chrome installed locally for rendered application-form crawling

Without `OPENAI_API_KEY`, the app can still crawl and index content, but it will refuse final Q&A generation.

Without Chrome, the crawler can still index static HTML pages and downloadable documents, but rendered application flows on `apply.medicalprotection.org` will be skipped.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
   The default answer model is `gpt-5.4-mini`. If that model is not available to your project, the app will try `gpt-5.5`, then `gpt-5.4`, then `gpt-5-mini`, then `gpt-4.1-mini`.
4. Start the app:

```bash
python -m uvicorn mps_assistant.app:app --reload
```

5. Open `http://127.0.0.1:8000`.

## How answers are produced

1. The app searches the local MPS knowledge base.
2. It retrieves the most relevant chunks using full-text search and embeddings.
   Local `manual_files/` content is preferred when it overlaps with crawled material.
3. It sends only those retrieved passages to the model.
4. It formats the answer into:
   - direct answer
   - MPS source citations
   - plain-English explanation
   - practical next steps
   - limitations or what to confirm with MPS

Normal question answering works from the local knowledge base. The chat UI no longer preloads the live onboarding configuration on first page load, so regular Q&A stays local-first and faster.

## Knowledge base files

- SQLite DB: `data/mps_assistant.db`
- Downloaded website files: `data/raw/`
- Uploaded files: `data/uploads/`
- Priority manual knowledge: `manual_files/`

Files in `manual_files/` are ingested automatically on startup and on refresh. They are stored as a dedicated priority source so they can override conflicting crawled wording when both cover the same topic.

## Deploying current loaded data

CI/CD deploys from repository contents, so local `data/` is not included directly.

To deploy the currently loaded data with your next code deploy:

1. Export a deployment snapshot:

```bash
bash scripts/export_deploy_data.sh
```

2. Commit and push the generated `deploy_data/mps_data_bundle.tgz` and `deploy_data/manifest.json`.

At startup, `startup.sh` automatically hydrates `DATA_DIR` from `deploy_data/mps_data_bundle.tgz` when the bundle exists.

## CLI

Refresh the official MPS site from the terminal:

```bash
python -m mps_assistant.cli refresh
```

Run a bounded refresh for a smoke test:

```bash
python -m mps_assistant.cli refresh --max-pages 25
```

Run the supported `/20` dummy walkthrough once to store the observed request model without trying to bypass server-side protections:

```bash
python -m mps_assistant.cli harvest-application https://apply.medicalprotection.org/20
```

## UI smoke test

Run the browser smoke test for the main chat journeys:

```bash
python scripts/chat_ui_smoke_test.py
```

This checks the desktop and mobile chat flows, follow-up questions, session persistence, collapse/reopen behavior, and new-chat reset.

## Chat Onboarding Mode

The floating chat UI has two modes:

- `Ask MPS` for retrieval-grounded questions against the MPS knowledge base
- `Apply in chat` for the guided South Africa onboarding flow

The onboarding flow currently supports the GP membership paths that the live portal exposes through the tested quotation journey. It can:

- verify access to the live portal
- send and verify email OTPs
- fetch live pricing and rate-card data
- collect the main underwriting and personal details in chat
- submit a live draft lead to the MPS onboarding API

The chat does not collect or store raw card numbers, CVVs, or full bank login details. Payment preference can be captured in chat, but final secure card or debit-order setup must still be completed directly with MPS.

## Azure App Service

Use `./startup.sh` as the App Service startup command.

```bash
./startup.sh
```

Recommended App Service application settings:

- App Service runtime stack: `PYTHON|3.13`
- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-5.4-mini`
- `OPENAI_FALLBACK_MODELS=gpt-5.5,gpt-5.4,gpt-5-mini,gpt-4.1-mini`
- `ONBOARDING_PORTAL_URL`
- `ONBOARDING_AUTH_URL`
- `ONBOARDING_API_BASE_URL`
- `ONBOARDING_COUNTRY_CODE=za`
- `ONBOARDING_PORTAL_USERNAME`
- `ONBOARDING_PORTAL_PASSWORD`
- `DATA_DIR=/home/site/data`
- `ENABLE_SCHEDULER=false`
- `AUTO_REFRESH_ON_STARTUP=false`
- `REFRESH_TIMEZONE=Africa/Johannesburg`
- `REFRESH_HOUR_LOCAL=0`
- `REFRESH_MINUTE_LOCAL=0`
- `SQLITE_JOURNAL_MODE=DELETE`
- `WEB_CONCURRENCY=1`

Health check path:

- `/healthz`

Important App Service constraints for this codebase:

- The app currently uses SQLite plus local files for the knowledge base. Treat this as a single-instance deployment unless you replace those with managed shared services.
- Scheduler-based refresh jobs are disabled by default on App Service to avoid duplicate crawls across workers or instances. Use the existing `POST /api/refresh` endpoint from an external scheduler if you want automated refreshes.
- Stock Python App Service images do not include Chrome/Chromedriver. That means rendered crawling of `apply.medicalprotection.org` will not work there unless you use a custom image or otherwise provide a compatible browser runtime.

## Notes

- The crawler intentionally stays scoped to the official MPS South Africa site and linked `medicalprotection.org` resources.
- The manual `harvest-application` command is separate from scheduled refreshes so the app does not repeatedly submit dummy form data to the production application endpoint.
- HTML crawling is limited by `CRAWL_MAX_PAGES` in `.env`.
- Refresh runs automatically on first startup if the knowledge base is empty, and then once a day at local midnight by default.
# MPS-Assistant
