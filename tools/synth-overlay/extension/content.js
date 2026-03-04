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

  /**
   * Scrape live Polymarket prices from the DOM.
   * Looks for Up/Down outcome buttons and extracts their cent values.
   * Returns { upPrice: 0.XX, downPrice: 0.XX } or null if not found.
   */
  function scrapeLivePrices() {
    var upPrice = null;
    var downPrice = null;

    // Strategy 1: Look for buttons/elements containing "Up" or "Down" with cent values
    // Polymarket typically shows prices like "Up 85¢" or "Down 16¢"
    var allElements = document.querySelectorAll("button, [role='button'], a");
    
    for (var i = 0; i < allElements.length; i++) {
      var el = allElements[i];
      var text = (el.textContent || "").trim();
      
      // Match patterns like "Up 85¢", "Up85¢", "Up 0.85", "Yes 85¢"
      var upMatch = text.match(/^(Up|Yes)\s*(\d+)\s*[¢c]?$/i);
      var downMatch = text.match(/^(Down|No)\s*(\d+)\s*[¢c]?$/i);
      
      if (upMatch && upMatch[2]) {
        upPrice = parseInt(upMatch[2], 10) / 100;
      }
      if (downMatch && downMatch[2]) {
        downPrice = parseInt(downMatch[2], 10) / 100;
      }
    }

    // Strategy 2: Look for data attributes or structured price elements
    if (upPrice === null || downPrice === null) {
      var priceEls = document.querySelectorAll("[data-outcome], [data-price]");
      for (var j = 0; j < priceEls.length; j++) {
        var priceEl = priceEls[j];
        var outcome = priceEl.getAttribute("data-outcome");
        var priceVal = priceEl.getAttribute("data-price");
        if (outcome && priceVal) {
          var p = parseFloat(priceVal);
          if (outcome.toLowerCase() === "up" || outcome.toLowerCase() === "yes") {
            upPrice = p;
          } else if (outcome.toLowerCase() === "down" || outcome.toLowerCase() === "no") {
            downPrice = p;
          }
        }
      }
    }

    // Strategy 3: Look for common Polymarket class patterns
    if (upPrice === null || downPrice === null) {
      // Try finding outcome cards with price text
      var cards = document.querySelectorAll("[class*='outcome'], [class*='Outcome']");
      for (var k = 0; k < cards.length; k++) {
        var card = cards[k];
        var cardText = (card.textContent || "").toLowerCase();
        var centMatch = cardText.match(/(\d+)\s*[¢c]/);
        if (centMatch) {
          var cents = parseInt(centMatch[1], 10) / 100;
          if (cardText.indexOf("up") !== -1 || cardText.indexOf("yes") !== -1) {
            upPrice = cents;
          } else if (cardText.indexOf("down") !== -1 || cardText.indexOf("no") !== -1) {
            downPrice = cents;
          }
        }
      }
    }

    if (upPrice !== null && downPrice !== null) {
      return { upPrice: upPrice, downPrice: downPrice };
    }
    
    // Fallback: if we only have one, derive the other (prices should sum to ~1)
    if (upPrice !== null && downPrice === null) {
      return { upPrice: upPrice, downPrice: 1 - upPrice };
    }
    if (downPrice !== null && upPrice === null) {
      return { upPrice: 1 - downPrice, downPrice: downPrice };
    }

    return null;
  }

  function getContext() {
    var livePrices = scrapeLivePrices();
    return {
      slug: slugFromPage(),
      url: window.location.href,
      host: window.location.hostname,
      pageUpdatedAt: Date.now(),
      livePrices: livePrices,
    };
  }

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || typeof message !== "object") return;
    if (message.type === "synth:getContext") {
      sendResponse({ ok: true, context: getContext() });
    }
  });
})();
