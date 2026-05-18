(function () {
  "use strict";

  var state = {
    page: "handoffs",
    handoffs: [],
    handoffsFilter: "",
    history: [],
    quickActions: [],
    faqs: [],
    linkRules: [],
    currentHandoff: null,
    editingFaqId: null,
    editingLinkRuleId: null,
  };

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (opts.body && !opts.headers["Content-Type"]) opts.headers["Content-Type"] = "application/json";
    return fetch(path, opts).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error("HTTP " + r.status + ": " + t); });
      var ct = r.headers.get("content-type") || "";
      return ct.indexOf("application/json") >= 0 ? r.json() : r.text();
    });
  }

  function escapeHTML(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function emptyState(opts) {
    return (
      '<div class="empty">' +
      '  <div class="empty-icon">' + escapeHTML(opts.icon || "✨") + '</div>' +
      '  <div class="empty-title">' + escapeHTML(opts.title || "Nothing here yet") + '</div>' +
      '  <div class="empty-hint">' + escapeHTML(opts.hint || "") + '</div>' +
      '</div>'
    );
  }

  function pageHero(opts) {
    var actions = opts.actions || "";
    return (
      '<div class="page-hero">' +
      '  <div class="page-hero-icon">' + escapeHTML(opts.icon || "✨") + '</div>' +
      '  <div class="page-hero-text">' +
      '    <h2 class="page-hero-title">' + escapeHTML(opts.title || "") + '</h2>' +
      '    <p class="page-hero-subtitle">' + escapeHTML(opts.subtitle || "") + '</p>' +
      '  </div>' +
      '  <div class="page-hero-actions">' + actions + '</div>' +
      '</div>'
    );
  }

  function avatarFor(name) {
    var initials = (name || "?").trim().split(/\s+/).map(function (w) { return w[0] || ""; }).join("").slice(0, 2).toUpperCase() || "?";
    // Deterministic bucket 1-5 from name hash so the same person keeps the same color.
    var h = 0;
    for (var i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
    var bucket = (Math.abs(h) % 5) + 1;
    return '<div class="avatar avatar-' + bucket + '">' + escapeHTML(initials) + '</div>';
  }

  function timeAgo(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      if (isNaN(+d)) return iso;
      var secs = Math.round((Date.now() - d) / 1000);
      if (secs < 60) return "just now";
      if (secs < 3600) return Math.round(secs / 60) + " min ago";
      if (secs < 86400) return Math.round(secs / 3600) + " h ago";
      if (secs < 2592000) return Math.round(secs / 86400) + " d ago";
      return d.toLocaleDateString();
    } catch (e) { return iso; }
  }

  function showPage(name) {
    state.page = name;
    $$(".nav-item").forEach(function (n) { n.classList.toggle("active", n.getAttribute("data-page") === name); });
    $$(".page").forEach(function (p) {
      p.style.display = p.getAttribute("data-page") === name ? "" : "none";
    });
    if (name === "handoffs") loadHandoffs();
    else if (name === "history") loadHistory();
    else if (name === "quick-actions") loadQuickActions();
    else if (name === "faq") loadFaqs();
    else if (name === "link-rules") loadLinkRules();
    else if (name === "analytics") loadAnalytics();
    else if (name === "reindex") loadIndexStatus();
  }

  /* HANDOFFS */
  function loadHandoffs() {
    var url = "/api/admin/handoffs?limit=200";
    if (state.handoffsFilter) url += "&status=" + encodeURIComponent(state.handoffsFilter);
    api(url)
      .then(function (items) {
        state.handoffs = items || [];
        var openCount = state.handoffs.filter(function (h) { return h.status === "open"; }).length;
        var badge = $("#handoff-badge");
        badge.textContent = openCount;
        badge.style.display = openCount > 0 ? "" : "none";
        renderHandoffs();
      })
      .catch(function (e) { renderError("#handoffs-list", e); });
  }

  function renderHandoffs() {
    var html = state.handoffs.map(function (h) {
      var contact = h.contact || {};
      var name = contact.name || "Anonymous";
      var msgCount = (h.messages || []).length;
      return (
        '<div class="request-item" data-id="' + escapeHTML(h.id) + '">' +
        avatarFor(name) +
        '  <div class="request-body">' +
        '    <div class="request-head">' +
        '      <div><span class="request-name">' + escapeHTML(name) + '</span>' +
        '        <span class="request-email">' + escapeHTML(contact.email || "—") + '</span></div>' +
        '      <span class="li-status ' + escapeHTML(h.status) + '">' + escapeHTML(h.status) + '</span>' +
        '    </div>' +
        '    <div class="request-message">' + escapeHTML(h.user_message || "—") + '</div>' +
        '    <div class="request-meta">' +
        '      <span class="request-meta-item">🕐 ' + escapeHTML(timeAgo(h.created_at)) + '</span>' +
        '      <span class="request-meta-item">💬 ' + msgCount + ' message' + (msgCount === 1 ? '' : 's') + '</span>' +
        '      <span class="request-meta-item">📌 ' + escapeHTML((h.reason || "—").replace(/_/g, " ")) + '</span>' +
        '    </div>' +
        '  </div>' +
        '</div>'
      );
    }).join("") || emptyState({
      icon: "📭",
      title: "No support requests yet",
      hint: "When users submit the “Contact a human” form in the chat widget, their request will appear here.",
    });
    $("#handoffs-list").innerHTML = html;
    $$("#handoffs-list .request-item").forEach(function (el) {
      el.addEventListener("click", function () { openHandoff(el.getAttribute("data-id")); });
    });
  }

  function openHandoff(id) {
    api("/api/admin/handoffs/" + encodeURIComponent(id))
      .then(function (h) {
        state.currentHandoff = h;
        $("#handoff-modal").style.display = "flex";
        var contact = h.contact || {};
        var msgs = (h.messages || []).map(function (m) {
          return '<div class="msg ' + escapeHTML(m.role) + '">' +
                 '  <div class="role">' + escapeHTML(m.operator_name || m.role) + ' · ' + escapeHTML(m.created_at || "") + '</div>' +
                 escapeHTML(m.text || "") +
                 '</div>';
        }).join("");
        $("#handoff-detail").innerHTML =
          '<p><strong>From:</strong> ' + escapeHTML(contact.name || "Anonymous") + ' (' + escapeHTML(contact.email || "—") + ')</p>' +
          '<p><strong>Status:</strong> ' + escapeHTML(h.status) + ' · <strong>AI:</strong> ' + (h.ai_enabled ? "enabled" : "disabled") + '</p>' +
          '<p><strong>Session:</strong> ' + escapeHTML(h.session_id || "—") + '</p>' +
          msgs;
      })
      .catch(function (e) { alert(e.message); });
  }

  function closeHandoffModal() { $("#handoff-modal").style.display = "none"; state.currentHandoff = null; }

  function sendReply() {
    var h = state.currentHandoff; if (!h) return;
    var msg = $("#handoff-reply").value.trim();
    if (!msg) return;
    api("/api/admin/handoffs/" + encodeURIComponent(h.id) + "/reply", {
      method: "POST",
      body: JSON.stringify({ message: msg, operator_name: "Copernicus Team" }),
    })
      .then(function () { $("#handoff-reply").value = ""; openHandoff(h.id); loadHandoffs(); })
      .catch(function (e) { alert(e.message); });
  }

  function toggleAi() {
    var h = state.currentHandoff; if (!h) return;
    api("/api/admin/handoffs/" + encodeURIComponent(h.id) + "/ai-mode", {
      method: "POST",
      body: JSON.stringify({ ai_enabled: !h.ai_enabled }),
    })
      .then(function () { openHandoff(h.id); })
      .catch(function (e) { alert(e.message); });
  }

  function resolveHandoff() {
    var h = state.currentHandoff; if (!h) return;
    var note = prompt("Resolution note (optional):", "");
    if (note === null) return;
    api("/api/admin/handoffs/" + encodeURIComponent(h.id) + "/resolve", {
      method: "POST",
      body: JSON.stringify({ note: note }),
    })
      .then(function () { closeHandoffModal(); loadHandoffs(); })
      .catch(function (e) { alert(e.message); });
  }

  /* HISTORY */
  function loadHistory() {
    var q = $("#history-search").value.trim();
    var url = "/api/admin/history?limit=200";
    if (q) url += "&q=" + encodeURIComponent(q);
    api(url)
      .then(function (items) {
        state.history = items || [];
        renderHistory();
      })
      .catch(function (e) { renderError("#history-list", e); });
  }

  function renderHistory() {
    var html = state.history.map(function (s) {
      var sat = s.latest_satisfaction;
      var satBadge = sat === "yes"
        ? '<span class="sat-badge yes">👍 helpful</span>'
        : sat === "no" ? '<span class="sat-badge no">👎 not helpful</span>' : "";
      var shortSid = (s.session_id || "").length > 18
        ? s.session_id.slice(0, 8) + "…" + s.session_id.slice(-6)
        : s.session_id;
      return (
        '<div class="session-item" data-sid="' + escapeHTML(s.session_id) + '">' +
        '  <div class="session-head">' +
        '    <div style="display:flex;gap:8px;align-items:center">' +
        '      <span class="session-id">' + escapeHTML(shortSid) + '</span>' +
                satBadge +
        '    </div>' +
        '    <div class="session-stats">' +
        '      <span class="session-stat">💬 ' + s.message_count + '</span>' +
        '      <span class="session-stat">🕐 ' + escapeHTML(timeAgo(s.last_activity_at)) + '</span>' +
        '    </div>' +
        '  </div>' +
        '  <div class="session-preview">' + escapeHTML(s.preview || "—") + '</div>' +
        '</div>'
      );
    }).join("") || emptyState({
      icon: "💬",
      title: "No chat sessions yet",
      hint: "Sessions appear here once visitors start chatting with the assistant.",
    });
    $("#history-list").innerHTML = html;
    $$("#history-list .session-item").forEach(function (el) {
      el.addEventListener("click", function () { openSessionLog(el.getAttribute("data-sid")); });
    });
  }

  function openSessionLog(sid) {
    api("/api/admin/sessions/" + encodeURIComponent(sid) + "?limit=200")
      .then(function (data) {
        state.currentHandoff = null;
        $("#handoff-modal").style.display = "flex";
        $("#handoff-detail").innerHTML =
          '<p><strong>Session:</strong> ' + escapeHTML(sid) + '</p>' +
          (data.items || []).map(function (m) {
            return '<div class="msg ' + escapeHTML(m.role) + '">' +
                   '  <div class="role">' + escapeHTML(m.role) + ' · ' + escapeHTML(m.ts || "") + '</div>' +
                   escapeHTML(m.text || "") +
                   '</div>';
          }).join("");
      })
      .catch(function (e) { alert(e.message); });
  }

  /* QUICK ACTIONS */
  function loadQuickActions() {
    api("/api/admin/quick-actions")
      .then(function (items) {
        state.quickActions = items || [];
        renderQuickActions();
      })
      .catch(function (e) { renderError("#quick-actions-list", e); });
  }

  function renderQuickActions() {
    var html = state.quickActions.map(function (qa, idx) {
      return (
        '<div class="qa-card" data-idx="' + idx + '">' +
        '  <div class="qa-num">' + (idx + 1) + '</div>' +
        '  <textarea class="qa-q" placeholder="Question shown to user">' + escapeHTML(qa.question) + '</textarea>' +
        '  <textarea class="qa-a" placeholder="Optional canned answer (if empty, the bot answers normally)">' + escapeHTML(qa.answer) + '</textarea>' +
        '  <label class="qa-toggle"><input type="checkbox" class="qa-enabled" ' + (qa.enabled ? "checked" : "") + ' /><span>Enabled</span></label>' +
        '  <button class="qa-delete-btn qa-delete" type="button" title="Remove">✕</button>' +
        '</div>'
      );
    }).join("");
    if (!html) {
      html = emptyState({
        icon: "⚡",
        title: "No quick actions",
        hint: "Add suggested questions to surface in the welcome screen of the chat widget.",
      });
    }
    $("#quick-actions-list").innerHTML = html;
    $$(".qa-delete").forEach(function (b) {
      b.addEventListener("click", function () {
        var idx = parseInt(b.closest(".qa-card").getAttribute("data-idx"), 10);
        state.quickActions.splice(idx, 1);
        renderQuickActions();
      });
    });
  }

  function addQuickAction() {
    state.quickActions.push({
      id: "qa_" + Date.now().toString(36),
      question: "",
      answer: "",
      enabled: true,
      sort_order: state.quickActions.length + 1,
    });
    renderQuickActions();
  }

  function saveQuickActions() {
    $$(".qa-card").forEach(function (row, idx) {
      var qa = state.quickActions[idx]; if (!qa) return;
      qa.question = row.querySelector(".qa-q").value;
      qa.answer = row.querySelector(".qa-a").value;
      qa.enabled = row.querySelector(".qa-enabled").checked;
      qa.sort_order = idx + 1;
    });
    api("/api/admin/quick-actions", {
      method: "PUT",
      body: JSON.stringify({ items: state.quickActions }),
    })
      .then(function (items) { state.quickActions = items; renderQuickActions(); alert("Saved."); })
      .catch(function (e) { alert(e.message); });
  }

  /* FAQ */
  function loadFaqs() {
    api("/api/admin/faq")
      .then(function (items) { state.faqs = items || []; renderFaqs(); })
      .catch(function (e) { renderError("#faq-list", e); });
  }

  function renderFaqs() {
    var html = state.faqs.map(function (f) {
      return (
        '<div class="faq-card" data-id="' + escapeHTML(f.id) + '">' +
        '  <div class="faq-q">' + escapeHTML(f.question) + '</div>' +
        '  <div class="faq-a">' + escapeHTML(f.answer || "—") + '</div>' +
        '  <div class="faq-actions">' +
        '    <button class="btn btn-secondary faq-edit">✎ Edit</button>' +
        '    <button class="btn btn-ghost faq-delete">🗑 Delete</button>' +
        '  </div>' +
        '</div>'
      );
    }).join("") || emptyState({
      icon: "❓",
      title: "No manual FAQ entries",
      hint: "Add custom Q&A above. They’ll be merged into the retrieval index next to the crawled site content.",
    });
    $("#faq-list").innerHTML = html;
    $$(".faq-edit").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = b.closest(".faq-card").getAttribute("data-id");
        var f = state.faqs.find(function (x) { return x.id === id; });
        if (!f) return;
        state.editingFaqId = id;
        $("#faq-question").value = f.question; $("#faq-answer").value = f.answer;
        $("#cancel-faq-edit").style.display = "";
      });
    });
    $$(".faq-delete").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = b.closest(".faq-card").getAttribute("data-id");
        if (!confirm("Delete this FAQ?")) return;
        api("/api/admin/faq/" + encodeURIComponent(id), { method: "DELETE" })
          .then(loadFaqs)
          .catch(function (err) { alert(err.message); });
      });
    });
  }

  function saveFaq() {
    var body = JSON.stringify({
      question: $("#faq-question").value.trim(),
      answer: $("#faq-answer").value.trim(),
    });
    var url = "/api/admin/faq" + (state.editingFaqId ? "/" + encodeURIComponent(state.editingFaqId) : "");
    var method = state.editingFaqId ? "PUT" : "POST";
    api(url, { method: method, body: body })
      .then(function () {
        $("#faq-question").value = ""; $("#faq-answer").value = "";
        state.editingFaqId = null; $("#cancel-faq-edit").style.display = "none";
        loadFaqs();
      })
      .catch(function (e) { alert(e.message); });
  }

  function cancelFaqEdit() {
    state.editingFaqId = null;
    $("#faq-question").value = ""; $("#faq-answer").value = "";
    $("#cancel-faq-edit").style.display = "none";
  }

  /* LINK RULES */
  function loadLinkRules() {
    api("/api/admin/link-rules")
      .then(function (items) { state.linkRules = items || []; renderLinkRules(); })
      .catch(function (e) { renderError("#link-rules-list", e); });
  }

  function renderLinkRules() {
    var html = state.linkRules.map(function (r) {
      var modeIcon = r.mode === "disable" ? "🚫" : "🔗";
      return (
        '<div class="link-rule mode-' + escapeHTML(r.mode) + '" data-id="' + escapeHTML(r.id) + '">' +
        '  <div class="link-rule-icon">' + modeIcon + '</div>' +
        '  <div class="link-rule-body">' +
        '    <div class="link-rule-head">' +
        '      <span class="link-rule-pattern">' + escapeHTML(r.question_pattern) + '</span>' +
        '      <span class="link-rule-mode">' + escapeHTML(r.mode) + (r.enabled ? '' : ' · off') + '</span>' +
        '    </div>' +
        '    <div class="link-rule-url">' + escapeHTML(r.url || "—") + (r.note ? " · " + escapeHTML(r.note) : "") + '</div>' +
        '  </div>' +
        '  <div class="link-rule-actions">' +
        '    <button class="btn btn-secondary lr-edit">✎ Edit</button>' +
        '    <button class="btn btn-ghost lr-delete">🗑</button>' +
        '  </div>' +
        '</div>'
      );
    }).join("") || emptyState({
      icon: "🔗",
      title: "No link rules",
      hint: "Add a rule to override or hide the source link the bot suggests for certain question patterns.",
    });
    $("#link-rules-list").innerHTML = html;
    $$(".lr-edit").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.closest(".link-rule").getAttribute("data-id");
        var r = state.linkRules.find(function (x) { return x.id === id; });
        if (!r) return;
        state.editingLinkRuleId = id;
        $("#lr-pattern").value = r.question_pattern;
        $("#lr-url").value = r.url || "";
        $("#lr-note").value = r.note || "";
        $("#lr-mode").value = r.mode;
        $("#cancel-lr-edit").style.display = "";
      });
    });
    $$(".lr-delete").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.closest(".link-rule").getAttribute("data-id");
        if (!confirm("Delete this rule?")) return;
        api("/api/admin/link-rules/" + encodeURIComponent(id), { method: "DELETE" })
          .then(loadLinkRules).catch(function (e) { alert(e.message); });
      });
    });
  }

  function saveLinkRule() {
    var body = JSON.stringify({
      question_pattern: $("#lr-pattern").value.trim(),
      url: $("#lr-url").value.trim(),
      note: $("#lr-note").value.trim(),
      mode: $("#lr-mode").value,
      enabled: true,
    });
    var url = "/api/admin/link-rules" + (state.editingLinkRuleId ? "/" + encodeURIComponent(state.editingLinkRuleId) : "");
    var method = state.editingLinkRuleId ? "PUT" : "POST";
    api(url, { method: method, body: body })
      .then(function () {
        $("#lr-pattern").value = ""; $("#lr-url").value = "";
        $("#lr-note").value = ""; $("#lr-mode").value = "manual";
        state.editingLinkRuleId = null; $("#cancel-lr-edit").style.display = "none";
        loadLinkRules();
      })
      .catch(function (e) { alert(e.message); });
  }

  function cancelLrEdit() {
    state.editingLinkRuleId = null;
    $("#lr-pattern").value = ""; $("#lr-url").value = "";
    $("#lr-note").value = ""; $("#lr-mode").value = "manual";
    $("#cancel-lr-edit").style.display = "none";
  }

  /* ANALYTICS */
  function loadAnalytics() {
    var days = parseInt($("#analytics-days").value, 10) || 0;
    api("/api/admin/analytics?days=" + days)
      .then(function (data) {
        var yes = (data.satisfaction_counts && data.satisfaction_counts.yes) || 0;
        var no = (data.satisfaction_counts && data.satisfaction_counts.no) || 0;
        var satTotal = yes + no;
        var satPct = satTotal ? Math.round((yes / satTotal) * 100) : null;
        var fields = [
          { label: "Total messages", value: data.total_messages, icon: "💬", variant: "" },
          { label: "Unique sessions", value: data.unique_sessions, icon: "👥", variant: "orange" },
          { label: "Needs human", value: data.needs_human, icon: "🙋", variant: "purple", sub: data.needs_human ? "review in support" : "" },
          { label: "Errors", value: data.error_count, icon: "⚠️", variant: data.error_count ? "red" : "", sub: data.error_count ? "investigate" : "all good" },
          { label: "Avg latency", value: (data.avg_latency_ms || 0) + " ms", icon: "⏱️", variant: "" },
          { label: "Satisfaction", value: satPct == null ? "—" : (satPct + "%"), icon: "⭐", variant: "green", sub: satTotal ? ("👍 " + yes + "   👎 " + no) : "no ratings yet" },
        ];
        $("#analytics-summary").innerHTML = fields.map(function (f) {
          return '<div class="metric ' + (f.variant ? "metric-" + f.variant : "") + '">' +
                 '  <div class="metric-icon">' + f.icon + '</div>' +
                 '  <div class="metric-label">' + escapeHTML(f.label) + '</div>' +
                 '  <div class="metric-value">' + escapeHTML(String(f.value == null ? 0 : f.value)) + '</div>' +
                 (f.sub ? '<div class="metric-sub">' + escapeHTML(f.sub) + '</div>' : "") +
                 '</div>';
        }).join("");

        var top = (data.top_questions || []).map(function (q, idx) {
          var rank = idx < 9 ? "0" + (idx + 1) : "" + (idx + 1);
          return '<div class="top-q-item">' +
                 '  <div class="top-q-rank">' + rank + '</div>' +
                 '  <div class="top-q-text">' + escapeHTML(q.question) + '</div>' +
                 '  <div class="top-q-count">' + q.count + '×</div>' +
                 '</div>';
        }).join("") || emptyState({
          icon: "📊",
          title: "No analytics yet",
          hint: "Once visitors start asking questions, the most-frequent ones will show up here.",
        });
        $("#analytics-top").innerHTML = top;
      })
      .catch(function (e) { renderError("#analytics-summary", e); });
  }

  /* REINDEX */
  function _fmtBytes(n) {
    if (!n) return "0 B";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
  function _fmtDate(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      if (isNaN(+d)) return iso;
      var now = new Date();
      var secs = Math.round((now - d) / 1000);
      var rel;
      if (secs < 60) rel = secs + "s ago";
      else if (secs < 3600) rel = Math.round(secs / 60) + "m ago";
      else if (secs < 86400) rel = Math.round(secs / 3600) + "h ago";
      else rel = Math.round(secs / 86400) + "d ago";
      return d.toLocaleString() + " (" + rel + ")";
    } catch (e) { return iso; }
  }

  function loadIndexStatus() {
    $("#index-stats").innerHTML = '<div class="hint">Loading…</div>';
    $("#index-pages-list").innerHTML = '<div class="hint">Loading…</div>';
    api("/api/admin/index-status")
      .then(function (data) {
        var lastReindex = data.runtime && data.runtime.last_reindex_at;
        var modified = (data.chunks_file && data.chunks_file.modified_at) || (data.embeddings_file && data.embeddings_file.modified_at);
        var fields = [
          { label: "Pages indexed", value: data.documents_total, icon: "📄", variant: "" },
          { label: "Chunks", value: data.chunks_total, icon: "🧩", variant: "orange" },
          { label: "Embedding size", value: _fmtBytes(data.embeddings_file && data.embeddings_file.size_bytes), icon: "💾", variant: "purple" },
        ];
        $("#index-stats").innerHTML = fields.map(function (f) {
          return '<div class="metric ' + (f.variant ? "metric-" + f.variant : "") + '">' +
                 '  <div class="metric-icon">' + f.icon + '</div>' +
                 '  <div class="metric-label">' + escapeHTML(f.label) +
                 '</div><div class="metric-value">' + escapeHTML(String(f.value == null ? "—" : f.value)) + '</div></div>';
        }).join("");

        $("#index-meta").innerHTML =
          '<div class="meta-row"><span class="meta-label">Site root</span><span class="meta-value">' + escapeHTML(data.site_root || "—") + '</span></div>' +
          '<div class="meta-row"><span class="meta-label">Crawl paths</span><span class="meta-value">' + escapeHTML(data.crawl_paths || "—") + '</span></div>' +
          '<div class="meta-row"><span class="meta-label">Last reindex</span><span class="meta-value">' + escapeHTML(_fmtDate(lastReindex || modified)) + '</span></div>';

        var docs = data.documents || [];
        $("#index-pages-count").textContent = docs.length ? docs.length + " pages" : "";
        if (!docs.length) {
          $("#index-pages-list").innerHTML = emptyState({
            icon: "🗂️",
            title: "Index is empty",
            hint: "Run a full reindex to populate the search index with content from copernicusberlin.org/en.",
          });
        } else {
          $("#index-pages-list").innerHTML = docs.map(function (d) {
            return (
              '<div class="reindex-page-row">' +
              '  <div class="rp-text">' +
              '    <div class="rp-title">' + escapeHTML(d.title || "(untitled)") + '</div>' +
              '    <a class="rp-url" href="' + escapeHTML(d.url) + '" target="_blank" rel="noopener">' + escapeHTML(d.url) + '</a>' +
              '  </div>' +
              '  <div class="rp-stats">' +
              '    <span>' + d.chunks + ' chunks</span>' +
              '    <span>' + _fmtBytes(d.text_chars) + ' text</span>' +
              '  </div>' +
              '</div>'
            );
          }).join("");
        }
      })
      .catch(function (e) {
        $("#index-stats").innerHTML = '<div class="hint" style="color:var(--red)">' + escapeHTML(e.message) + '</div>';
        $("#index-pages-list").innerHTML = "";
        $("#index-meta").innerHTML = "";
      });
  }

  function runReindex() {
    var mode = (document.querySelector('input[name="reindex-mode"]:checked') || {}).value || "full";
    var full = mode === "full";
    var btn = $("#run-reindex");
    var status = $("#reindex-status");
    var output = $("#reindex-output");
    btn.disabled = true;
    btn.textContent = "Running…";
    status.style.display = "";
    status.textContent = full
      ? "Crawling copernicusberlin.org and rebuilding embeddings… this takes 3–5 minutes. You can leave this page open."
      : "Re-embedding existing pages… ~30 seconds.";
    output.style.display = "none";
    output.textContent = "";
    api("/api/admin/reindex", {
      method: "POST",
      body: JSON.stringify({ full_crawl: full }),
    })
      .then(function (data) {
        output.style.display = "";
        output.textContent = "✓ Indexed " + data.indexed_documents + " documents into " + data.indexed_chunks + " chunks.";
        status.textContent = "Reindex complete.";
        btn.disabled = false; btn.textContent = "Start reindex";
        loadIndexStatus();
      })
      .catch(function (e) {
        output.style.display = "";
        output.textContent = "✗ Failed: " + e.message;
        status.textContent = "Reindex failed.";
        btn.disabled = false; btn.textContent = "Start reindex";
      });
  }

  function renderError(sel, e) {
    $(sel).innerHTML = '<div class="hint" style="color:var(--red)">' + escapeHTML(e.message || String(e)) + '</div>';
  }

  /* Init */
  document.addEventListener("DOMContentLoaded", function () {
    $$(".nav-item").forEach(function (n) {
      n.addEventListener("click", function (e) { e.preventDefault(); showPage(n.getAttribute("data-page")); });
    });

    $$(".filter").forEach(function (f) {
      f.addEventListener("click", function () {
        state.handoffsFilter = f.getAttribute("data-status") || "";
        $$(".filter").forEach(function (x) { x.classList.toggle("active", x === f); });
        loadHandoffs();
      });
    });

    $("#reload-handoffs").addEventListener("click", loadHandoffs);
    $("#reload-history").addEventListener("click", loadHistory);
    $("#history-search").addEventListener("keydown", function (e) { if (e.key === "Enter") loadHistory(); });
    $("#reload-analytics").addEventListener("click", loadAnalytics);
    $("#analytics-days").addEventListener("change", loadAnalytics);
    $("#close-handoff-modal").addEventListener("click", closeHandoffModal);
    $("#send-reply").addEventListener("click", sendReply);
    $("#toggle-ai").addEventListener("click", toggleAi);
    $("#resolve-handoff").addEventListener("click", resolveHandoff);

    $("#save-quick-actions").addEventListener("click", saveQuickActions);
    $("#add-quick-action").addEventListener("click", addQuickAction);

    $("#save-faq").addEventListener("click", saveFaq);
    $("#cancel-faq-edit").addEventListener("click", cancelFaqEdit);

    $("#save-link-rule").addEventListener("click", saveLinkRule);
    $("#cancel-lr-edit").addEventListener("click", cancelLrEdit);

    $("#run-reindex").addEventListener("click", runReindex);
    var reloadIdx = $("#reload-index-status");
    if (reloadIdx) reloadIdx.addEventListener("click", loadIndexStatus);

    // Open access — load handoffs immediately.
    loadHandoffs();
  });
})();
