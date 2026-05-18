<div align="center">
  <img src="app/static/widget/logo.jpg" width="120" alt="Copernicus Berlin" />

  <h1>Copernicus Berlin — AI Assistant</h1>

  <p>
    <b>An embeddable chat assistant for <a href="https://copernicusberlin.org">copernicusberlin.org</a></b><br>
    Answers visitor questions about programs, scholarships, events, and how to get involved —
    with a built-in admin dashboard for monitoring conversations and managing the knowledge base.
  </p>

  <p>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white">
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688?style=flat-square&logo=fastapi&logoColor=white">
    <img alt="OpenAI" src="https://img.shields.io/badge/OpenAI-gpt--4.1--mini-412991?style=flat-square&logo=openai&logoColor=white">
    <img alt="Playwright" src="https://img.shields.io/badge/Playwright-Chromium-2EAD33?style=flat-square&logo=playwright&logoColor=white">
    <img alt="Status" src="https://img.shields.io/badge/Status-Production%20Ready-EE7625?style=flat-square">
  </p>

  <p>
    <a href="#-quick-start">Quick start</a> ·
    <a href="#-screenshots">Screenshots</a> ·
    <a href="#%EF%B8%8F-admin-dashboard">Admin dashboard</a> ·
    <a href="#-embed-on-your-website">Embed</a> ·
    <a href="#%EF%B8%8F-configuration">Configuration</a>
  </p>
</div>

---

## ✨ What it does

🤖 &nbsp; **Chat widget** — drops into any page as an iframe. Welcomes visitors,
suggests common questions, streams answers token-by-token, and offers a
"Contact a human" form that routes directly to the admin inbox.

📚 &nbsp; **Knowledge base** — automatically crawls every English page on
copernicusberlin.org and builds a searchable index. One-click rebuild
from the dashboard whenever the website changes.

🎛️ &nbsp; **Admin dashboard** — review every conversation, respond to support
requests, edit suggested questions, add manual FAQ entries, override
outbound links, and track usage analytics — all from one polished UI.

---

## 📸 Screenshots

<table>
  <tr>
    <td width="33%" align="center">
      <img src="doc/screenshots/widget-welcome.png" alt="Chat widget welcome" />
      <br><sub><b>Chat widget — welcome screen</b></sub>
    </td>
    <td width="33%" align="center">
      <img src="doc/screenshots/widget-chat.png" alt="Chat widget conversation" />
      <br><sub><b>Streamed conversation with sources</b></sub>
    </td>
    <td width="33%" align="center">
      <img src="doc/screenshots/admin-support.png" alt="Admin support requests" />
      <br><sub><b>Admin — support requests inbox</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="doc/screenshots/admin-analytics.png" alt="Admin analytics" />
      <br><sub><b>Admin — usage analytics</b></sub>
    </td>
    <td align="center">
      <img src="doc/screenshots/admin-history.png" alt="Admin session history" />
      <br><sub><b>Admin — session history</b></sub>
    </td>
    <td align="center">
      <img src="doc/screenshots/admin-reindex.png" alt="Admin reindex" />
      <br><sub><b>Admin — search index management</b></sub>
    </td>
  </tr>
</table>

---

## 🛠️ Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Backend** | FastAPI · Python 3.11+ | Async, typed, well-documented |
| **Crawler** | Playwright (headless Chromium) | The Copernicus website is a client-rendered React SPA, so a normal HTTP crawler sees nothing |
| **Retrieval** | OpenAI `text-embedding-3-large` + BM25 lexical search | Hybrid scoring with URL-slug-aware boosting keeps program-specific facts (e.g. IES vs PIR scholarships) from getting mixed up |
| **Chat model** | OpenAI `gpt-4.1-mini`, streaming | Fast first-token, strict context grounding |
| **Storage** | JSON files under `data/` | No database required — easy to back up, restore, and inspect |
| **Frontend** | Vanilla HTML / CSS / JS | No build step, no framework, instant edits |

---

## 🚀 Quick start

> **Requirements:** Python 3.11+, an OpenAI API key, ~500 MB free disk for the Chromium browser.

```bash
# 1️⃣  clone & enter
git clone https://github.com/Azimml/copernicus-ai.git
cd copernicus-ai

# 2️⃣  install Python deps + Chromium browser
make install

# 3️⃣  add your OpenAI API key
cp .env.example .env
#   ↳ open .env in your editor and fill in OPENAI_API_KEY

# 4️⃣  crawl the website and build the search index (3–5 min)
make index

# 5️⃣  start the server
make run
```

Then open in your browser:

| URL | What it is |
|---|---|
| 💬 &nbsp; http://localhost:8000/widget | **Chat widget** — embeddable assistant |
| 🎛️ &nbsp; http://localhost:8000/admin | **Admin dashboard** — open access on localhost |
| 📘 &nbsp; http://localhost:8000/docs | **Swagger API docs** — interactive |

---

## 🌐 Embed on your website

