"""A simulated Alexa+ for demos (development only).

The page at /alexa/ plays the part of Alexa+: it takes a spoken or typed question and,
through POST /alexa/ask/, this view connects to Parlo's MCP server exactly like a real
assistant would (bearer token, list tools, call tools) and returns the answer plus a trace
of the tool calls so the demo can show what happened.
"""
import asyncio
import json
import re
import time

import httpx2
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

KEY_PATTERN = re.compile(r"^pk_[A-Za-z0-9_-]{8,64}$")


def _data(result):
    if result.structured_content:
        return result.structured_content
    text = "".join(getattr(part, "text", "") for part in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return {"message": text}


async def _call_mcp(url, key, question, conversation_id):
    trace = []
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=60)
    async with Client(streamable_http_client(url, http_client=http)) as client:

        async def call(name, args):
            start = time.perf_counter()
            result = await client.call_tool(name, args)
            data = _data(result)
            failed = bool(getattr(result, "is_error", False))
            trace.append(
                {
                    "tool": name,
                    "arguments": args,
                    "ms": round((time.perf_counter() - start) * 1000),
                    "ok": not failed,
                }
            )
            return data, failed

        found, failed = await call("search_knowledge", {"query": question})
        passages = [] if failed else found.get("results", [])
        args = {"question": question}
        if conversation_id:
            args["conversation_id"] = conversation_id
        answer, failed = await call("ask_business_assistant", args)
        if failed:
            raise RuntimeError(answer.get("message") or "The assistant could not answer.")
    return {
        "answer": answer["answer"],
        "conversation_id": answer["conversation_id"],
        "passages": passages,
        "trace": trace,
    }


def call_mcp(url, key, question, conversation_id):
    return asyncio.run(_call_mcp(url, key, question, conversation_id))


@csrf_exempt
@require_POST
def alexa_ask(request):
    if not settings.DEBUG:
        raise Http404()
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    key = str(body.get("key", ""))
    question = str(body.get("question", "")).strip()
    if not KEY_PATTERN.match(key):
        return JsonResponse({"error": "A valid bot key is required."}, status=400)
    if not question or len(question) > 500:
        return JsonResponse({"error": "Ask a question of up to 500 characters."}, status=400)
    try:
        result = call_mcp(settings.ALEXA_SIM_MCP_URL, key, question, body.get("conversation_id"))
    except Exception as exc:
        return JsonResponse({"error": f"Could not reach the MCP server: {type(exc).__name__}"}, status=502)
    return JsonResponse(result)


def alexa_page(request):
    if not settings.DEBUG:
        raise Http404()
    return HttpResponse(PAGE)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alexa+ simulator for Parlo</title>
