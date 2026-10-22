/*!
 * Parlo chat widget. Add to any website:
 *
 *   <script src="https://YOUR-PARLO-HOST/widget.js" data-bot-key="pk_..." async></script>
 *
 * Optional attributes: data-color="#4f46e5"  data-position="right|left"  data-title="Chat with us"
 * No dependencies. Styles live in a Shadow DOM so the host page cannot break them.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script || window.__parloLoaded) return;
  window.__parloLoaded = true;

  var key = (script.getAttribute("data-bot-key") || "").trim();
  if (!key) {
    console.warn("[Parlo] The data-bot-key attribute is missing.");
    return;
  }

  var apiBase = new URL(script.src, window.location.href).origin;
  var colorAttr = script.getAttribute("data-color") || "";
  var color = /^#[0-9a-fA-F]{3,8}$/.test(colorAttr) ? colorAttr : "#4f46e5";
  var side = script.getAttribute("data-position") === "left" ? "left" : "right";
  var titleAttr = (script.getAttribute("data-title") || "").trim();
  var storageKey = "parlo:" + key;

  function readStore() {
    try { return window.sessionStorage.getItem(storageKey); } catch (e) { return null; }
  }
  function writeStore(value) {
    try {
      if (value) window.sessionStorage.setItem(storageKey, value);
      else window.sessionStorage.removeItem(storageKey);
    } catch (e) { /* storage can be blocked; the chat still works without it */ }
  }

  var conversationId = readStore();
  var busy = false;
  var open = false;

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}",
    ".root{--accent:" + color + ";--bg:#fff;--fg:#1f2937;--muted:#6b7280;--bubble:#f3f4f6;--border:#e5e7eb;",
    "position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;color:var(--fg)}",
    "@media (prefers-color-scheme:dark){.root{--bg:#1f2937;--fg:#f3f4f6;--muted:#9ca3af;--bubble:#374151;--border:#374151}}",
    ".launcher{width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;background:var(--accent);color:#fff;",
    "box-shadow:0 6px 20px rgba(0,0,0,.25);display:flex;align-items:center;justify-content:center}",
    ".launcher:focus-visible,.send:focus-visible,.close:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}",
    ".launcher svg{width:26px;height:26px}",
    ".panel{position:absolute;bottom:68px;" + side + ":0;width:360px;max-width:calc(100vw - 32px);",
    "height:min(540px,calc(100vh - 110px));background:var(--bg);border:1px solid var(--border);border-radius:16px;",
    "box-shadow:0 12px 40px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden}",
    ".panel.open{display:flex}",
    ".header{background:var(--accent);color:#fff;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:8px}",
    ".title{font-weight:600;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".close{background:transparent;border:0;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:4px 8px;border-radius:6px}",
    ".log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}",
    ".msg{max-width:85%;padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}",
    ".msg.bot{background:var(--bubble);align-self:flex-start;border-bottom-left-radius:4px}",
    ".msg.user{background:var(--accent);color:#fff;align-self:flex-end;border-bottom-right-radius:4px}",
    ".msg.error{background:#fef2f2;color:#991b1b;align-self:flex-start;border:1px solid #fecaca}",
    ".src{font-size:11px;color:var(--muted);margin-top:6px}",
    ".typing{display:flex;gap:4px;align-items:center;padding:12px}",
    ".dot{width:6px;height:6px;border-radius:50%;background:var(--muted);animation:b 1.2s infinite ease-in-out}",
    ".dot:nth-child(2){animation-delay:.15s}.dot:nth-child(3){animation-delay:.3s}",
    "@keyframes b{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-4px);opacity:1}}",
    "@media (prefers-reduced-motion:reduce){.dot{animation:none}}",
    ".form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--border);align-items:flex-end}",
    ".input{flex:1;resize:none;border:1px solid var(--border);border-radius:12px;padding:9px 12px;font-size:14px;",
    "max-height:96px;background:var(--bg);color:var(--fg);line-height:1.4}",
    ".input:focus{outline:2px solid var(--accent);outline-offset:0}",
    ".send{background:var(--accent);color:#fff;border:0;border-radius:12px;padding:0 14px;height:38px;font-size:14px;cursor:pointer}",
    ".send:disabled,.input:disabled{opacity:.6;cursor:not-allowed}",
    ".foot{font-size:10px;text-align:center;color:var(--muted);padding:0 0 8px}",
    ".foot a{color:inherit}"
  ].join("");

  var host = document.createElement("div");
  host.setAttribute("data-parlo-widget", "");
  var shadow = host.attachShadow({ mode: "open" });
  var style = document.createElement("style");
  style.textContent = CSS;

  function el(tag, className, attrs) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (attrs) for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  var root = el("div", "root");
  var launcher = el("button", "launcher", {
    type: "button", "aria-label": "Open chat", "aria-expanded": "false"
  });
  launcher.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  var panel = el("div", "panel", { role: "dialog", "aria-label": "Chat" });
  var header = el("div", "header");
  var title = el("div", "title");
  title.textContent = titleAttr || "Chat with us";
  var closeBtn = el("button", "close", { type: "button", "aria-label": "Close chat" });
  closeBtn.textContent = "\u00d7";
  header.appendChild(title);
  header.appendChild(closeBtn);

  var log = el("div", "log", { role: "log", "aria-live": "polite" });
  var form = el("form", "form");
  var input = el("textarea", "input", {
    rows: "1", maxlength: "1000", placeholder: "Type your question...", "aria-label": "Your message"
  });
  var send = el("button", "send", { type: "submit" });
  send.textContent = "Send";
  form.appendChild(input);
  form.appendChild(send);
  var foot = el("div", "foot");
  foot.textContent = "Powered by Parlo";

  panel.appendChild(header);
  panel.appendChild(log);
  panel.appendChild(form);
  panel.appendChild(foot);
  root.appendChild(panel);
  root.appendChild(launcher);
  shadow.appendChild(style);
  shadow.appendChild(root);

  function addMessage(kind, text, sources) {
    var bubble = el("div", "msg " + kind);
    bubble.textContent = text; // text only, never HTML, so answers cannot inject markup
    if (sources && sources.length) {
      var src = el("div", "src");
      src.textContent = "Source: " + sources.join(", ");
      bubble.appendChild(src);
    }
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  function addTyping() {
    var bubble = el("div", "msg bot typing", { "aria-label": "The assistant is typing" });
    for (var i = 0; i < 3; i++) bubble.appendChild(el("span", "dot"));
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  function setOpen(value) {
    open = value;
    panel.classList.toggle("open", open);
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) input.focus();
    else launcher.focus();
  }

  function request(path, options) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 60000);
    options = options || {};
    options.headers = Object.assign({ "X-Bot-Key": key }, options.headers || {});
    options.signal = controller.signal;
    return fetch(apiBase + path, options).then(
      function (response) {
        clearTimeout(timer);
        return response.json().catch(function () { return {}; }).then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
      },
      function (error) { clearTimeout(timer); throw error; }
    );
  }

  function sendMessage(text) {
    if (busy) return;
    busy = true;
    input.disabled = true;
    send.disabled = true;
    addMessage("user", text);
    var typing = addTyping();

    var body = { message: text };
    if (conversationId) body.conversation_id = conversationId;

    request("/api/public/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (result) {
      typing.remove();
      if (result.ok) {
        conversationId = result.data.conversation_id;
        writeStore(conversationId);
        addMessage("bot", result.data.answer, result.data.sources);
      } else if (result.status === 404) {
        conversationId = null;
        writeStore(null);
        addMessage("error", "That conversation expired. Please send your message again.");
      } else {
        addMessage("error", result.data.detail || result.data.message ||
          "Something went wrong. Please try again.");
      }
    }).catch(function () {
      typing.remove();
      addMessage("error", "Could not reach the assistant. Check your connection and try again.");
    }).then(function () {
      busy = false;
      input.disabled = false;
      send.disabled = false;
      if (open) input.focus();
    });
  }

  launcher.addEventListener("click", function () { setOpen(!open); });
  closeBtn.addEventListener("click", function () { setOpen(false); });
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Escape") setOpen(false);
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    sendMessage(text);
  });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 96) + "px";
  });

  // Load the bot's name and greeting. If the key is wrong or this site is not
  // allowed, the widget simply does not appear.
  request("/api/public/bot/", { method: "GET" }).then(function (result) {
    if (!result.ok) {
      console.warn("[Parlo] Widget not shown: " + (result.data.detail || "request failed (" + result.status + ")"));
      return;
    }
    if (!titleAttr) title.textContent = result.data.name;
    addMessage("bot", result.data.welcome_message);
    document.body.appendChild(host);
  }).catch(function () {
    console.warn("[Parlo] Widget not shown: could not reach " + apiBase);
  });
})();
