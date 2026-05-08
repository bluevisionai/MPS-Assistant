# MPS Assistant

MPS Assistant is a restricted-source retrieval app for Medical Protection South Africa. It crawls the public South Africa section of the official MPS website, downloads supported linked documents, extracts their text into a local knowledge base, and answers questions only from retrieved MPS passages.

## What it does

- Crawls `https://www.medicalprotection.org/southafrica`
- Prioritises the South Africa join/member-type pages so membership application guidance is captured early
- Follows South Africa HTML pages on `www.medicalprotection.org`
- Renders and extracts the public MPS application flows on `apply.medicalprotection.org`
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
- Answers using a strict retrieval-only prompt and refuses when support is insufficient
- Lets you upload additional documents that become part of the same searchable knowledge base
- Refreshes the official site content on a schedule and on demand

## Guardrails

- No general knowledge answers
- No unofficial sources
- No invented rules, dates, prices, benefits, or policy terms
- High-stakes topics stay conservative
- If support is insufficient, the app returns:
  - `I don't have enough MPS-provided information to answer that confidently.`

## Requirements

- Python 3.9+
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
4. Start the app:

```bash
python3 -m uvicorn mps_assistant.app:app --reload
```

5. Open `http://127.0.0.1:8000`.

## How answers are produced

1. The app searches the local MPS knowledge base.
2. It retrieves the most relevant chunks using full-text search and embeddings.
3. It sends only those retrieved passages to the model.
4. It formats the answer into:
   - direct answer
   - MPS source citations
   - plain-English explanation
   - practical next steps
   - limitations or what to confirm with MPS

## Knowledge base files

- SQLite DB: `data/mps_assistant.db`
- Downloaded website files: `data/raw/`
- Uploaded files: `data/uploads/`

## CLI

Refresh the official MPS site from the terminal:

```bash
python3 -m mps_assistant.cli refresh
```

Run a bounded refresh for a smoke test:

```bash
python3 -m mps_assistant.cli refresh --max-pages 25
```

## Notes

- The crawler intentionally stays scoped to the official MPS South Africa site and linked `medicalprotection.org` resources.
- HTML crawling is limited by `CRAWL_MAX_PAGES` in `.env`.
- Refresh runs automatically on first startup if the knowledge base is empty, and then on the configured interval.
# MPS-Assistant
