// Move Mintlify's native language selector to the right-side topbar controls so
// the docs header matches the aisa.one website order: News / language / CTA.
// Keep the original Mintlify trigger and dropdown behavior intact.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var ITEM_ID = "aisa-language-nav-item";

  function setCompactLabel(trigger) {
    var label = trigger.querySelector("span");
    if (!label) return;

    var current = (label.textContent || "").trim().toLowerCase();
    if (current.indexOf("中文") !== -1 || current === "zh" || current === "中") {
      label.textContent = "中";
    } else {
      label.textContent = "EN";
    }

    trigger.setAttribute("aria-label", "Language");
    trigger.setAttribute("title", "Language");
  }

  function ensureListItem(wrapper) {
    var existing = document.getElementById(ITEM_ID);
    if (existing) {
      if (!existing.contains(wrapper)) existing.appendChild(wrapper);
      return existing;
    }

    var item = document.createElement("li");
    item.id = ITEM_ID;
    item.appendChild(wrapper);
    return item;
  }

  function findRightControls(navbar) {
    return (
      navbar.querySelector("topbar-right-container") ||
      navbar.querySelector("[class*='justify-end']") ||
      navbar
    );
  }

  function findCta(rightControls) {
    return (
      document.getElementById("topbar-cta-button") ||
      rightControls.querySelector("a[href*='console.aisa.one']") ||
      rightControls.querySelector("a[href*='console']")
    );
  }

  function syncLanguageNav() {
    var trigger = document.getElementById("localization-select-trigger");
    var navbar = document.getElementById("navbar");
    if (!trigger || !navbar) return;

    setCompactLabel(trigger);

    var wrapper = trigger.parentElement;
    if (!wrapper) return;
    wrapper.classList.add("aisa-language-wrapper");

    var rightControls = findRightControls(navbar);
    var cta = findCta(rightControls);

    if (cta) {
      var ctaItem = cta.closest("li") || cta;
      var parent = ctaItem.parentNode;
      if (!parent) return;

      if (parent.tagName === "UL" || parent.tagName === "OL") {
        var item = ensureListItem(wrapper);
        if (item.parentNode !== parent || item.nextSibling !== ctaItem) {
          parent.insertBefore(item, ctaItem);
        }
      } else if (wrapper.parentNode !== parent || wrapper.nextSibling !== ctaItem) {
        parent.insertBefore(wrapper, ctaItem);
      }
      return;
    }

    if (!rightControls.contains(wrapper)) {
      rightControls.appendChild(wrapper);
    }
  }

  function scheduleSync() {
    window.requestAnimationFrame(syncLanguageNav);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleSync, { once: true });
  } else {
    scheduleSync();
  }

  window.addEventListener("load", scheduleSync, { once: true });
  window.addEventListener("popstate", scheduleSync);
  window.addEventListener("hashchange", scheduleSync);
  window.addEventListener("mintlify:navigation", scheduleSync);

  var timer = null;
  new MutationObserver(function () {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(scheduleSync, 100);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
