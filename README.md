# Parlo

Parlo lets any business create an AI chatbot from its own knowledge and put it on a website with one script tag. The same knowledge is also available to voice assistants such as Alexa+ through a self-hosted MCP server.

Built for the Amazon Developer Hackathon (Alexa+ track). Released under the MIT license.

## What it does

- A business owner signs up, creates a bot and adds knowledge (text sources).
- Parlo splits the text into chunks, embeds them (Gemini embeddings) and stores them in PostgreSQL with pgvector.
- Visitors chat with the bot through an embeddable widget (`/widget.js`). Answers come only from that business's own knowledge, and the bot says so when it does not know.
- Voice assistants reach the same knowledge through the MCP server (see "Alexa+ MCP server" below).

## Stack

Django 5 and Django REST Framework, JWT auth, PostgreSQL 16 with pgvector, Celery and Redis for background processing, Gemini for embeddings and answers, a vanilla JavaScript widget in a Shadow DOM, the MCP Python SDK for the Alexa+ server, and Docker Compose.

## How it works

1. A source is saved and a Celery task chunks it (about 1000 characters with overlap, paragraph-aware), embeds each chunk and marks the source `ready`.
2. A question is embedded, and the closest chunks of that one bot are found with a cosine search (HNSW index).
3. For website chat, the chunks go to the language model inside a delimited `<context>` block, and the answer comes back with the titles of the sources it used.
4. For voice, the MCP tool `search_knowledge` returns the passages without calling a language model, so it stays fast. The calling assistant writes the reply itself.

## Quickstart (for judges)

