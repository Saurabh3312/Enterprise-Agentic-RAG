const API_BASE = window.location.origin;

const state = {
  route: "dashboard",
  currentSessionId: null,
  charts: {},
};

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const ROUTES = {
  dashboard: { title: "Dashboard", sub: "Real-time knowledge platform overview", init: initDashboard },
  chat: { title: "Agent Chat", sub: "Plan → Retrieve → Grade → Refine → Synthesize", init: initChat },
  documents: { title: "Documents", sub: "Upload, chunk, embed and index your knowledge base", init: initDocuments },
  analytics: { title: "Analytics", sub: "Aggregated query performance & accuracy", init: initAnalytics },
  settings: { title: "Settings", sub: "Pipeline configuration reference", init: initSettings },
};

function navigate(route) {
  state.route = route;
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.route === route);
  });

  const conf = ROUTES[route];
  document.getElementById("page-title").textContent = conf.title;
  document.getElementById("page-sub").textContent = conf.sub;

  const tpl = document.getElementById(`tpl-${route}`);
  const content = document.getElementById("page-content");
  content.innerHTML = "";
  content.appendChild(tpl.content.cloneNode(true));

  conf.init();
}

document.getElementById("nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".nav-item");
  if (btn) navigate(btn.dataset.route);
});

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------
async function checkBackend() {
  const dot = document.querySelector(".pulse-dot");
  const label = document.getElementById("backend-status");
  try {
    const res = await fetch(`${API_BASE}/`);
    if (!res.ok) throw new Error();
    dot.classList.remove("offline");
    label.textContent = "Backend online";
  } catch {
    dot.classList.add("offline");
    label.textContent = "Backend unreachable";
  }
}

async function refreshModelChip() {
  try {
    const data = await fetch(`${API_BASE}/settings`).then((r) => r.json());
    const chip = document.getElementById("model-chip-llm");
    if (chip && data?.current?.OLLAMA_MODEL) chip.textContent = `⌬ ${data.current.OLLAMA_MODEL}`;
  } catch { /* non-critical */ }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso + "Z")) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function destroyChart(key) {
  if (state.charts[key]) {
    state.charts[key].destroy();
    delete state.charts[key];
  }
}

const chartDefaults = {
  plugins: { legend: { labels: { color: "#8b93a7", font: { family: "JetBrains Mono", size: 11 } } } },
  scales: {
    x: { ticks: { color: "#5b6478", font: { family: "JetBrains Mono", size: 10 } }, grid: { color: "rgba(255,255,255,.04)" } },
    y: { ticks: { color: "#5b6478", font: { family: "JetBrains Mono", size: 10 } }, grid: { color: "rgba(255,255,255,.04)" } },
  },
};

