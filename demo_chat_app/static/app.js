const API_BASE = "/api";
let currentSessionId = null;
let sessionsCache = [];

async function fetchJson(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

async function loadMeta() {
  try {
    const meta = await fetchJson(`${API_BASE}/meta`);
    document.getElementById("dashboard-link").href = meta.sampler_dashboard_url;
  } catch (err) {
    // non-fatal, dashboard link just won't work
  }
}

async function loadSessions() {
  sessionsCache = await fetchJson(`${API_BASE}/sessions`);
  renderSessionList();
}

function renderSessionList() {
  const listEl = document.getElementById("session-list");
  if (sessionsCache.length === 0) {
    listEl.innerHTML = `<div class="session-item">No conversations yet</div>`;
    return;
  }
  listEl.innerHTML = sessionsCache
    .map((s) => {
      const preview = s.messages.find((m) => m.role === "user")?.text?.slice(0, 24) || "New conversation";
      const voteIcon = s.vote === "up" ? "👍" : s.vote === "down" ? "👎" : "";
      const activeClass = s.id === currentSessionId ? "active" : "";
      return `<div class="session-item ${activeClass}" data-id="${s.id}">
                <span>${preview}</span><span class="vote-icon">${voteIcon}</span>
              </div>`;
    })
    .join("");

  listEl.querySelectorAll(".session-item[data-id]").forEach((el) => {
    el.addEventListener("click", () => selectSession(el.dataset.id));
  });
}

function renderMessages(session) {
  const el = document.getElementById("messages");
  el.innerHTML = session.messages
    .map((m) => `<div class="bubble ${m.role}">${escapeHtml(m.text)}</div>`)
    .join("");
  el.scrollTop = el.scrollHeight;
}

function renderVoteState(session) {
  document.getElementById("thumbs-up").classList.toggle("selected", session.vote === "up");
  document.getElementById("thumbs-down").classList.toggle("selected", session.vote === "down");
  const statusEl = document.getElementById("vote-status");
  statusEl.textContent = session.vote ? `you rated this ${session.vote === "up" ? "👍" : "👎"}` : "";
}

function renderDebug(session) {
  document.getElementById("debug-content").innerHTML = `
    <div>session_id: ${session.id}</div>
    <div>tier: ${session.tier || "not yet assigned"}</div>
    <div>model: ${session.model || "—"}</div>
    <div>messages: ${session.messages.length}</div>
  `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function selectSession(id) {
  currentSessionId = id;
  const session = await fetchJson(`${API_BASE}/sessions/${id}`);
  document.getElementById("empty-state").hidden = true;
  document.getElementById("chat-panel").hidden = false;
  renderMessages(session);
  renderVoteState(session);
  renderDebug(session);
  renderSessionList();
}

async function createNewChat() {
  const session = await fetchJson(`${API_BASE}/sessions`, { method: "POST" });
  sessionsCache.unshift(session);
  await selectSession(session.id);
}

async function sendMessage(text) {
  const session = await fetchJson(`${API_BASE}/sessions/${currentSessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  renderMessages(session);
  renderDebug(session);
  const idx = sessionsCache.findIndex((s) => s.id === session.id);
  if (idx >= 0) sessionsCache[idx] = session;
  renderSessionList();
}

async function vote(choice) {
  if (!currentSessionId) return;
  const session = await fetchJson(`${API_BASE}/sessions/${currentSessionId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vote: choice }),
  });
  renderVoteState(session);
  const idx = sessionsCache.findIndex((s) => s.id === session.id);
  if (idx >= 0) sessionsCache[idx] = session;
  renderSessionList();
}

document.getElementById("new-chat-btn").addEventListener("click", () => {
  createNewChat().catch((err) => alert(`Failed to start chat: ${err.message}`));
});

document.getElementById("message-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("message-input");
  const text = input.value.trim();
  if (!text || !currentSessionId) return;
  input.value = "";
  sendMessage(text).catch((err) => alert(`Failed to send message: ${err.message}`));
});

document.getElementById("thumbs-up").addEventListener("click", () => {
  vote("up").catch((err) => alert(`Failed to record vote: ${err.message}`));
});
document.getElementById("thumbs-down").addEventListener("click", () => {
  vote("down").catch((err) => alert(`Failed to record vote: ${err.message}`));
});

loadMeta();
loadSessions();
