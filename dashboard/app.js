const API_BASE = "/api";

async function fetchJson(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `${resp.status} ${resp.statusText}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function formatPct(n) {
  return n === null || n === undefined ? "—" : `${(n * 100).toFixed(1)}%`;
}

function renderBadge(config, result) {
  if (!config.enabled) return `<span class="badge disabled">disabled</span>`;
  if (!result) return `<span class="badge no-data">no data yet</span>`;
  return result.significant
    ? `<span class="badge significant">significant difference</span>`
    : `<span class="badge inconclusive">inconclusive</span>`;
}

function renderCard(config, result) {
  const controlRate = result && result.control_n ? result.control_successes / result.control_n : null;
  const weakRate = result && result.weak_n ? result.weak_successes / result.weak_n : null;

  const samplesNeeded = result && result.estimated_samples_needed != null
    ? `~${result.estimated_samples_needed} more samples/tier to reach significance at current effect size`
    : (result && result.significant ? "significance reached" : "not enough data to estimate yet");

  return `
    <div class="card" data-call-site="${config.call_site_id}">
      <div class="card-top">
        <div>
          <div class="card-title">${config.call_site_id}</div>
          <div class="card-sub">${config.control_model} (control) vs ${config.weak_model} (weak) &middot; sample rate ${formatPct(config.sample_rate)}</div>
        </div>
        ${renderBadge(config, result)}
      </div>

      <div class="tier-rates">
        <div class="tier-stat control">
          <div class="label">Control success rate</div>
          <div class="rate">${formatPct(controlRate)}</div>
          <div class="n">${result ? result.control_n : 0} scopes</div>
        </div>
        <div class="tier-stat weak">
          <div class="label">Weak success rate</div>
          <div class="rate">${formatPct(weakRate)}</div>
          <div class="n">${result ? result.weak_n : 0} scopes</div>
        </div>
      </div>

      <div class="meta-row">
        <span>p-value: ${result && result.p_value != null ? result.p_value.toFixed(4) : "—"}</span>
        <span>${samplesNeeded}</span>
        <span>updated ${result ? new Date(result.computed_at).toLocaleString() : "never"}</span>
      </div>

      <div class="card-actions">
        <label>
          <input type="checkbox" class="enabled-toggle" ${config.enabled ? "checked" : ""} />
          enabled
        </label>
        <label>
          sample rate
          <input type="number" class="sample-rate-input" min="0" max="1" step="0.01" value="${config.sample_rate}" />
        </label>
        <button class="save-btn">Save</button>
      </div>
    </div>
  `;
}

async function loadDashboard() {
  const listEl = document.getElementById("call-sites-list");
  let configs;
  try {
    configs = await fetchJson(`${API_BASE}/call-sites`);
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Failed to load call sites: ${err.message}</div>`;
    return;
  }

  if (configs.length === 0) {
    listEl.innerHTML = `<div class="empty-state">No call sites configured yet. Create one to start an experiment.</div>`;
    return;
  }

  const results = await Promise.all(
    configs.map((c) =>
      fetchJson(`${API_BASE}/call-sites/${encodeURIComponent(c.call_site_id)}/results/latest`).catch(() => null)
    )
  );

  listEl.innerHTML = configs.map((c, i) => renderCard(c, results[i])).join("");

  listEl.querySelectorAll(".card").forEach((cardEl, i) => {
    const callSiteId = cardEl.dataset.callSite;
    cardEl.querySelector(".save-btn").addEventListener("click", async () => {
      const enabled = cardEl.querySelector(".enabled-toggle").checked;
      const sampleRate = parseFloat(cardEl.querySelector(".sample-rate-input").value);
      try {
        await fetchJson(`${API_BASE}/call-sites/${encodeURIComponent(callSiteId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled, sample_rate: sampleRate, changed_by: "dashboard" }),
        });
        loadDashboard();
      } catch (err) {
        alert(`Failed to save: ${err.message}`);
      }
    });
  });
}

function setupNewCallSiteDialog() {
  const dialog = document.getElementById("new-call-site-dialog");
  const form = document.getElementById("new-call-site-form");
  const errorEl = document.getElementById("new-call-site-error");

  document.getElementById("new-call-site-btn").addEventListener("click", () => {
    errorEl.textContent = "";
    form.reset();
    dialog.showModal();
  });
  document.getElementById("cancel-new-call-site").addEventListener("click", () => dialog.close());

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    data.sample_rate = parseFloat(data.sample_rate);
    try {
      await fetchJson(`${API_BASE}/call-sites`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      dialog.close();
      loadDashboard();
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });
}

function setupRunAnalysisButton() {
  const btn = document.getElementById("run-analysis-btn");
  const statusEl = document.getElementById("run-analysis-status");

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    statusEl.textContent = "running...";
    try {
      const result = await fetchJson(`${API_BASE}/analysis/run`, { method: "POST" });
      statusEl.textContent = `done — analyzed ${result.analyzed_call_sites} call site(s) at ${new Date().toLocaleTimeString()}`;
      await loadDashboard();
    } catch (err) {
      statusEl.textContent = `failed: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });
}

setupNewCallSiteDialog();
setupRunAnalysisButton();
loadDashboard();
setInterval(loadDashboard, 30000);
