// Give Mintlify's "Copy page" button a visible copying → copied sequence.
// The native "Copying..." state lasts ~100ms, too short to read, so we hold our
// own copying state for a minimum time, then show a check while the native
// button says "Copied". Only attributes and CSS variables are touched; the
// React-managed children are never replaced.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var BUTTON_ID = "page-context-menu-button";
  var MIN_COPYING_MS = 650;
  var POLL_MS = 50;
  var MAX_WAIT_MS = 5000;

  function isZh() {
    return /^(?:\/docs)?\/zh(?:\/|$)/.test(window.location.pathname);
  }

  function nativeLabel(button) {
    var label = button.querySelector("span.grid > span:last-child");
    return label ? (label.textContent || "").trim() : "";
  }

  function setState(button, state) {
    if (state === "idle") {
      button.removeAttribute("data-aisa-copy");
      return;
    }
    if (button.getAttribute("data-aisa-copy") !== state) button.setAttribute("data-aisa-copy", state);
  }

  function run(button) {
    if (button.getAttribute("data-aisa-copy")) return;

    var started = Date.now();
    button.style.setProperty("--aisa-copying-label", isZh() ? '"复制中…"' : '"Copying…"');
    setState(button, "copying");

    (function poll() {
      if (!button.isConnected) return;
      var elapsed = Date.now() - started;
      var text = nativeLabel(button);

      if (elapsed >= MAX_WAIT_MS) {
        setState(button, "idle");
        return;
      }
      if (elapsed >= MIN_COPYING_MS) {
        if (/copied|已复制|复制成功/i.test(text)) {
          setState(button, "copied");
        } else if (!/copying|复制中/i.test(text)) {
          // Native button is back to idle, or the copy failed: show its text.
          setState(button, "idle");
          return;
        }
      }
      window.setTimeout(poll, POLL_MS);
    })();
  }

  // Delegated listener: the button is re-mounted on client-side navigation.
  document.addEventListener(
    "click",
    function (event) {
      var target = event.target;
      var button = target && target.closest && target.closest("#" + BUTTON_ID);
      if (button) run(button);
    },
    true
  );
})();