// ---------------------------------------------------------------------------
// DASHBOARD
// ---------------------------------------------------------------------------
async function initDashboard() {
  const [overview, series, docs, activity] = await Promise.all([
    fetch(`${API_BASE}/analytics/overview`).then((r) => r.json()).catch(() => ({})),
    fetch(`${API_BASE}/analytics/timeseries`).then((r) => r.json()).catch(() => []),
    fetch(`${API_BASE}/analytics/documents`).then((r) => r.json()).catch(() => []),
    fetch(`${API_BASE}/analytics/recent-activity`).then((r) => r.json()).catch(() => []),
  ]);

  const kpis = [
    { label: "Documents indexed", value: overview.total_documents ?? 0, accent: "#f5a623" },
    { label: "Vector chunks", value: overview.total_chunks ?? 0, accent: "#2dd4bf" },
    { label: "Total queries", value: overview.total_queries ?? 0, accent: "#8b7cf6" },
    { label: "Avg confidence", value: overview.avg_confidence != null ? `${Math.round(overview.avg_confidence * 100)}%` : "—", accent: "#34d399" },
  ];

  document.getElementById("kpi-grid").innerHTML = kpis.map((k) => `
    <div class="kpi-card" style="--kpi-accent:${k.accent}">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-delta neutral">live from SQL + ChromaDB</div>
    </div>`).join("");

  destroyChart("volume");
  state.charts.volume = new Chart(document.getElementById("chart-volume"), {
    type: "bar",
    data: {
      labels: series.map((s) => s.day.slice(5)),
      datasets: [{ label: "Queries/day", data: series.map((s) => s.queries), backgroundColor: "#f5a623aa", borderRadius: 5 }],
    },
    options: { ...chartDefaults, plugins: { legend: { display: false } } },
  });

  destroyChart("confidence");
  state.charts.confidence = new Chart(document.getElementById("chart-confidence"), {
    type: "line",
    data: {
      labels: series.map((s) => s.day.slice(5)),
      datasets: [{ label: "Avg confidence", data: series.map((s) => s.avg_confidence), borderColor: "#2dd4bf", backgroundColor: "#2dd4bf33", tension: 0.35, fill: true }],
    },
    options: { ...chartDefaults },
  });

  destroyChart("docs");
  state.charts.docs = new Chart(document.getElementById("chart-docs"), {
    type: "doughnut",
    data: {
      labels: docs.map((d) => d.filename),
      datasets: [{ data: docs.map((d) => d.chunks), backgroundColor: ["#f5a623", "#2dd4bf", "#8b7cf6", "#34d399", "#f0556b", "#fbbf24"] }],
    },
    options: { plugins: { legend: { position: "bottom", labels: { color: "#8b93a7", font: { size: 10 } } } } },
  });

  document.getElementById("activity-list").innerHTML = activity.length
    ? activity.map((a) => `
      <div class="activity-row">
        <div class="activity-q">${escapeHtml(a.question)}</div>
        <div class="activity-meta">
          <span>conf ${Math.round((a.confidence || 0) * 100)}%</span>
          <span>${a.hops_used} hop(s)</span>
          <span>${(a.response_time_ms / 1000).toFixed(1)}s</span>
          <span>${timeAgo(a.created_at)}</span>
        </div>
      </div>`).join("")
    : `<div class="muted-text">No queries yet — ask the agent something in Chat.</div>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// CHAT
// ---------------------------------------------------------------------------
async function initChat() {
  document.getElementById("new-session-btn").addEventListener("click", async () => {
    const res = await fetch(`${API_BASE}/chat/sessions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "New conversation" }),
    });
    const session = await res.json();
    state.currentSessionId = session.id;
    await loadSessions();
    renderEmptyChat();
  });

  document.getElementById("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    await sendQuestion(question);
  });

  document.getElementById("session-search").addEventListener("input", (e) => {
    renderSessionList(state.allSessions || [], e.target.value.trim().toLowerCase());
  });

  await loadSessions();
}

async function loadSessions() {
  const sessions = await fetch(`${API_BASE}/chat/sessions`).then((r) => r.json()).catch(() => []);
  state.allSessions = sessions;
  const searchEl = document.getElementById("session-search");
  renderSessionList(sessions, searchEl ? searchEl.value.trim().toLowerCase() : "");
}

function renderSessionList(sessions, filterText) {
  const filtered = filterText
    ? sessions.filter((s) => (s.title || "").toLowerCase().includes(filterText) || (s.last_message_preview || "").toLowerCase().includes(filterText))
    : sessions;

  const countTag = document.getElementById("session-count-tag");
  if (countTag) countTag.textContent = `${sessions.length} conversation${sessions.length === 1 ? "" : "s"}`;

  const list = document.getElementById("session-list");
  list.innerHTML = filtered.length ? filtered.map((s) => `
    <div class="session-item ${s.id === state.currentSessionId ? "active" : ""}" data-id="${s.id}">
      <div class="session-item-top">
        <span class="session-title">${escapeHtml(s.title || "Conversation")}</span>
        <button class="icon-btn session-delete" data-id="${s.id}" title="Delete conversation">✕</button>
      </div>
      ${s.last_message_preview ? `<div class="session-preview">${escapeHtml(s.last_message_preview)}</div>` : ""}
      <div class="session-meta">
        <span>${s.message_count} msg${s.message_count === 1 ? "" : "s"}</span>
        <span>${timeAgo(s.last_active)}</span>
      </div>
    </div>`).join("") : `<div class="muted-text session-empty">No matching conversations.</div>`;

  list.querySelectorAll(".session-item").forEach((el) => {
    el.addEventListener("click", async (e) => {
      if (e.target.closest(".session-delete")) return;
      state.currentSessionId = el.dataset.id;
      list.querySelectorAll(".session-item").forEach((s) => s.classList.toggle("active", s === el));
      await loadMessages(state.currentSessionId);
    });
  });

  list.querySelectorAll(".session-delete").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`${API_BASE}/chat/sessions/${btn.dataset.id}`, { method: "DELETE" });
      if (state.currentSessionId === btn.dataset.id) {
        state.currentSessionId = null;
        renderEmptyChat();
      }
      await loadSessions();
    });
  });
}

