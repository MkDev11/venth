var SUPPORTED_ORIGINS = [
  "https://polymarket.com/"
];

function isSupportedUrl(url) {
  for (var i = 0; i < SUPPORTED_ORIGINS.length; i++) {
    if (url.indexOf(SUPPORTED_ORIGINS[i]) === 0) return true;
  }
  return false;
}

chrome.runtime.onInstalled.addListener(function () {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

chrome.tabs.onUpdated.addListener(function (tabId, info, tab) {
  if (!chrome.sidePanel) return;
  if (info.status === "complete" || info.url) {
    var url = tab && tab.url ? tab.url : "";
    chrome.sidePanel.setOptions({
      tabId: tabId,
      path: "sidepanel.html",
      enabled: isSupportedUrl(url)
    });
  }
});
