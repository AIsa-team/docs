// Advertises the clean-markdown version of every page to agents and crawlers
// via <link rel="alternate" type="text/markdown"> in <head>.
//
// Mintlify serves a .md version of each page at {url}.md with no extra config.
// This script inserts an alternate-link tag pointing there on every page load
// and re-syncs the tag on client-side navigation.

(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var LINK_ID = "mintlify-markdown-alternate";

  function markdownHrefForLocation() {
    var path = window.location.pathname;
    // Skip synthetic paths
    if (!path || path.indexOf(".") !== -1) return null;
    var clean = path.replace(/\/+$/, "");
    return window.location.origin + clean + ".md";
  }

  function syncAlternateLink() {
    var href = markdownHrefForLocation();
    var link = document.getElementById(LINK_ID);
    if (!href) {
      if (link && link.parentNode) link.parentNode.removeChild(link);
      return;
    }
    if (!link) {
      link = document.createElement("link");
      link.id = LINK_ID;
      link.rel = "alternate";
      link.type = "text/markdown";
      document.head.appendChild(link);
    }
    if (link.href !== href) link.href = href;
  }

  // Initial paint
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", syncAlternateLink, { once: true });
  } else {
    syncAlternateLink();
  }

  // SPA-aware: re-run on history navigation and any URL change
  var lastPath = window.location.pathname;
  function onMaybeNavigated() {
    if (window.location.pathname !== lastPath) {
      lastPath = window.location.pathname;
      syncAlternateLink();
    }
  }

  window.addEventListener("popstate", syncAlternateLink);
  window.addEventListener("hashchange", syncAlternateLink);

  // Wrap pushState / replaceState to detect programmatic navigation
  ["pushState", "replaceState"].forEach(function (method) {
    var original = history[method];
    if (typeof original !== "function") return;
    history[method] = function () {
      var result = original.apply(this, arguments);
      window.dispatchEvent(new Event("mintlify:navigation"));
      return result;
    };
  });
  window.addEventListener("mintlify:navigation", syncAlternateLink);

  // Backstop: poll once per second for missed navigations
  setInterval(onMaybeNavigated, 1000);
})();
