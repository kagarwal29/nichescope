/**
 * NicheScope — YouTube Studio content script.
 * Tabbed sidebar: Gaps | Demands | Calendar | Formats
 */
(function () {
  "use strict";
  if (document.getElementById("nichescope-sidebar")) return;

  function createSidebar() {
    const sidebar = document.createElement("div");
    sidebar.id = "nichescope-sidebar";
    sidebar.innerHTML = `
      <div class="ns-header">
        <span class="ns-logo">🔍 NicheScope</span>
        <button class="ns-toggle" id="ns-toggle-btn">−</button>
      </div>
      <div class="ns-tabs" id="ns-tabs">
        <button class="ns-tab ns-tab-active" data-tab="gaps">Gaps</button>
        <button class="ns-tab" data-tab="demands">Demands</button>
        <button class="ns-tab" data-tab="calendar">Calendar</button>
        <button class="ns-tab" data-tab="formats">Formats</button>
      </div>
      <div class="ns-content" id="ns-content"><div class="ns-loading">Loading...</div></div>`;
    document.body.appendChild(sidebar);

    document.getElementById("ns-toggle-btn").addEventListener("click", () => {
      const c = document.getElementById("ns-content");
      const t = document.getElementById("ns-tabs");
      const b = document.getElementById("ns-toggle-btn");
      const hidden = c.style.display === "none";
      c.style.display = hidden ? "block" : "none";
      t.style.display = hidden ? "flex" : "none";
      b.textContent = hidden ? "−" : "+";
    });

    document.querySelectorAll(".ns-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".ns-tab").forEach(t => t.classList.remove("ns-tab-active"));
        tab.classList.add("ns-tab-active");
        loadTab(tab.dataset.tab);
      });
    });
    loadTab("gaps");
  }

  function loadTab(tab) {
    const content = document.getElementById("ns-content");
    content.innerHTML = `<div class="ns-loading">Loading...</div>`;
    const types = { gaps: "GET_GAPS", demands: "GET_DEMANDS", calendar: "GET_CALENDAR", formats: "GET_FORMATS" };
    chrome.runtime.sendMessage({ type: types[tab] }, (response) => {
      if (chrome.runtime.lastError || !response) {
        content.innerHTML = `<div class="ns-error">Failed to load. Check extension settings.</div>`; return;
      }
      if (response.error) { content.innerHTML = `<div class="ns-error">${response.error}</div>`; return; }
      ({ gaps: renderGaps, demands: renderDemands, calendar: renderCalendar, formats: renderFormats })[tab](response.data, content);
    });
  }

  function card(rank, title, stats, extra = "") {
    return `<div class="ns-card"><div class="ns-card-rank">${rank}</div><div class="ns-card-body">
      <div class="ns-card-title">${title}</div>
      <div class="ns-card-stats">${stats}</div>${extra}</div></div>`;
  }

  function renderGaps(data, el) {
    const gaps = data?.gaps || [];
    if (!gaps.length) { el.innerHTML = `<div class="ns-empty">No gap data yet. Analysis runs daily.</div>`; return; }
    el.innerHTML = gaps.map((g, i) => card(
      `#${i+1}`,
      `${esc(g.topic)} ${trend(g.trend)}`,
      `Score: ${g.score} · ${fmt(g.avg_views)} views · Comp: ${g.competitor_videos} · You: ${g.your_videos}`,
      g.example_videos?.length ? `<div class="ns-card-examples">${g.example_videos.slice(0,2).map(t=>`<div class="ns-example">• ${esc(t)}</div>`).join("")}</div>` : ""
    )).join("");
  }

  function renderDemands(data, el) {
    const s = data?.demand_signals || [];
    if (!s.length) { el.innerHTML = `<div class="ns-empty">No demand signals yet.</div>`; return; }
    el.innerHTML = `<div class="ns-section-hint">💬 What viewers are asking for:</div>` +
      s.map((d, i) => card(`#${i+1}`, esc(d.topic),
        `${d.request_count} requests · ${d.total_likes} likes · Strength: ${d.strength_score}`,
        d.example_requests?.length ? `<div class="ns-card-examples">${d.example_requests.slice(0,2).map(r=>`<div class="ns-example">💬 ${esc(r.slice(0,80))}...</div>`).join("")}</div>` : ""
      )).join("");
  }

  function renderCalendar(data, el) {
    const entries = data?.calendar || [];
    if (!entries.length) { el.innerHTML = `<div class="ns-empty">No seasonal patterns detected yet.</div>`; return; }
    const icon = { now: "🔴", upcoming: "🟡", plan_ahead: "🟢" };
    el.innerHTML = `<div class="ns-section-hint">📅 Publish before the peak:</div>` +
      entries.map(e => card(
        icon[e.urgency] || "⚪", esc(e.topic),
        `📆 ${esc(e.publish_window)} · Peak: ${esc(e.peak_month)} (${e.peak_multiplier}x)`,
        `<div class="ns-card-examples"><div class="ns-example">${esc(e.reason)}</div></div>`
      )).join("");
  }

  function renderFormats(data, el) {
    const f = data?.format_insights || [];
    if (!f.length) { el.innerHTML = `<div class="ns-empty">Not enough data to analyze formats.</div>`; return; }
    el.innerHTML = `<div class="ns-section-hint">🎬 Best format per topic:</div>` +
      f.map((fi, i) => card(`#${i+1}`, esc(fi.topic),
        `✅ ${esc(fi.best_format)} (${esc(fi.best_duration)}) → ${fmt(fi.best_avg_views)} views`,
        `<div class="ns-card-stats">❌ ${esc(fi.worst_format)} → ${fmt(fi.worst_avg_views)} views · <strong>${fi.multiplier}x gap</strong></div>`
      )).join("");
  }

  const trend = t => ({ up: "📈", down: "📉", stable: "➡️" })[t] || "";
  const fmt = n => n >= 1e6 ? (n/1e6).toFixed(1)+"M" : n >= 1e3 ? (n/1e3).toFixed(1)+"K" : String(n);
  function esc(t) { if (!t) return ""; const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

  const observer = new MutationObserver(() => {
    if (document.querySelector("#page-manager") || document.querySelector("ytcp-app")) {
      observer.disconnect(); setTimeout(createSidebar, 1000);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  if (document.querySelector("#page-manager") || document.querySelector("ytcp-app")) setTimeout(createSidebar, 1000);
})();
