// Rearrange Mintlify's native topbar selectors, Mintlify-docs style:
// [logo] [English ˅] ........ [Search] [Get Started] [theme ◐]
// The language selector sits flat right of the logo; the theme selector is a
// round icon button at the far right. Only wrapper elements are moved — the
// React-managed triggers stay inside their own parents so Radix/React
// re-renders never lose their DOM nodes.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var THEME_ITEM_ID = "aisa-theme-control";

  // Production serves the docs under /docs, so zh pages live at /docs/zh/...
  function isZh() {
    return /^(?:\/docs)?\/zh(?:\/|$)/.test(window.location.pathname);
  }

  function setText(node, value) {
    if (node.textContent !== value) node.textContent = value;
  }

  function setAttr(el, name, value) {
    if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }

  function setLanguageLabel(trigger) {
    var label = trigger.querySelector("span");
    if (!label) return;

    if (isZh()) {
      setText(label, "简体中文");
      setAttr(trigger, "aria-label", "语言");
    } else {
      setText(label, "English");
      setAttr(trigger, "aria-label", "Language");
    }
  }

  function relabelThemeMenu() {
    var menu = document.getElementById("theme-preference-menu-content");
    if (!menu) return;

    var labels = isZh()
      ? { system: "跟随系统", light: "浅色", dark: "深色" }
      : { system: "System", light: "Light", dark: "Dark" };

    var map = {
      "system": labels.system,
      "follow system": labels.system,
      "跟随系统": labels.system,
      "light": labels.light,
      "浅色": labels.light,
      "dark": labels.dark,
      "深色": labels.dark
    };

    menu.querySelectorAll('[role="menuitem"], [role="menuitemradio"]').forEach(function (item) {
      var walker = document.createTreeWalker(item, NodeFilter.SHOW_TEXT);
      var node;
      while ((node = walker.nextNode())) {
        var target = map[node.textContent.trim().toLowerCase()];
        if (target && node.textContent !== target) node.textContent = target;
      }
    });
  }

  function placeLanguage(navbar, langTrigger) {
    setLanguageLabel(langTrigger);

    var langWrap = langTrigger.parentElement;
    var logo = navbar.querySelector("img") && navbar.querySelector("img").closest("a");
    var logoBox = logo && logo.parentElement;
    if (!langWrap || !logoBox) return;

    langWrap.classList.add("aisa-language-wrapper");
    if (langWrap.parentNode !== logoBox || langWrap.previousElementSibling !== logo) {
      logoBox.insertBefore(langWrap, logo.nextSibling);
    }
  }

  function placeTheme(navbar, themeTrigger) {
    var themeWrap = themeTrigger.parentElement;
    if (!themeWrap) return;
    themeWrap.classList.add("aisa-theme-wrapper");

    var item = document.getElementById(THEME_ITEM_ID);
    if (!item) {
      item = document.createElement("li");
      item.id = THEME_ITEM_ID;
    }
    if (themeWrap.parentNode !== item) item.appendChild(themeWrap);

    // Keep the theme button last, right after the CTA.
    var cta = document.getElementById("topbar-cta-button");
    var ctaItem = cta && (cta.tagName === "LI" ? cta : cta.closest("li"));
    if (ctaItem && ctaItem.parentNode) {
      if (item.parentNode !== ctaItem.parentNode || ctaItem.nextElementSibling !== item) {
        ctaItem.parentNode.insertBefore(item, ctaItem.nextSibling);
      }
    } else if (!item.parentNode) {
      var fallback =
        navbar.querySelector("ul.flex") ||
        navbar.querySelector("[class*='justify-end']") ||
        navbar;
      fallback.appendChild(item);
    }
  }

  function syncHeaderControls() {
    var navbar = document.getElementById("navbar");
    if (!navbar) return;

    // Only the desktop topbar triggers (inside lg:flex areas); mobile menus may
    // render their own copies, which must stay where Mintlify puts them.
    var langTrigger = navbar.querySelector('[class~="lg:flex"] #localization-select-trigger');
    var themeTrigger = navbar.querySelector('[class~="lg:flex"] #theme-preference-menu-trigger');
    if (langTrigger) placeLanguage(navbar, langTrigger);
    if (themeTrigger) placeTheme(navbar, themeTrigger);

    relabelThemeMenu();
  }

  // setTimeout instead of requestAnimationFrame: rAF is frozen in background
  // tabs, which would leave the header unsynced after soft navigations.
  function scheduleSync() {
    window.setTimeout(syncHeaderControls, 0);
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

  // Trailing throttle, not debounce: pages with continuously animating DOM
  // (chat widgets etc.) would starve a debounce timer forever.
  var pending = false;
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    window.setTimeout(function () {
      pending = false;
      scheduleSync();
    }, 120);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