function renderEmptyChat() {
  document.getElementById("chat-messages").innerHTML = `
    <div class="chat-empty">
      <div class="chat-empty-mark">◆</div>
      <h3>Ask your knowledge base</h3>
      <p>The agent plans sub-questions, retrieves with hybrid search, grades its own confidence, and refines before answering.</p>
    </div>`;
}

async function loadMessages(sessionId) {
  const messages = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`).then((r) => r.json()).catch(() => []);
  const box = document.getElementById("chat-messages");
  if (!messages.length) { renderEmptyChat(); return; }

  box.innerHTML = messages.map((m) => renderMessageHtml(m)).join("");
  box.scrollTop = box.scrollHeight;
  wireFeedbackButtons(box);
}

function renderMessageHtml(m) {
  if (m.role === "user") {
    return `<div class="msg user">${escapeHtml(m.content)}</div>`;
  }
  const sources = (m.sources || []).map((s) => `<span class="source-chip">📄 ${escapeHtml(s)}</span>`).join("");
  const meta = m.confidence != null
    ? `<div class="msg-meta"><span>confidence ${Math.round(m.confidence * 100)}%</span><span>${m.hops_used} hop(s)</span><span>${((m.response_time_ms||0)/1000).toFixed(1)}s</span></div>`
    : "";
  const feedback = m.id ? renderFeedbackHtml(m.id, m.feedback) : "";
  return `<div class="msg assistant" data-message-id="${m.id || ""}">${escapeHtml(m.content)}${sources ? `<div class="msg-sources">${sources}</div>` : ""}${meta}${feedback}</div>`;
}

function renderFeedbackHtml(messageId, feedback) {
  return `
    <div class="msg-feedback" data-id="${messageId}">
      <button class="feedback-btn up ${feedback === 1 ? "active" : ""}" data-rating="1" title="Good answer">👍</button>
      <button class="feedback-btn down ${feedback === -1 ? "active" : ""}" data-rating="-1" title="Not helpful">👎</button>
    </div>`;
}

function wireFeedbackButtons(container) {
  container.querySelectorAll(".msg-feedback").forEach((el) => {
    el.querySelectorAll(".feedback-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const messageId = el.dataset.id;
        const alreadyActive = btn.classList.contains("active");
        const rating = alreadyActive ? 0 : parseInt(btn.dataset.rating, 10);
        try {
          await fetch(`${API_BASE}/chat/messages/${messageId}/feedback`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rating }),
          });
          el.querySelectorAll(".feedback-btn").forEach((b) => b.classList.remove("active"));
          if (rating !== 0) btn.classList.add("active");
        } catch { /* feedback is best-effort, ignore network errors */ }
      });
    });
  });
}

async function sendQuestion(question) {
  const box = document.getElementById("chat-messages");
  if (box.querySelector(".chat-empty")) box.innerHTML = "";

  box.insertAdjacentHTML("beforeend", `<div class="msg user">${escapeHtml(question)}</div>`);
  const thinkingId = `thinking-${Date.now()}`;
  box.insertAdjacentHTML("beforeend", `<div class="msg assistant" id="${thinkingId}">🧠 Planning sub-questions…</div>`);
  box.scrollTop = box.scrollHeight;

  const sendBtn = document.querySelector("#chat-form button");
  sendBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: state.currentSessionId }),
    });
    const result = await res.json();
    state.currentSessionId = result.session_id;

    document.getElementById(thinkingId).remove();
    box.insertAdjacentHTML("beforeend", renderMessageHtml({
      id: result.message_id, role: "assistant", content: result.answer, sources: result.documents_used,
      confidence: result.confidence, hops_used: result.hops_used, response_time_ms: result.response_time_ms, feedback: null,
    }));
    box.scrollTop = box.scrollHeight;
    wireFeedbackButtons(box);

    renderTraceBar(result.trace);
    await loadSessions();
  } catch (err) {
    document.getElementById(thinkingId).textContent = "⚠ Could not reach the backend. Is FastAPI running?";
  } finally {
    sendBtn.disabled = false;
  }
}

function renderTraceBar(trace) {
  const bar = document.getElementById("agent-trace-bar");
  if (!trace || !trace.length) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.innerHTML = trace.map((t) => `<span class="trace-chip ${t.step_type}">${stepIcon(t.step_type)} ${t.step_type}</span>`).join("");
}

function stepIcon(type) {
  return { plan: "◇", retrieve: "▸", grade: "✓", refine: "↻", synthesize: "✎" }[type] || "•";
}

// ---------------------------------------------------------------------------
// DOCUMENTS
// ---------------------------------------------------------------------------
async function initDocuments() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    handleFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", () => handleFiles(fileInput.files));

  const urlInput = document.getElementById("url-input");
  const urlBtn = document.getElementById("url-ingest-btn");
  urlBtn.addEventListener("click", () => ingestUrl(urlInput));
  urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ingestUrl(urlInput); } });

  await loadDocuments();
}

const ALLOWED_EXTENSIONS = ["pdf", "docx", "txt", "md"];

function handleFiles(fileList) {
  [...fileList]
    .filter((f) => ALLOWED_EXTENSIONS.includes((f.name.split(".").pop() || "").toLowerCase()))
    .forEach(uploadFile);
}

function ingestUrl(urlInput) {
  const url = urlInput.value.trim();
  if (!url) return;
  urlInput.value = "";

  const rowId = `up-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  document.getElementById("upload-progress-list").insertAdjacentHTML("beforeend", `
    <div class="upload-row" id="${rowId}">
      <div class="name">🔗 ${escapeHtml(url)}</div>
      <div class="progress-track"><div class="progress-fill" id="${rowId}-fill" style="width:40%"></div></div>
      <div class="upload-status" id="${rowId}-status">Fetching & indexing…</div>
    </div>`);

  fetch(`${API_BASE}/documents/from-url`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
  })
    .then(async (res) => {
      const fill = document.getElementById(`${rowId}-fill`);
      const status = document.getElementById(`${rowId}-status`);
      if (res.ok) {
        const result = await res.json();
        fill.style.width = "100%";
        status.textContent = `✓ ${result.chunks_indexed} chunks indexed`;
        await loadDocuments();
      } else {
        const err = await res.json().catch(() => ({}));
        fill.style.width = "100%";
        status.textContent = `✗ ${err.detail || "Failed to fetch URL"}`;
      }
    })
    .catch(() => {
      document.getElementById(`${rowId}-status`).textContent = "✗ Network error";
    });
}

