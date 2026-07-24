// Group Mintlify's native theme-preference and language selectors into one
// pill control in the right-side topbar, matching the aisa.one website design:
// [ theme ˅ | 🌐 EN ˅ ]  [ Get Started ]  ← CTA stays at the far right.
// Only container elements are moved — the React-managed triggers stay inside
// their own parents so Radix/React re-renders never lose their DOM nodes.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var ITEM_ID = "aisa-header-controls";

  function isZh() {
    return window.location.pathname.indexOf("/zh") === 0;
  }

  function svgEl(tag, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(function (key) {
      el.setAttribute(key, attrs[key]);
    });
    return el;
  }

  function ensureEarthIcon(trigger) {
    if (trigger.querySelector(".aisa-language-earth-icon")) return;

    var icon = svgEl("svg", {
      class: "aisa-language-earth-icon",
      xmlns: "http://www.w3.org/2000/svg",
      width: "24",
      height: "24",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "2",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true"
    });

    [
      ["path", { d: "M21.54 15H17a2 2 0 0 0-2 2v4.54" }],
      ["path", { d: "M7 3.34V5a3 3 0 0 0 3 3a2 2 0 0 1 2 2c0 1.1.9 2 2 2a2 2 0 0 0 2-2c0-1.1.9-2 2-2h3.17" }],
      ["path", { d: "M11 21.95V18a2 2 0 0 0-2-2a2 2 0 0 1-2-2v-1a2 2 0 0 0-2-2H2.05" }],
      ["circle", { cx: "12", cy: "12", r: "10" }]
    ].forEach(function (node) {
      icon.appendChild(svgEl(node[0], node[1]));
    });

    trigger.insertBefore(icon, trigger.firstChild);
  }

  function setText(node, value) {
    if (node.textContent !== value) node.textContent = value;
  }

  function setAttr(el, name, value) {
    if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }

  function setCompactLabel(trigger) {
    var label = trigger.querySelector("span");
    if (!label) return;

    var current = (label.textContent || "").trim().toLowerCase();
    if (current.indexOf("中文") !== -1 || current === "zh" || current === "中") {
      setText(label, "中");
      setAttr(trigger, "aria-label", "语言");
    } else {
      setText(label, "EN");
      setAttr(trigger, "aria-label", "Language");
    }

    ensureEarthIcon(trigger);
    setAttr(trigger, "title", trigger.getAttribute("aria-label"));
  }

  // "System" reads as "Follow system" in the reference design; localize for zh.
  function relabelThemeMenu() {
    var menu = document.getElementById("theme-preference-menu-content");
    if (!menu) return;

    var labels = isZh()
      ? { system: "跟随系统", light: "浅色", dark: "深色" }
      : { system: "Follow system", light: "Light", dark: "Dark" };

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

  function ensureGroupItem() {
    var item = document.getElementById(ITEM_ID);
    if (item) return item;

    item = document.createElement("li");
    item.id = ITEM_ID;
    var group = document.createElement("div");
    group.className = "aisa-control-group";
    item.appendChild(group);
    return item;
  }

  function syncHeaderControls() {
    var navbar = document.getElementById("navbar");
    var langTrigger = document.getElementById("localization-select-trigger");
    var themeTrigger = document.getElementById("theme-preference-menu-trigger");
    var cta = document.getElementById("topbar-cta-button");
    if (!navbar || !langTrigger) return;

    setCompactLabel(langTrigger);

    var langWrap = langTrigger.parentElement;
    if (!langWrap) return;
    langWrap.classList.add("aisa-language-wrapper");

    // Move the trigger's own wrapper div, never the React-managed button.
    var themeWrap = null;
    if (themeTrigger) {
      themeWrap = themeTrigger.parentElement;
      if (themeWrap) themeWrap.classList.add("aisa-theme-wrapper");
    }

    var item = ensureGroupItem();
    var group = item.querySelector(".aisa-control-group");

    var divider = group.querySelector(".aisa-control-divider");
    if (!divider) {
      divider = document.createElement("span");
      divider.className = "aisa-control-divider";
      divider.setAttribute("aria-hidden", "true");
    }

    // Desired order inside the pill: theme | divider | language.
    var desired = themeWrap ? [themeWrap, divider, langWrap] : [langWrap];
    var needsReflow = desired.some(function (node, index) {
      return node.parentNode !== group || group.children[index] !== node;
    });
    if (needsReflow) {
      desired.forEach(function (node) {
        group.appendChild(node);
      });
    }

    // Place the pill right before the CTA so "Get Started" stays last.
    var ctaItem = cta && (cta.tagName === "LI" ? cta : cta.closest("li"));
    if (ctaItem && ctaItem.parentNode) {
      var parent = ctaItem.parentNode;
      if (item.parentNode !== parent || item.nextElementSibling !== ctaItem) {
        parent.insertBefore(item, ctaItem);
      }
    } else if (!item.parentNode) {
      var fallback =
        navbar.querySelector("ul.flex") ||
        navbar.querySelector("[class*='justify-end']") ||
        navbar;
      fallback.appendChild(item);
    }

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