Drop this `<iframe>` wherever you want the chat to appear:

```html
<iframe
  src="https://your-deployment.example.com/widget"
  title="Copernicus Berlin Assistant"
  width="400"
  height="680"
  style="border:0; border-radius:12px; box-shadow:0 6px 30px rgba(0,0,0,.12)"
  loading="lazy"
></iframe>
```

Replace `your-deployment.example.com` with the host where this service is running.

---

## 🎛️ Admin dashboard

Seven sections, all open at `/admin`:

| Section | Purpose |
|---|---|
| 📬 &nbsp; **Support requests** | Every "Contact a human" submission. Reply directly; the assistant pauses while a human is on the conversation. |
| 💬 &nbsp; **Session history** | Every chat session with full transcript, satisfaction ratings, and relative timestamps. |
| ⚡ &nbsp; **Quick actions** | The suggested-question buttons shown to new visitors. Edit, reorder, enable/disable — changes go live immediately. |
| ❓ &nbsp; **FAQ** | Manual Q&A entries for topics not yet on the website. Automatically merged into the search index. |
| 🔗 &nbsp; **Link rules** | Override or hide the "Learn more" link the assistant attaches to specific question patterns. |
| 📊 &nbsp; **Analytics** | Total messages, unique sessions, satisfaction rate, average latency, and top questions — filterable by time range. |
| 🔄 &nbsp; **Search index** | Rebuild the knowledge base. <b>Full reindex</b> re-crawls every page (3–5 min); <b>Re-embed only</b> skips the crawl (~30 sec). |

---

## 🔄 Re-crawling the website

Whenever the Copernicus Berlin website is updated, refresh the assistant's
knowledge base:

1. Open the admin dashboard → **Search index**
2. Pick a mode:
   - **Full reindex** *(recommended)* — re-crawls every page on `copernicusberlin.org/en`. Takes 3–5 minutes.
   - **Re-embed only** — skips the crawl, just rebuilds embeddings from existing content. ~30 seconds.
3. Click **Start reindex** and wait. You can navigate away — the job runs to completion.

For automated workflows you can also run `make index` from the shell.

---

## ⚙️ Configuration

All settings live in `.env`. The essentials:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required.** Used for both chat and embeddings. |
| `OPENAI_CHAT_MODEL` | `gpt-4.1-mini` | Chat completion model. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model for retrieval. |
| `SITE_ROOT` | `https://copernicusberlin.org` | Root URL to crawl. |
| `CRAWL_PATHS` | `/en` | Comma-separated path prefixes to crawl. |
| `CRAWL_EXCLUDE_HOSTS` | `campus.copernicusberlin.org` | Hosts to skip during crawling. |
| `CRAWL_MAX_PAGES` | `200` | Safety cap on pages crawled per run. |
| `RETRIEVAL_TOP_K` | `8` | Number of chunks pulled into the prompt per query. |
| `APP_PORT` | `8000` | HTTP port the server listens on. |

See [.env.example](.env.example) for the full list.

---

## 📁 Project structure

```
copernicus-ai/
├── 📂 app/
│   ├── 📂 api/routes.py        ← FastAPI endpoints (chat, admin)
│   ├── 📂 core/                ← config, JSON helpers
│   ├── 📂 models/schemas.py    ← Pydantic request/response models
│   ├── 📂 services/            ← chat, retrieval, indexer, crawler, handoff, …
│   ├── 📂 static/widget/       ← chat widget (HTML / CSS / JS + logo)
│   ├── 📂 static/admin/        ← admin dashboard
│   └── 📄 main.py              ← FastAPI app entrypoint
├── 📂 data/
│   ├── 📂 raw/                 ← crawled content, FAQ, link rules, sessions
│   └── 📂 index/               ← embeddings (.npy) + chunk metadata (.json)
├── 📂 doc/screenshots/         ← README screenshots
├── 📂 scripts/build_index.py   ← CLI to rebuild the index
├── 📄 Makefile                 ← install / index / run shortcuts
├── 📄 requirements.txt
└── 📄 .env.example
```

---

## 🚢 Deployment notes

- The service is a **single Python process** — run it behind any standard reverse
  proxy (nginx, Caddy, Traefik, Cloudflare Tunnel).
- Persistent data lives in **`data/`**. Mount it as a volume in production so
  conversation history and configuration survive container restarts.
- Playwright needs system libraries for Chromium. On Debian/Ubuntu `make install`
  pulls these automatically; on Alpine install them manually
  (`apk add chromium nss freetype …`).
- For HTTPS, terminate TLS at the reverse proxy. The widget iframe must be
  embedded over the **same scheme** as the host page or browsers will block it.
- Set `OPENAI_API_KEY` and any non-default settings as **environment variables**
  in production rather than committing them to `.env`.

---

<div align="center">
  <sub>Built for <a href="https://copernicusberlin.org">Copernicus Berlin e. V.</a></sub>
</div>