function uploadFile(file) {
  const rowId = `up-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  document.getElementById("upload-progress-list").insertAdjacentHTML("beforeend", `
    <div class="upload-row" id="${rowId}">
      <div class="name">📄 ${escapeHtml(file.name)}</div>
      <div class="progress-track"><div class="progress-fill" id="${rowId}-fill"></div></div>
      <div class="upload-status" id="${rowId}-status">Uploading…</div>
    </div>`);

  const formData = new FormData();
  formData.append("file", file);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", `${API_BASE}/upload`);

  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    document.getElementById(`${rowId}-fill`).style.width = `${pct}%`;
    document.getElementById(`${rowId}-status`).textContent = pct < 100 ? `Uploading ${pct}%` : "Chunking & embedding…";
  };

  xhr.onload = async () => {
    const fill = document.getElementById(`${rowId}-fill`);
    const status = document.getElementById(`${rowId}-status`);
    if (xhr.status === 200) {
      fill.style.width = "100%";
      const result = JSON.parse(xhr.responseText);
      status.textContent = `✓ ${result.chunks_indexed} chunks indexed`;
      await loadDocuments();
    } else {
      status.textContent = "✗ Upload failed";
    }
  };

  xhr.onerror = () => {
    document.getElementById(`${rowId}-status`).textContent = "✗ Network error";
  };

  xhr.send(formData);
}

const TYPE_ICON = { pdf: "📄", docx: "📝", txt: "📃", md: "🗒️", url: "🔗" };

async function loadDocuments() {
  const docs = await fetch(`${API_BASE}/documents`).then((r) => r.json()).catch(() => []);
  document.getElementById("doc-count-tag").textContent = `${docs.length} document(s)`;
  document.getElementById("documents-tbody").innerHTML = docs.map((d) => `
    <tr>
      <td>${TYPE_ICON[d.source_type] || "📄"} ${escapeHtml(d.filename)}</td>
      <td><span class="type-pill">${(d.source_type || "pdf").toUpperCase()}</span></td>
      <td>${d.page_count}</td>
      <td>${d.chunk_count}</td>
      <td>${d.file_size_kb} KB</td>
      <td><span class="status-pill ${d.status}">${d.status}</span></td>
      <td>${new Date(d.uploaded_at + "Z").toLocaleString()}</td>
      <td><button class="icon-btn" data-id="${d.id}" title="Delete">✕</button></td>
    </tr>`).join("");

  document.querySelectorAll("#documents-tbody .icon-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API_BASE}/documents/${btn.dataset.id}`, { method: "DELETE" });
      await loadDocuments();
    });
  });
}

