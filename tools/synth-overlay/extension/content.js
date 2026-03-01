(function () {
  "use strict";

  var API_BASE = "http://127.0.0.1:8765";
  var currentSlug = null;
  var lastApiData = null;

  function slugFromPage() {
    var path = window.location.pathname || "";
    var segments = path.split("/").filter(Boolean);
    var first = segments[0];
    var second = segments[1] || segments[0];
    if (first === "event" || first === "market") {
      return second || null;
    }
    return first || null;
  }

  function formatLabel(signal, edgePct) {
    var prefix = edgePct >= 0 ? "+" : "";
    if (signal === "fair") return "Fair " + prefix + edgePct + "%";
    return "YES Edge " + prefix + edgePct + "%";
  }

  function confidenceLabel(score) {
    if (score >= 0.7) return "High";
    if (score >= 0.4) return "Medium";
    return "Low";
  }

  function confidenceBarWidth(score) {
    return Math.max(5, Math.min(100, Math.round(score * 100)));
  }

  function confidenceColorClass(score) {
    if (score >= 0.7) return "synth-overlay-conf-high";
    if (score >= 0.4) return "synth-overlay-conf-medium";
    return "synth-overlay-conf-low";
  }

  function formatProbAsCents(p) {
    if (p == null || p === undefined) return "—";
    return Math.round(p * 100) + "¢";
  }

  function formatNow() {
    var d = new Date();
    var h = d.getHours(); var m = d.getMinutes(); var s = d.getSeconds();
    var ampm = h >= 12 ? "PM" : "AM";
    h = h % 12; if (h === 0) h = 12;
    var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
    return h + ":" + pad(m) + ":" + pad(s) + " " + ampm;
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function readDomPrices() {
    var scope = findTradeWidgetAnchor() || document.body;
    var allNodes = Array.prototype.slice.call(scope.querySelectorAll("button, [role='button'], div, span"));
    var upCents = null;
    var downCents = null;
    for (var i = 0; i < allNodes.length; i++) {
      var node = allNodes[i];
      var raw = (node.textContent || "").replace(/[\s\u00a0]+/g, " ").trim();
      if (raw.length > 20) continue;
      if (!upCents && /^up\b/i.test(raw) && /\d/.test(raw) && /¢/.test(raw)) {
        var m1 = raw.match(/([\d.]+)\s*¢/);
        if (m1) upCents = m1[1] + "¢";
      }
      if (!downCents && /^down\b/i.test(raw) && /\d/.test(raw) && /¢/.test(raw)) {
        var m2 = raw.match(/([\d.]+)\s*¢/);
        if (m2) downCents = m2[1] + "¢";
      }
      if (upCents && downCents) break;
    }
    return { up: upCents, down: downCents };
  }

  function showPanel(data) {
    closePanel();
    var tab = document.querySelector("[data-synth-overlay=tab]");
    if (tab) tab.classList.add("synth-overlay-tab-hidden");
    var panel = document.createElement("div");
    panel.className = "synth-overlay-panel";
    panel.setAttribute("data-synth-overlay", "panel");

    var explanation = data.explanation || "No explanation available.";
    var invalidation = data.invalidation || "";
    var confScore = data.confidence_score != null ? data.confidence_score : 0.5;
    var barWidth = confidenceBarWidth(confScore);

    var hasDual = data.edge_1h_pct != null && data.edge_24h_pct != null;
    var now1h = hasDual ? formatLabel(data.signal_1h, data.edge_1h_pct) : formatLabel(data.signal, data.edge_pct);
    var byClose24h = hasDual ? formatLabel(data.signal_24h, data.edge_24h_pct) : formatLabel(data.signal, data.edge_pct);

    var synthProb = data.synth_probability_up != null ? data.synth_probability_up : data.synth_probability;
    var synthUpCents = formatProbAsCents(synthProb);
    var synthDownCents = synthProb != null ? formatProbAsCents(1 - synthProb) : "—";

    var domPrices = readDomPrices();
    var liveUp = domPrices.up || "—";
    var liveDown = domPrices.down || "—";

    panel.innerHTML =
      '<div class="synth-overlay-panel-header">' +
        '<span class="synth-overlay-panel-title">Synth Overlay</span>' +
        '<span class="synth-overlay-panel-close">\u2715</span>' +
      "</div>" +
      '<div class="synth-overlay-panel-body">' +
        '<div class="synth-overlay-panel-section">' +
          '<div class="synth-overlay-panel-label">Synth Forecast</div>' +
          '<div class="synth-overlay-panel-row"><strong>Synth Up:</strong> ' + escapeHtml(synthUpCents) + "</div>" +
          '<div class="synth-overlay-panel-row"><strong>Synth Down:</strong> ' + escapeHtml(synthDownCents) + "</div>" +
          '<div class="synth-overlay-panel-row"><strong>Edge:</strong> ' + (data.edge_pct >= 0 ? "+" : "") + escapeHtml(String(data.edge_pct)) + "%</div>" +
          '<div class="synth-overlay-panel-text" style="margin-top:6px">' + escapeHtml(explanation) + "</div>" +
        "</div>" +
        '<div class="synth-overlay-panel-section">' +
          '<div class="synth-overlay-panel-label">Live Market (from page)</div>' +
          '<div class="synth-overlay-panel-row"><strong>Up:</strong> ' + escapeHtml(liveUp) + "</div>" +
          '<div class="synth-overlay-panel-row"><strong>Down:</strong> ' + escapeHtml(liveDown) + "</div>" +
        "</div>" +
        '<div class="synth-overlay-panel-section">' +
          '<div class="synth-overlay-panel-label">Signal</div>' +
          '<div class="synth-overlay-panel-row"><strong>Now (1h):</strong> ' + escapeHtml(now1h) + "</div>" +
          '<div class="synth-overlay-panel-row"><strong>By close (24h):</strong> ' + escapeHtml(byClose24h) + "</div>" +
          '<div class="synth-overlay-panel-row"><strong>Strength:</strong> ' + escapeHtml(data.strength) + "</div>" +
        "</div>" +
        '<div class="synth-overlay-panel-section">' +
          '<div class="synth-overlay-panel-label">Confidence</div>' +
          '<div class="synth-overlay-conf-bar synth-overlay-conf-bar-lg">' +
            '<div class="synth-overlay-conf-fill ' + confidenceColorClass(confScore) + '" style="width:' + barWidth + '%"></div>' +
          "</div>" +
          '<div class="synth-overlay-panel-row">' + escapeHtml(confidenceLabel(confScore)) +
            " (" + Math.round(confScore * 100) + "%)</div>" +
        "</div>" +
        (invalidation
          ? '<div class="synth-overlay-panel-section">' +
              '<div class="synth-overlay-panel-label">What would invalidate it</div>' +
              '<div class="synth-overlay-panel-text">' + escapeHtml(invalidation) + "</div>" +
            "</div>"
          : "") +
        (data.no_trade_warning
          ? '<div class="synth-overlay-panel-section synth-overlay-no-trade">' +
              "No trade \u2014 uncertainty is high or signals conflict." +
            "</div>"
          : "") +
        '<div class="synth-overlay-panel-meta">' +
          "Last update: " + escapeHtml(formatNow()) +
          ' <span class="synth-overlay-refresh-btn" data-synth-refresh="1">\u21BB Refresh</span>' +
        "</div>" +
      "</div>";

    var closeBtn = panel.querySelector(".synth-overlay-panel-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        closePanel();
        var t = document.querySelector("[data-synth-overlay=tab]");
        if (t) t.classList.remove("synth-overlay-tab-hidden");
      });
    }

    var refreshBtn = panel.querySelector("[data-synth-refresh]");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        refreshBtn.textContent = "\u21BB Refreshing\u2026";
        var slug = slugFromPage();
        if (!slug) return;
        fetchEdge(slug).then(function (freshData) {
          if (!freshData || freshData.error) {
            refreshBtn.textContent = "\u21BB Refresh (failed)";
            return;
          }
          lastApiData = freshData;
          removeInlineOverlays();
          injectInlineOverlays(freshData);
          showPanel(freshData);
        });
      });
    }

    document.body.appendChild(panel);
    requestAnimationFrame(function () {
      panel.classList.add("synth-overlay-panel-open");
    });
  }

  function closePanel() {
    var panels = document.querySelectorAll("[data-synth-overlay=panel]");
    for (var i = 0; i < panels.length; i++) panels[i].remove();
    var t = document.querySelector("[data-synth-overlay=tab]");
    if (t) t.classList.remove("synth-overlay-tab-hidden");
  }

  function createSidePanelTab(data) {
    var existing = document.querySelector("[data-synth-overlay=tab]");
    if (existing) existing.remove();
    var tab = document.createElement("div");
    tab.className = "synth-overlay-tab";
    tab.setAttribute("data-synth-overlay", "tab");
    tab.textContent = "Synth";
    tab.addEventListener("click", function (e) {
      e.stopPropagation();
      showPanel(data);
    });
    document.body.appendChild(tab);
  }

  function injectInlineOverlays(data) {
    removeInlineOverlays();
    var synthProb = data.synth_probability_up != null ? data.synth_probability_up : data.synth_probability;
    var synthUpCents = formatProbAsCents(synthProb);
    var synthDownCents = synthProb != null ? formatProbAsCents(1 - synthProb) : "—";
    var signal = data.signal;

    var upColor = signal === "underpriced" ? "#15803d" : signal === "overpriced" ? "#b91c1c" : "#6b7280";
    var downColor = signal === "overpriced" ? "#15803d" : signal === "underpriced" ? "#b91c1c" : "#6b7280";

    var scope = findTradeWidgetAnchor() || document.body;
    var allNodes = Array.prototype.slice.call(scope.querySelectorAll("button, [role='button'], div, span"));
    var upTarget = null;
    var downTarget = null;
    for (var i = 0; i < allNodes.length; i++) {
      var node = allNodes[i];
      var raw = (node.textContent || "").replace(/[\s\u00a0]+/g, " ").trim();
      if (raw.length > 20) continue;
      if (!upTarget && /^up\b/i.test(raw) && /\d/.test(raw) && /¢/.test(raw)) upTarget = node;
      if (!downTarget && /^down\b/i.test(raw) && /\d/.test(raw) && /¢/.test(raw)) downTarget = node;
      if (upTarget && downTarget) break;
    }

    function addSynthLabel(anchor, labelText, color) {
      if (!anchor) return;
      var parent = anchor.parentNode;
      if (!parent) return;
      var label = document.createElement("div");
      label.setAttribute("data-synth-inline", "1");
      label.style.cssText =
        "display:block !important;visibility:visible !important;opacity:1 !important;" +
        "font-size:11px !important;font-weight:700 !important;font-family:system-ui,-apple-system,sans-serif !important;" +
        "color:" + color + " !important;text-align:center !important;" +
        "margin-top:4px !important;padding:2px 6px !important;" +
        "background:#f0f9ff !important;border:1px solid #93c5fd !important;border-radius:6px !important;" +
        "z-index:99998 !important;";
      label.textContent = labelText;
      if (anchor.nextSibling) {
        parent.insertBefore(label, anchor.nextSibling);
      } else {
        parent.appendChild(label);
      }
    }

    addSynthLabel(upTarget, "Synth: " + synthUpCents, upColor);
    addSynthLabel(downTarget, "Synth: " + synthDownCents, downColor);

    if (!upTarget && !downTarget) {
      var anchor = findTradeWidgetAnchor();
      var bar = document.createElement("div");
      bar.setAttribute("data-synth-inline", "1");
      bar.style.cssText =
        "display:flex !important;gap:12px !important;align-items:center !important;justify-content:center !important;" +
        "padding:6px 12px !important;margin:4px 0 !important;" +
        "background:#f0f9ff !important;border:1px solid #93c5fd !important;" +
        "border-radius:8px !important;font-family:system-ui,-apple-system,sans-serif !important;" +
        "font-size:12px !important;z-index:99998 !important;" +
        "visibility:visible !important;opacity:1 !important;";
      var upSpan = document.createElement("span");
      upSpan.style.cssText = "font-weight:700 !important;color:" + upColor + " !important;";
      upSpan.textContent = "\u2191 Synth Up: " + synthUpCents;
      var downSpan = document.createElement("span");
      downSpan.style.cssText = "font-weight:700 !important;color:" + downColor + " !important;";
      downSpan.textContent = "\u2193 Synth Down: " + synthDownCents;
      bar.appendChild(upSpan);
      bar.appendChild(downSpan);
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(bar, anchor);
      } else {
        bar.style.position = "fixed";
        bar.style.top = "60px";
        bar.style.right = "60px";
        document.body.appendChild(bar);
      }
    }
  }

  function findTradeWidgetAnchor() {
    var candidates = Array.prototype.slice.call(document.querySelectorAll("div, section, aside, form"));
    var best = null;
    var bestLen = Infinity;
    for (var i = 0; i < candidates.length; i++) {
      var el = candidates[i];
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length < 20 || text.length > 4000) continue;
      if (!/\bbuy\b/i.test(text) || !/\bsell\b/i.test(text)) continue;
      if (!/¢/.test(text)) continue;
      if (!/\btrade\b/i.test(text) && !/\bamount\b/i.test(text)) continue;
      if (text.length < bestLen) {
        best = el;
        bestLen = text.length;
      }
    }
    return best;
  }

  function removeInlineOverlays() {
    var hints = document.querySelectorAll("[data-synth-inline]");
    for (var i = 0; i < hints.length; i++) hints[i].remove();
  }

  function injectBadge(container, data) {
    removeBadge();
    lastApiData = data;
    createSidePanelTab(data);
    injectInlineOverlays(data);
    var retries = [1000, 2500, 5000];
    retries.forEach(function (ms) {
      setTimeout(function () {
        if (!document.querySelector("[data-synth-overlay=tab]")) return;
        if (!document.querySelector("[data-synth-inline]")) injectInlineOverlays(data);
      }, ms);
    });
  }

  function removeBadge() {
    var tabs = document.querySelectorAll("[data-synth-overlay=tab]");
    for (var i = 0; i < tabs.length; i++) tabs[i].remove();
    removeInlineOverlays();
    closePanel();
  }

  function findInjectionTarget() {
    return document.body;
  }

  function fetchEdge(slug) {
    return fetch(API_BASE + "/api/edge?slug=" + encodeURIComponent(slug), {
      method: "GET",
      mode: "cors",
    })
      .then(function (r) {
        if (!r.ok) return null;
        return r.json();
      })
      .catch(function () {
        return null;
      });
  }

  function run() {
    var slug = slugFromPage();
    if (!slug) {
      currentSlug = null;
      removeBadge();
      return;
    }
    var requestedSlug = slug;
    fetchEdge(slug).then(function (data) {
      if (slugFromPage() !== requestedSlug) return;
      if (!data || data.error) {
        currentSlug = null;
        removeBadge();
        return;
      }
      currentSlug = requestedSlug;
      var target = findInjectionTarget();
      if (target) injectBadge(target, data);
    });
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      if (t) clearTimeout(t);
      t = setTimeout(fn, ms);
    };
  }

  var runDebounced = debounce(run, 400);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }

  var observer = new MutationObserver(function () {
    var slug = slugFromPage();
    if (slug === currentSlug && document.querySelector("[data-synth-overlay=tab]")) {
      return;
    }
    runDebounced();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  var lastHref = window.location.href;
  setInterval(function () {
    if (window.location.href !== lastHref) {
      lastHref = window.location.href;
      currentSlug = null;
      removeBadge();
      run();
    }
  }, 500);
})();
