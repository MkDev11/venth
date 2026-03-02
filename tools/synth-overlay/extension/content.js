(function () {
  "use strict";

  function slugFromPage() {
    var host = window.location.hostname || "";
    var path = window.location.pathname || "";
    var segments = path.split("/").filter(Boolean);

    // Polymarket: /event/<slug> or /market/<slug> or /<slug>
    if (host.indexOf("polymarket.com") !== -1) {
      var first = segments[0];
      var second = segments[1] || segments[0];
      if (first === "event" || first === "market") return second || null;
      return first || null;
    }

    // Generic fallback: use the last meaningful path segment
    return segments[segments.length - 1] || null;
  }

  function getContext() {
    return {
      slug: slugFromPage(),
      url: window.location.href,
      host: window.location.hostname,
      pageUpdatedAt: Date.now(),
    };
  }

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || typeof message !== "object") return;
    if (message.type === "synth:getContext") {
      sendResponse({ ok: true, context: getContext() });
    }
  });
})();