// ---------------------------------------------------------------------------
// ANALYTICS
// ---------------------------------------------------------------------------
async function initAnalytics() {
  const [overview, series, logs] = await Promise.all([
    fetch(`${API_BASE}/analytics/overview`).then((r) => r.json()).catch(() => ({})),
    fetch(`${API_BASE}/analytics/timeseries`).then((r) => r.json()).catch(() => []),
    fetch(`${API_BASE}/analytics/recent-activity`).then((r) => r.json()).catch(() => []),
  ]);

  const kpis = [
    { label: "Answer rate", value: `${overview.answer_rate_percent ?? 0}%`, accent: "#34d399" },
    { label: "Avg response time", value: `${overview.avg_response_seconds ?? 0}s`, accent: "#f5a623" },
    { label: "Avg hops / query", value: overview.avg_hops_per_query ?? 0, accent: "#8b7cf6" },
    { label: "Positive feedback", value: overview.positive_feedback_rate != null ? `${overview.positive_feedback_rate}%` : "—", accent: "#2dd4bf" },
  ];
  document.getElementById("analytics-kpi-grid").innerHTML = kpis.map((k) => `
    <div class="kpi-card" style="--kpi-accent:${k.accent}">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
    </div>`).join("");

  destroyChart("analyticsMain");
  state.charts.analyticsMain = new Chart(document.getElementById("chart-analytics-main"), {
    type: "line",
    data: {
      labels: series.map((s) => s.day.slice(5)),
      datasets: [
        { label: "Avg response (s)", data: series.map((s) => s.avg_response_seconds), borderColor: "#f5a623", backgroundColor: "#f5a62333", yAxisID: "y", tension: .35 },
        { label: "Avg confidence", data: series.map((s) => s.avg_confidence), borderColor: "#2dd4bf", backgroundColor: "#2dd4bf33", yAxisID: "y1", tension: .35 },
      ],
    },
    options: {
      ...chartDefaults,
      scales: {
        ...chartDefaults.scales,
        y: { position: "left", ticks: { color: "#5b6478" }, grid: { color: "rgba(255,255,255,.04)" } },
        y1: { position: "right", ticks: { color: "#5b6478" }, grid: { display: false }, min: 0, max: 1 },
      },
    },
  });

  document.getElementById("querylog-tbody").innerHTML = logs.map((l) => `
    <tr>
      <td>${escapeHtml(l.question)}</td>
      <td>${Math.round((l.confidence || 0) * 100)}%</td>
      <td>${l.hops_used}</td>
      <td>${((l.response_time_ms||0)/1000).toFixed(1)}s</td>
      <td>${timeAgo(l.created_at)}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="muted-text">No queries logged yet.</td></tr>`;
}

// ---------------------------------------------------------------------------
// SETTINGS (live admin panel)
// ---------------------------------------------------------------------------
const SETTINGS_FIELDS = [
  { key: "OLLAMA_MODEL", label: "LLM model (Ollama)", type: "text" },
  { key: "MAX_AGENT_HOPS", label: "Max agent hops", type: "number", step: 1 },
  { key: "MIN_CONFIDENCE_TO_STOP", label: "Confidence threshold to stop", type: "number", step: 0.01 },
  { key: "MAX_SUBQUESTIONS", label: "Max sub-questions", type: "number", step: 1 },
  { key: "HYBRID_ALPHA", label: "Hybrid alpha (vector vs BM25 weight)", type: "number", step: 0.05 },
  { key: "VECTOR_TOP_K", label: "Vector search top-K", type: "number", step: 1 },
  { key: "BM25_TOP_K", label: "BM25 search top-K", type: "number", step: 1 },
  { key: "RERANK_TOP_K", label: "Rerank top-K (final context size)", type: "number", step: 1 },
];

async function initSettings() {
  const data = await fetch(`${API_BASE}/settings`).then((r) => r.json()).catch(() => null);
  const current = data ? data.current : {};
  const bounds = data ? data.bounds : {};

  document.getElementById("settings-form").innerHTML = SETTINGS_FIELDS.map((f) => {
    const b = bounds[f.key];
    const rangeHint = b ? `<span class="field-hint">range ${b[0]}–${b[1]}</span>` : "";
    return `
      <label class="settings-field">
        <span class="field-label">${f.label} ${rangeHint}</span>
        <input type="${f.type}" step="${f.step || "any"}" ${b ? `min="${b[0]}" max="${b[1]}"` : ""} data-key="${f.key}" value="${current[f.key] ?? ""}" />
      </label>`;
  }).join("");

  document.getElementById("settings-save-btn").onclick = async () => {
    const updates = {};
    document.querySelectorAll("#settings-form input").forEach((input) => {
      const v = input.value.trim();
      if (v !== "") updates[input.dataset.key] = input.dataset.key === "OLLAMA_MODEL" ? v : Number(v);
    });
    const toast = document.getElementById("settings-toast");
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error();
      toast.textContent = "✓ Saved — applied instantly, no restart needed";
      toast.className = "settings-toast success";
      await initSettings();
      await refreshModelChip();
    } catch {
      toast.textContent = "✗ Failed to save settings";
      toast.className = "settings-toast error";
    }
    setTimeout(() => { toast.textContent = ""; }, 4000);
  };

  document.getElementById("settings-reset-btn").onclick = async () => {
    await fetch(`${API_BASE}/settings/reset`, { method: "POST" });
    await initSettings();
    const toast = document.getElementById("settings-toast");
    toast.textContent = "↺ Reset to defaults";
    toast.className = "settings-toast success";
    setTimeout(() => { toast.textContent = ""; }, 4000);
  };

  const staticInfo = data ? data.static_info : {};
  const config = [
    ["Embedding model", staticInfo.embedding_model || "—"],
    ["Reranker model", staticInfo.reranker_model || "—"],
    ["Chunk size / overlap", `${staticInfo.chunk_size ?? "—"} / ${staticInfo.chunk_overlap ?? "—"}`],
  ];
  document.getElementById("config-grid").innerHTML = config.map(([k, v]) => `
    <div class="config-item">
      <div class="config-key">${k}</div>
      <div class="config-val">${v}</div>
    </div>`).join("");
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
checkBackend();
refreshModelChip();
setInterval(checkBackend, 15000);
navigate("dashboard");
