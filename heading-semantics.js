// Keep Mintlify-generated navigation labels out of the document heading outline.
// Article headings remain untouched.
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  var SELECTOR = [
    "#table-of-contents h1",
    "#table-of-contents h2",
    "#table-of-contents h3",
    "#table-of-contents h4",
    "#table-of-contents h5",
    "#table-of-contents h6",
    ".sidebar-title:is(h1, h2, h3, h4, h5, h6)"
  ].join(",");

  var scheduled = false;

  function replaceHeading(heading) {
    if (!heading || heading.dataset.headingSemanticsFixed === "true") return;

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
    scheduled = false;
    document.querySelectorAll(SELECTOR).forEach(replaceHeading);
  }

  function scheduleNormalize() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(normalizeGeneratedHeadings);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleNormalize, { once: true });
  } else {
    scheduleNormalize();
  }

  new MutationObserver(scheduleNormalize).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
