(function () {
  "use strict";

  var SESSION_KEY = "cb_session_id";
  var baseUrl = (window.CB_WIDGET_BASE_URL || "").replace(/\/$/, "") || "";

  function api(path) { return (baseUrl || "") + path; }

  // One-time cleanup of legacy keys from an earlier version that stored
  // visitor name/email locally. Keeps the browser tidy for returning users.
  try { localStorage.removeItem("cb_user_name"); localStorage.removeItem("cb_user_email"); } catch (e) {}

  function uuid() {
    if (crypto && crypto.randomUUID) return crypto.randomUUID();
    return "s_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function getSession() {
    try {
      var sid = localStorage.getItem(SESSION_KEY);
      if (!sid) { sid = uuid(); localStorage.setItem(SESSION_KEY, sid); }
      return sid;
    } catch (e) { return uuid(); }
  }

  function escapeHTML(s) {
    return String(s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderMarkdown(text) {
    var html = escapeHTML(text);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Match full URL up to next whitespace, then strip trailing sentence punctuation.
    html = html.replace(/https?:\/\/[^\s<]+/g, function (raw) {
      var trailing = "";
      var m = raw.match(/[.,;:!?)\]}'"]+$/);
      if (m) { trailing = m[0]; raw = raw.slice(0, -trailing.length); }
      return '<a href="' + raw + '" target="_blank" rel="noopener noreferrer">' + raw + "</a>" + trailing;
    });
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  var state = {
    sessionId: getSession(),
    quickActions: [],
    sending: false,
    started: false,
    satisfactionShown: false,
  };

  var root, body, input, send, satisfactionEl, welcomeEl;

  function mount() {
    root = document.getElementById("cb-widget-root");
    if (!root) return;

    var logoSrc = (baseUrl || "") + "/widget/logo.jpg";

    root.innerHTML =
      '<div class="cb-shell" role="region" aria-label="Copernicus Berlin chat">' +
      '  <div class="cb-header">' +
      '    <div class="cb-logo"><img src="' + logoSrc + '" alt="Copernicus Berlin" /></div>' +
      '    <div class="cb-header-text">' +
      '      <div class="cb-title">Copernicus Berlin</div>' +
      '      <div class="cb-subtitle">Ask about our programs &amp; events</div>' +
      '    </div>' +
      '    <div class="cb-header-actions">' +
      '      <button class="cb-icon-btn" id="cb-contact" title="Contact a human">✉</button>' +
      '      <button class="cb-icon-btn" id="cb-reset" title="New chat">↻</button>' +
      '    </div>' +
      '  </div>' +
      '  <div class="cb-body" id="cb-body"></div>' +
      '  <div class="cb-satisfaction" id="cb-satisfaction" style="display:none"></div>' +
      '  <form class="cb-footer" id="cb-form">' +
      '    <input class="cb-input" id="cb-input" placeholder="Type your question…" autocomplete="off" />' +
      '    <button class="cb-send" id="cb-send" type="submit" title="Send" aria-label="Send">➤</button>' +
      '  </form>' +
      '</div>';

    body = document.getElementById("cb-body");
    input = document.getElementById("cb-input");
    send = document.getElementById("cb-send");
    satisfactionEl = document.getElementById("cb-satisfaction");

    document.getElementById("cb-form").addEventListener("submit", onSubmit);
    document.getElementById("cb-reset").addEventListener("click", resetChat);
    document.getElementById("cb-contact").addEventListener("click", function () { openSupportModal(""); });

    loadQuickActions().then(showWelcome);
  }

  function showWelcome() {
    var logoSrc = (baseUrl || "") + "/widget/logo.jpg";
    var chipsHtml = "";
    if (state.quickActions && state.quickActions.length) {
      chipsHtml = '<div class="cb-welcome-chips">' +
        state.quickActions.map(function (qa) {
          return '<button type="button" class="cb-chip-lg" data-q="' + escapeHTML(qa.question) + '">' +
                 escapeHTML(qa.question) + '</button>';
        }).join("") + '</div>';
    }
    welcomeEl = document.createElement("div");
    welcomeEl.className = "cb-welcome";
    welcomeEl.id = "cb-welcome";
    welcomeEl.innerHTML =
      '<div class="cb-welcome-logo"><img src="' + logoSrc + '" alt="Copernicus Berlin" /></div>' +
      '<h3 class="cb-welcome-title">Hi 👋 I\'m the Copernicus Berlin assistant.</h3>' +
      '<p class="cb-welcome-text">Ask me about our programs, scholarships, events, ' +
      'or how to get involved. Pick a question to get started:</p>' +
      chipsHtml;
    body.appendChild(welcomeEl);
    Array.from(welcomeEl.querySelectorAll(".cb-chip-lg")).forEach(function (b) {
      b.addEventListener("click", function () { submitMessage(b.getAttribute("data-q")); });
    });
  }

  function hideWelcome() {
    if (welcomeEl && welcomeEl.parentNode) {
      welcomeEl.parentNode.removeChild(welcomeEl);
      welcomeEl = null;
    }
    state.started = true;
  }

  function appendUser(text) {
    if (!state.started) hideWelcome();
    var el = document.createElement("div");
    el.className = "cb-msg user";
    el.textContent = text;
    body.appendChild(el);
    scrollDown();
  }

  function appendBot(text) {
    if (!state.started) hideWelcome();
    var el = document.createElement("div");
    el.className = "cb-msg bot";
    el.innerHTML = renderMarkdown(text);
    body.appendChild(el);
    scrollDown();
    return el;
  }

  function appendTyping() {
    var el = document.createElement("div");
    el.className = "cb-msg bot cb-typing-wrap";
    el.innerHTML = '<span class="cb-typing"><span></span><span></span><span></span></span>';
    body.appendChild(el);
    scrollDown();
    return el;
  }

  function scrollDown() { body.scrollTop = body.scrollHeight; }

  function loadQuickActions() {
    return fetch(api("/api/quick-actions"))
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (items) { state.quickActions = items || []; })
      .catch(function () { state.quickActions = []; });
  }

  function setSending(v) {
    state.sending = v;
    send.disabled = v;
    input.disabled = v;
  }

  function onSubmit(e) {
    e.preventDefault();
    if (state.sending) return;
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    submitMessage(text);
  }

  function submitMessage(text) {
    appendUser(text);
    setSending(true);
    satisfactionEl.style.display = "none";

    var typing = appendTyping();
    var botEl = null;
    var assembled = "";
    var openedSupport = false;

    fetch(api("/api/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: state.sessionId,
        channel: "web",
      }),
    })
      .then(function (resp) {
        if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";

        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) { return finalize(); }
            buf += decoder.decode(chunk.value, { stream: true });
            var lines = buf.split("\n");
            buf = lines.pop();
            for (var i = 0; i < lines.length; i++) {
              var ln = lines[i].trim();
              if (!ln) continue;
              try {
                var ev = JSON.parse(ln);
                handleEvent(ev);
              } catch (e) { /* ignore parse */ }
            }
            return pump();
          });
        }

        function handleEvent(ev) {
          if (ev.type === "token") {
            if (!botEl) {
              if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
              botEl = appendBot("");
              assembled = "";
            }
            assembled += (ev.text || "");
            botEl.innerHTML = renderMarkdown(assembled);
            scrollDown();
          } else if (ev.type === "ui_action") {
            if (ev.action === "open_support_modal" && !openedSupport) {
              openedSupport = true;
              openSupportModal(ev.prefill_question || text);
            }
          } else if (ev.type === "error") {
            if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
            appendBot("Sorry, something went wrong: " + (ev.message || "unknown error"));
          }
        }

        function finalize() {
          if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
          setSending(false);
          if (assembled && !state.satisfactionShown) showSatisfaction();
        }

        return pump();
      })
      .catch(function (err) {
        if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
        appendBot("Sorry, the assistant is not reachable right now. Please try again later.");
        setSending(false);
      });
  }

  function showSatisfaction() {
    state.satisfactionShown = true;
    satisfactionEl.style.display = "flex";
    satisfactionEl.innerHTML =
      '<span>Was this helpful?</span>' +
      '<button data-r="yes">👍 Yes</button>' +
      '<button data-r="no">👎 No</button>';
    Array.from(satisfactionEl.querySelectorAll("button")).forEach(function (b) {
      b.addEventListener("click", function () { submitSatisfaction(b.getAttribute("data-r")); });
    });
  }

  function submitSatisfaction(value) {
    satisfactionEl.style.display = "none";
    fetch(api("/api/chat/satisfaction"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response: value, session_id: state.sessionId }),
    }).catch(function () {});
    if (value === "no") openSupportModal("");
  }

  function resetChat() {
    fetch(api("/api/chat/reset"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    }).catch(function () {});
    state.sessionId = uuid();
    try { localStorage.setItem(SESSION_KEY, state.sessionId); } catch (e) {}
    state.started = false;
    state.satisfactionShown = false;
    body.innerHTML = "";
    satisfactionEl.style.display = "none";
    showWelcome();
  }

  /* Support / handoff modal */
  function openSupportModal(prefill) {
    var existing = document.getElementById("cb-modal-bg");
    if (existing) existing.remove();
    var bg = document.createElement("div");
    bg.id = "cb-modal-bg";
    bg.className = "cb-modal-bg";
    bg.innerHTML =
      '<div class="cb-modal">' +
      '  <h3>Contact Copernicus Berlin</h3>' +
      '  <p>Leave your name and email. Someone from our team will reply to your email directly.</p>' +
      '  <label>Your name</label>' +
      '  <input id="cb-sf-name" type="text" maxlength="120" autocomplete="off" />' +
      '  <label>Email</label>' +
      '  <input id="cb-sf-email" type="email" maxlength="160" autocomplete="off" />' +
      '  <label>Your question</label>' +
      '  <textarea id="cb-sf-q" maxlength="4000">' + escapeHTML(prefill || "") + '</textarea>' +
      '  <div class="cb-modal-actions">' +
      '    <button class="cb-btn cb-btn-ghost" id="cb-sf-cancel" type="button">Cancel</button>' +
      '    <button class="cb-btn cb-btn-primary" id="cb-sf-send" type="button">Send</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(bg);
    bg.addEventListener("click", function (e) { if (e.target === bg) bg.remove(); });
    document.getElementById("cb-sf-cancel").addEventListener("click", function () { bg.remove(); });
    document.getElementById("cb-sf-send").addEventListener("click", function () {
      var name = document.getElementById("cb-sf-name").value.trim();
      var email = document.getElementById("cb-sf-email").value.trim();
      var q = document.getElementById("cb-sf-q").value.trim();
      if (!name || !email || !q) { alert("Please fill in all fields."); return; }
      fetch(api("/api/chat/support"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, email: email, question: q, session_id: state.sessionId }),
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
        .then(function (resp) {
          bg.remove();
          // Echo the question as a user bubble so the conversation history
          // shows what was submitted.
          appendUser(q);
          appendBot(resp.message || "Thanks! We'll be in touch.");
        })
        .catch(function () {
          bg.remove();
          appendBot("Sorry — could not submit the form. Please try again later.");
        });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
