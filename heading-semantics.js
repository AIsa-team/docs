// Keep Mintlify-generated labels and recommendation cards out of the heading outline.
// Article headings remain untouched, except for the final "Related" recommendations label.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var HEADING_SELECTOR = "h1,h2,h3,h4,h5,h6";
  var GENERATED_HEADING_SELECTOR = [
    "#table-of-contents",
    ".card",
    ".card-group",
    ".sidebar-title"
  ].join(",");

  var scheduledTimer = null;
  var readyAt = Date.now() + 1200;

  function normalizedText(node) {
    return (node.textContent || "").replace(/\u200B/g, "").replace(/\s+/g, " ").trim();
  }

  function shouldReplaceHeading(heading) {
    if (!heading || heading.id === "page-title") return false;

    var text = normalizedText(heading);
    if (text === "Documentation Index") return true;
    if (text === "Related" && heading.id === "related") return true;
    if (text === "On this page") return true;

    return Boolean(heading.closest(GENERATED_HEADING_SELECTOR));
  }

  function replaceHeading(heading) {
    if (!heading || heading.dataset.headingSemanticsFixed === "true") return;
    if (!shouldReplaceHeading(heading)) return;

    var replacement = document.createElement("div");
    for (var i = 0; i < heading.attributes.length; i += 1) {
      var attr = heading.attributes[i];
      replacement.setAttribute(attr.name, attr.value);
    }
    replacement.dataset.headingSemanticsFixed = "true";

    while (heading.firstChild) replacement.appendChild(heading.firstChild);
    heading.replaceWith(replacement);
  }

  function normalizeGeneratedHeadings() {
    scheduledTimer = null;
    document.querySelectorAll(HEADING_SELECTOR).forEach(replaceHeading);
  }

  function scheduleNormalize() {
    var delay = Math.max(250, readyAt - Date.now());
    if (scheduledTimer) window.clearTimeout(scheduledTimer);
    scheduledTimer = window.setTimeout(function () {
      window.requestAnimationFrame(normalizeGeneratedHeadings);
    }, delay);
  }

  function scheduleAfterLoad() {
    readyAt = Math.max(readyAt, Date.now() + 500);
    scheduleNormalize();
  }

  if (document.readyState === "complete") scheduleAfterLoad();
  else window.addEventListener("load", scheduleAfterLoad, { once: true });

  new MutationObserver(scheduleNormalize).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