<style>
  :root { --bg:#0b1020; --panel:#121a30; --line:#223055; --text:#e8eefc; --muted:#8fa0c8; --cyan:#27d3f5; --warn:#ffb454; }
  * { box-sizing: border-box; }
  body { margin:0; background:radial-gradient(1200px 600px at 50% -10%, #16264d 0%, var(--bg) 60%); color:var(--text);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; min-height:100vh; }
  main { max-width:1000px; margin:0 auto; padding:24px 16px 48px; display:grid; gap:20px; grid-template-columns: 1fr; }
  @media (min-width: 860px) { main { grid-template-columns: 1.2fr 1fr; } header { grid-column: 1 / -1; } }
  header h1 { margin:0; font-size:22px; }
  header p { margin:4px 0 0; color:var(--muted); font-size:14px; }
  .badge { display:inline-block; background:#2a1f08; color:var(--warn); border:1px solid #5a4313; border-radius:999px;
           padding:2px 10px; font-size:12px; margin-left:8px; vertical-align:middle; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px; }
  .orb-wrap { display:flex; justify-content:center; padding:8px 0 16px; }
  .orb { width:92px; height:92px; border-radius:50%; border:5px solid var(--cyan); box-shadow:0 0 24px #27d3f566, inset 0 0 18px #27d3f533;
         transition: box-shadow .2s, transform .2s; }
  .orb.listening { animation:pulse 1.2s ease-in-out infinite; }
  .orb.thinking { animation:spin 1s linear infinite; border-top-color:transparent; }
  .orb.speaking { animation:pulse .6s ease-in-out infinite; box-shadow:0 0 40px #27d3f5aa; }
  @keyframes pulse { 50% { transform:scale(1.08); box-shadow:0 0 44px #27d3f5aa; } }
  @keyframes spin { to { transform:rotate(360deg); } }
  #log { height:300px; overflow:auto; display:flex; flex-direction:column; gap:10px; padding:4px; }
  .msg { max-width:85%; padding:10px 14px; border-radius:14px; white-space:pre-wrap; word-wrap:break-word; }
  .you { align-self:flex-end; background:#1c2b57; }
  .alexa { align-self:flex-start; background:#0e3a46; border:1px solid #17586a; }
  .alexa small { display:block; color:var(--muted); margin-top:6px; font-size:12px; }
  form { display:flex; gap:8px; margin-top:12px; }
  input[type=text] { flex:1; background:#0b1228; color:var(--text); border:1px solid var(--line); border-radius:12px; padding:12px 14px; font-size:16px; }
  button { background:var(--cyan); color:#02222b; border:0; border-radius:12px; padding:0 16px; font-weight:600; font-size:15px; cursor:pointer; min-height:44px; }
  button.ghost { background:transparent; color:var(--text); border:1px solid var(--line); }
  button:disabled { opacity:.5; cursor:default; }
  .row { display:flex; gap:8px; align-items:center; margin-top:10px; color:var(--muted); font-size:13px; flex-wrap:wrap; }
  h2 { margin:0 0 10px; font-size:15px; color:var(--muted); font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
  .step { border-left:3px solid var(--cyan); padding:4px 0 4px 12px; margin:0 0 12px; font-size:14px; }
  .step code { color:var(--cyan); }
  .step .ms { color:var(--muted); }
  .passage { background:#0b1228; border:1px solid var(--line); border-radius:10px; padding:8px 10px; margin:6px 0; font-size:13px; color:#c7d3f2; }
  .passage b { color:var(--text); display:block; font-size:12px; margin-bottom:2px; }
  .empty { color:var(--muted); font-size:14px; }
</style>
</head>
<body>
<main>
  <header>
    <h1>Alexa+ simulator <span class="badge">simulated</span></h1>
    <p>This page plays the part of Alexa+. It connects to Parlo's MCP server with the business's key, looks the answer up with the server's tools, and speaks it back.</p>
  </header>

  <section class="card">
    <div class="orb-wrap"><div id="orb" class="orb" aria-hidden="true"></div></div>
    <div id="log" aria-live="polite"></div>
    <form id="form">
      <button type="button" id="mic" class="ghost" title="Speak">Speak</button>
      <input type="text" id="q" placeholder='Ask the business, e.g. "Can I get my money back?"' autocomplete="off" maxlength="500">
      <button type="submit" id="send">Ask</button>
    </form>
    <div class="row">
      <label><input type="checkbox" id="speak" checked> Read answers aloud</label>
      <span id="biz"></span>
    </div>
  </section>

  <section class="card">
    <h2>What Alexa+ did over MCP</h2>
    <div id="trace" class="empty">Ask a question to see the tool calls.</div>
  </section>
</main>

<script>
(function () {
  var params = new URLSearchParams(location.search);
  var key = params.get("key") || "";
  var log = document.getElementById("log");
  var trace = document.getElementById("trace");
  var orb = document.getElementById("orb");
  var input = document.getElementById("q");
  var send = document.getElementById("send");
  var mic = document.getElementById("mic");
  var speak = document.getElementById("speak");
  var conversation = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function state(name) { orb.className = "orb" + (name ? " " + name : ""); }
  function add(who, text, note) {
    var m = el("div", "msg " + who, text);
    if (note) m.appendChild(el("small", "", note));
    log.appendChild(m);
    log.scrollTop = log.scrollHeight;
    return m;
  }

  function drawTrace(data) {
    trace.className = "";
    trace.textContent = "";
    data.trace.forEach(function (t) {
      var step = el("div", "step");
      var line = el("div");
      line.appendChild(el("code", "", t.tool));
      line.appendChild(el("span", "ms", "  " + t.ms + " ms" + (t.ok ? "" : "  (error)")));
      step.appendChild(line);
      step.appendChild(el("div", "ms", JSON.stringify(t.arguments)));
      trace.appendChild(step);
    });
    if (data.passages.length) {
      trace.appendChild(el("div", "empty", "Passages found by search_knowledge:"));
      data.passages.forEach(function (p) {
        var box = el("div", "passage");
        box.appendChild(el("b", "", p.source));
        box.appendChild(document.createTextNode(p.text));
        trace.appendChild(box);
      });
    }
  }

  function say(text, done) {
    if (!speak.checked || !window.speechSynthesis) { done(); return; }
    var u = new SpeechSynthesisUtterance(text);
    u.onend = done; u.onerror = done;
    state("speaking");
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  function ask(question) {
    question = question.trim();
    if (!question) return;
    if (!key) { add("alexa", "Add ?key=YOUR_BOT_KEY to the address of this page."); return; }
    add("you", question);
    input.value = "";
    send.disabled = true;
    state("thinking");
    fetch("/alexa/ask/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key, question: question, conversation_id: conversation })
    }).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, data: data }; });
    }).then(function (res) {
      if (!res.ok) throw new Error(res.data.error || "Something went wrong.");
      conversation = res.data.conversation_id;
      var total = res.data.trace.reduce(function (s, t) { return s + t.ms; }, 0);
      add("alexa", res.data.answer, "via Parlo MCP, " + total + " ms");
      drawTrace(res.data);
      say(res.data.answer, function () { state(""); });
    }).catch(function (err) {
      add("alexa", "Sorry, " + err.message);
      state("");
    }).then(function () { send.disabled = false; input.focus(); });
  }

  document.getElementById("form").addEventListener("submit", function (e) {
    e.preventDefault();
    ask(input.value);
  });

  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    mic.disabled = true;
    mic.title = "Speech input needs Chrome or Edge";
  } else {
    mic.addEventListener("click", function () {
      var rec = new Recognition();
      rec.lang = "en-US";
      rec.interimResults = false;
      state("listening");
      rec.onresult = function (e) { ask(e.results[0][0].transcript); };
      rec.onerror = function () { state(""); };
      rec.onend = function () { if (orb.className.indexOf("listening") > -1) state(""); };
      rec.start();
    });
  }

  fetch("/api/public/bot/", { headers: { "X-Bot-Key": key } }).then(function (r) { return r.json(); })
    .then(function (b) {
      if (b && b.name) {
        document.getElementById("biz").textContent = "Business: " + b.name;
        add("alexa", "Hi, I'm Alexa. You're connected to " + b.name + ". What would you like to know?");
      }
    }).catch(function () {});
  if (!key) add("alexa", "Add ?key=YOUR_BOT_KEY to the address of this page.");
})();
</script>
</body>
</html>
"""