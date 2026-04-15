/**
 * NicheScope — YouTube Studio content script.
 * Injects a tabbed sidebar with Content Gaps, Demands, Calendar, and Formats.
 */

(function () {
  "use strict";

  const SIDEBAR_ID = "nichescope-sidebar";

  // Don't inject twice
  if (document.getElementById(SIDEBAR_ID)) return;

  let activeTab = "gaps";

  /**
   * Create the sidebar panel with tabs.
   */
  function createSidebar() {
    const sidebar = document.createElement("div");
    sidebar.id = SIDEBAR_ID;
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
      <div class="ns-content" id="ns-content">
        <div class="ns-loading">Loading...</div>
      </div>
    `;
    document.body.appendChild(sidebar);

    // Toggle collapse
    document.getElementById("ns-toggle-btn").addEventListener("click", () => {
      const content = document.getElementById("ns-content");
      const tabs = document.getElementById("ns-tabs");
      const btn = document.getElementById("ns-toggle-btn");
      if (content.style.display === "none") {
        content.style.display = "block";
        tabs.style.display = "flex";
        btn.textContent = "−";
      } else {
        content.style.display = "none";
        tabs.style.display = "none";
        btn.textContent = "+";
      }
    });

    // Tab click handlers
    document.querySelectorAll(".ns-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".ns-tab").forEach((t) => t.classList.remove("ns-tab-active"));
        tab.classList.add("ns-tab-active");
        activeTab = tab.dataset.tab;
        loadTab(activeTab);
      });
    });

    loadTab("gaps");
  }

  /**
   * Load data for the selected tab.
   */
  function loadTab(tab) {
    const content = document.getElementById("ns-content");
    content.innerHTML = `<div class="ns-loading">Loading...</div>`;

    const messageTypes = {
      gaps: "GET_GAPS",
      demands: "GET_DEMANDS",
      calendar: "GET_CALENDAR",
      formats: "GET_FORMATS",
    };

    chrome.runtime.sendMessage({ type: messageTypes[tab] }, (response) => {
      if (chrome.runtime.lastError || !response) {
        content.innerHTML = `<div class="ns-error">Failed to load. Check extension settings.</div>`;
        return;
      }

      if (response.error) {
        content.innerHTML = `<div class="ns-error">${response.error}</div>`;
        return;
      }

      const renderers = {
        gaps: renderGaps,
        demands: renderDemands,
        calendar: renderCalendar,
        formats: renderFormats,
      };

      renderers[tab](response.data, content);
    });
  }

  // ---------- Renderers ----------

  function renderGaps(data, container) {
    const gaps = data?.gaps || [];
    if (gaps.length === 0) {
      container.innerHTML = `<div class="ns-empty">No gap data yet. Analysis runs daily.</div>`;
      return;
    }

    container.innerHTML = gaps
      .map(
        (g, i) => `
      <div class="ns-card">
        <div class="ns-card-rank">#${i + 1}</div>
        <div class="ns-card-body">
          <div class="ns-card-title">${escapeHtml(g.topic)} ${trendEmoji(g.trend)}</div>
          <div class="ns-card-stats">
            Score: ${g.score} · Avg views: ${formatNumber(g.avg_views)} ·
            Competitors: ${g.competitor_videos} · You: ${g.your_videos}
          </div>
          ${
            g.example_videos?.length
              ? `<div class="ns-card-examples">
                  ${g.example_videos.map((t) => `<div class="ns-example">• ${escapeHtml(t)}</div>`).join("")}
                </div>`
              : ""
          }
        </div>
      </div>
    `
      )
      .join("");
  }

  function renderDemands(data, container) {
    const signals = data?.demand_signals || [];
    if (signals.length === 0) {
      container.innerHTML = `<div class="ns-empty">No demand signals yet. Need more competitor data.</div>`;
      return;
    }

    container.innerHTML =
      `<div class="ns-section-hint">💬 What viewers are asking for:</div>` +
      signals
        .map(
          (d, i) => `
        <div class="ns-card">
          <div class="ns-card-rank">#${i + 1}</div>
          <div class="ns-card-body">
            <div class="ns-card-title">${escapeHtml(d.topic)}</div>
            <div class="ns-card-stats">
              ${d.request_count} requests · ${d.total_likes} likes · Strength: ${d.strength_score}
            </div>
            ${
              d.example_requests?.length
                ? `<div class="ns-card-examples">
                    ${d.example_requests.slice(0, 2).map((r) => `<div class="ns-example">💬 ${escapeHtml(r.slice(0, 80))}...</div>`).join("")}
                  </div>`
                : ""
            }
          </div>
        </div>
      `
        )
        .join("");
  }

  function renderCalendar(data, container) {
    const entries = data?.calendar || [];
    if (entries.length === 0) {
      container.innerHTML = `<div class="ns-empty">No seasonal patterns detected yet.</div>`;
      return;
    }

    const urgencyIcon = { now: "🔴", upcoming: "🟡", plan_ahead: "🟢" };

    container.innerHTML =
      `<div class="ns-section-hint">📅 Publish before the peak:</div>` +
      entries
        .map(
          (e) => `
        <div class="ns-card">
          <div class="ns-card-rank">${urgencyIcon[e.urgency] || "⚪"}</div>
          <div class="ns-card-body">
            <div class="ns-card-title">${escapeHtml(e.topic)}</div>
            <div class="ns-card-stats">
              📆 ${escapeHtml(e.publish_window)} · Peak: ${escapeHtml(e.peak_month)} (${e.peak_multiplier}x)
            </div>
            <div class="ns-card-examples">
              <div class="ns-example">${escapeHtml(e.reason)}</div>
            </div>
          </div>
        </div>
      `
        )
        .join("");
  }

  function renderFormats(data, container) {
    const insights = data?.format_insights || [];
    if (insights.length === 0) {
      container.innerHTML = `<div class="ns-empty">Not enough data to analyze formats.</div>`;
      return;
    }

    container.innerHTML =
      `<div class="ns-section-hint">🎬 Best format per topic:</div>` +
      insights
        .map(
          (f, i) => `
        <div class="ns-card">
          <div class="ns-card-rank">#${i + 1}</div>
          <div class="ns-card-body">
            <div class="ns-card-title">${escapeHtml(f.topic)}</div>
            <div class="ns-card-stats">
              ✅ ${escapeHtml(f.best_format)} (${escapeHtml(f.best_duration)}) → ${formatNumber(f.best_avg_views)} views
            </div>
            <div class="ns-card-stats">
              ❌ ${escapeHtml(f.worst_format)} → ${formatNumber(f.worst_avg_views)} views ·
              <strong>${f.multiplier}x gap</strong>
            </div>
          </div>
        </div>
      `
        )
        .join("");
  }

  // ---------- Utilities ----------

  function trendEmoji(trend) {
    return { up: "📈", down: "📉", stable: "➡️" }[trend] || "";
  }

  function formatNumber(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
  }

  function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Wait for YouTube Studio to finish loading, then inject
  const observer = new MutationObserver(() => {
    if (document.querySelector("#page-manager") || document.querySelector("ytcp-app")) {
      observer.disconnect();
      setTimeout(createSidebar, 1000);
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Also try immediately in case page is already loaded
  if (document.querySelector("#page-manager") || document.querySelector("ytcp-app")) {
    setTimeout(createSidebar, 1000);
  }
})();
