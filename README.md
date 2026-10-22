# Parlo

Parlo lets any business create an AI chatbot from its own knowledge and put it on a website with one script tag. The same knowledge is also available to voice assistants such as Alexa+ through a self-hosted MCP server.

Built for the Amazon Developer Hackathon (Alexa+ track).

## What it does

1. A business owner signs up, creates a bot and adds knowledge (text sources).
2. Parlo splits the text into chunks, embeds them (Gemini embeddings) and stores them in PostgreSQL with pgvector.
3. Visitors chat with the bot through an embeddable widget (`/widget.js`). Answers come only from that business's own knowledge, and the bot says so when it does not know.
4. Voice assistants reach the same knowledge through the MCP server (see below).

## Stack

Django 5 and Django REST Framework, JWT auth, PostgreSQL 16 with pgvector, Celery and Redis for background processing, Gemini for embeddings and answers, vanilla JavaScript widget in a Shadow DOM, MCP Python SDK for the Alexa+ server, Docker Compose.

## Setup    

Put a Gemini API key in `.env` (`GEMINI_API_KEY`, with `EMBEDDING_BACKEND=gemini` and `LLM_BACKEND=gemini`). With the default `fake` backends everything runs offline with placeholder answers.

The API runs at `http://localhost:8001`. Try the widget at `http://localhost:8001/demo/?key=pk_YOUR_KEY` (development only).

## Security notes

- Every search and every conversation is limited to one bot, so businesses never see each other's knowledge.
- Knowledge is passed to the model as data inside a delimited block, and the system prompt tells the model not to follow instructions found there.
- Public endpoints are rate limited, and each bot has a daily message cap.
- The widget writes all text with `textContent`, never as HTML.
## Alexa+ MCP server

Parlo exposes every business's knowledge to voice assistants such as Alexa+ through a self-hosted
MCP server (Streamable HTTP, `stateless_http`). One connection is one business: the assistant sends the
bot's key as a bearer token (`Authorization: Bearer pk_...`) and only that bot's knowledge is reachable.

| Tool | What it does |
|------|--------------|
| `search_knowledge` | Fast retrieval-only lookup. Returns the matching passages and the document each came from, so the assistant can phrase the reply itself. Built for voice, where latency matters. |
| `ask_business_assistant` | Returns a finished answer written by the business's bot (a few seconds). Accepts a `conversation_id` for follow-ups. |
| `get_business_info` | The business name, greeting and the topics it knows about. |

Run it:

The endpoint is `http://HOST:8002/mcp`. Requests without a valid key get `401`. The server checks the
`Host` header (set `MCP_ALLOWED_HOSTS` when you expose it under a public name), limits each business to
`MCP_RATE_PER_MINUTE` calls a minute, and shares the daily message cap with the website widget.

### Simulated Alexa+

With `DJANGO_DEBUG=True`, open `http://localhost:8001/alexa/?key=pk_YOUR_KEY`. The page plays the part of
Alexa+ (speech input in Chrome or Edge, spoken answers) and calls the MCP server like a real assistant
would. The side panel shows each tool call, its timing and the passages found. This is a simulation for
demonstration. Real Alexa+ deployment would add OAuth 2.1 account linking, which is not built yet.

## License

MIT. See `LICENSE`.