Requirements: Docker Desktop and a free Gemini API key (https://aistudio.google.com/apikey). No AWS account or Alexa device is needed.

1. Copy the environment file and edit it:

   ```
   copy .env.example .env
   ```

   In `.env` set `DJANGO_SECRET_KEY` to a long random string, `GEMINI_API_KEY` to your key,
   `EMBEDDING_BACKEND=gemini`, `LLM_BACKEND=gemini` and `DJANGO_DEBUG=True` (the demo pages only work in
   debug mode). Use the same database password in `POSTGRES_PASSWORD` and `DATABASE_URL`.

2. Start the app, the worker and the MCP server, then create the tables:

   ```
   docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --build
   docker compose exec web python manage.py migrate
   ```

3. Create a demo business ("Sunrise Shop") with knowledge and print its bot key:

   ```
   docker compose exec web python manage.py seed_demo
   ```

   The output lists the key and ready-made links.

4. Try it:

   - Simulated Alexa+: `http://localhost:8001/alexa/?key=PASTE_THE_KEY`
   - Website widget: `http://localhost:8001/demo/?key=PASTE_THE_KEY`
   - Call the MCP server as a client and list its tools:

     ```
     docker compose exec web python manage.py mcp_demo --url http://mcp:8002/mcp --key PASTE_THE_KEY --question "Can I get my money back?" --ask
     ```

   Good questions: "Can I get my money back?", "How long does delivery take?", "Do you take mobile money?"

5. Run the automated tests (111 tests, including real pgvector searches):

   ```
   docker compose exec web python manage.py test
   ```

Without a Gemini key, set both backends to `fake` to run everything offline with placeholder answers.

## Alexa+ MCP server

Parlo exposes every business's knowledge to voice assistants such as Alexa+ through a self-hosted MCP server (Streamable HTTP, `stateless_http`). It speaks MCP protocol version 2025-11-25 and later. One connection is one business: the assistant sends the bot's key as a bearer token (`Authorization: Bearer pk_...`) and only that bot's knowledge is reachable.

| Tool | What it does |
|------|--------------|
| `search_knowledge` | Fast retrieval-only lookup. Returns the matching passages and the document each came from, so the assistant can phrase the reply itself. Built for voice, where latency matters. |
| `ask_business_assistant` | Returns a finished answer written by the business's bot (a few seconds). Accepts a `conversation_id` for follow-up questions that keep their context. |
| `get_business_info` | The business name, greeting and the topics it knows about. |

Run it:

```
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d mcp
curl http://localhost:8002/health
```

The endpoint is `http://HOST:8002/mcp`. Requests without a valid key get `401`. The server checks the `Host` header (set `MCP_ALLOWED_HOSTS` when you expose it under a public name), limits each business to `MCP_RATE_PER_MINUTE` calls a minute, and shares the daily message cap with the website widget.

The server code is in `chatbots/mcp_server.py` and is started by `python manage.py run_mcp_server`.

### Simulated Alexa+

With `DJANGO_DEBUG=True`, open `http://localhost:8001/alexa/?key=pk_YOUR_KEY`. The page plays the part of Alexa+ (speech input in Chrome or Edge, spoken answers) and calls the MCP server like a real assistant would. The side panel shows each tool call, its timing and the passages found. This is a simulation for demonstration; the source is in `chatbots/views_alexa.py`. Real Alexa+ deployment would add OAuth 2.1 account linking, which is not built yet.

## Website widget

Add one script tag to any page:

```
<script src="http://localhost:8001/widget.js" data-key="pk_YOUR_KEY" defer></script>
```

A try-out page is at `http://localhost:8001/demo/?key=pk_YOUR_KEY` (development only). The widget uses a Shadow DOM, so it cannot clash with the host page's styles, and it writes all text with `textContent`, never as HTML. Each bot can list the domains allowed to use it.

## API overview

| Area | Path | Notes |
|------|------|-------|
| Health | `GET /api/health/` | Service check |
| Accounts | `/api/auth/` | Sign up, log in, current user (JWT) |
| Bots and sources | `/api/bots/...` | Create and manage bots, add and reprocess sources, test the search |
| Conversations | `/api/bots/<id>/conversations/` | Owners can read their bots' conversations |
| Public chat | `POST /api/public/chat/` | Header `X-Bot-Key: pk_...`, body `{"message", "conversation_id"}` |
| Public bot info | `GET /api/public/bot/` | Header `X-Bot-Key: pk_...` |
| Widget | `GET /widget.js` | The embeddable script |

Owner endpoints need `Authorization: Bearer <access token>`.

## Docker services

| Service | What it does |
|---------|--------------|
| `db` | PostgreSQL 16 with pgvector |
| `redis` | Redis (Celery broker) |
| `web` | Django app, published on port 8001 |
| `worker` | Celery worker that processes sources |
| `mcp` | MCP server on port 8002 (added by `docker-compose.mcp.yml`) |

## Environment variables

See `.env.example` for the full list. Never commit `.env`.

| Variable | Purpose |
|----------|---------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | `True` enables the demo pages (`/demo/`, `/alexa/`) |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` | Database settings |
| `CELERY_BROKER_URL` | Redis URL for Celery |
| `EMBEDDING_BACKEND` | `gemini` or `fake` (offline) |
| `LLM_BACKEND` | `gemini` or `fake` (offline) |
| `GEMINI_API_KEY` | Gemini key for embeddings and answers |
| `GEMINI_EMBEDDING_MODEL`, `GEMINI_CHAT_MODEL` | Model names (defaults are set in settings) |
| `MCP_RATE_PER_MINUTE` | Calls per minute per business on the MCP server (default 30) |
| `MCP_ALLOWED_HOSTS` | Host names the MCP server answers to |
| `ALEXA_SIM_MCP_URL` | MCP address used by the simulator (default `http://mcp:8002/mcp`) |
| `CORS_ALLOWED_ORIGINS` | Origins allowed to call the owner API |

## Security notes

- Every search and every conversation is limited to one bot, so businesses never see each other's knowledge. Tests cover this for both the website and the MCP server.
- Knowledge is passed to the model as data inside a delimited block, and the system prompt tells the model not to follow instructions found there.
- Public endpoints are rate limited, and each bot has a daily message cap (default 500).
- The MCP server rejects requests without a valid bot key (401) and checks the `Host` header.
- The domain allow-list of a bot is a convenience for browsers, not a security boundary, because non-browser clients can send any `Origin`.
- The widget writes all text with `textContent`, never as HTML.

## Tests

```
docker compose exec web python manage.py test
```

The tests cover accounts, bots, chunking, ingestion, retrieval (real pgvector), chat, the widget, the MCP server and the simulator.

## Project layout

```
config/            settings, urls
users/             custom user, signup, login
chatbots/          bots, sources, chunking, embeddings, retrieval, chat, widget
  mcp_server.py    the Alexa+ MCP server
  views_alexa.py   the simulated Alexa+ page
  management/commands/   run_mcp_server, mcp_demo, seed_demo
docker-compose.yml
docker-compose.mcp.yml
Dockerfile
```

## Known limitations

- Sources are text only; file and URL ingestion are planned.
- No React dashboard yet. Bots are managed through the API and the Django admin.
- The Alexa+ part is a self-hosted MCP server plus a simulator; OAuth 2.1 account linking for real Alexa+ deployment is not built.
- No email verification, password reset or billing.
- The MCP rate limiter is in memory, which is fine for one server process.

## Hackathon

Entered in the Alexa+ track of the Amazon Developer Hackathon, with the Open Source mini challenge. Parlo was started on 21 October 2026 during the hackathon period as a new project.

## License

MIT. See `LICENSE`.