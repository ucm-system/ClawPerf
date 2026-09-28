/* Copy buttons for code blocks.
 *
 * Material for MkDocs 9.7 ships the "clipboard.copy" translation strings but no
 * implementation in its bundle, so `content.code.copy` renders nothing. The docs
 * are full of long commands and captured reports, so we provide it: ~30 lines,
 * no dependency, wired to the same `.highlight` blocks the theme renders.
 *
 * The button is appended to each block; CSS positions it in the corner.
 */
(function () {
  function button(label, copied, done) {
    var el = document.createElement("button");
    el.type = "button";
    el.className = "clawperf-copy";
    el.title = label;
    el.setAttribute("aria-label", label);
    el.addEventListener("click", function () {
      var code = el.parentElement.querySelector("code");
      var text = code ? code.innerText : "";
      function flash() {
        el.title = copied;
        el.classList.add("is-copied");
        setTimeout(function () {
          el.title = label;
          el.classList.remove("is-copied");
        }, 1200);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(flash, flash);
      } else {
        var range = document.createRange();
        range.selectNode(code);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        try { document.execCommand("copy"); } catch (err) { /* nothing else to try */ }
        window.getSelection().removeAllRanges();
        flash();
      }
    });
    return el;
  }

  function install() {
    var lang = document.documentElement.lang || "en";
    var zh = lang.indexOf("zh") === 0;
    var label = zh ? "复制到剪贴板" : "Copy to clipboard";
    var copied = zh ? "已复制" : "Copied";
    document.querySelectorAll(".md-content .highlight").forEach(function (block) {
      // Skip if the theme (or a previous run) already put a button there.
      if (block.querySelector("button")) {
        return;
      }
      if (getComputedStyle(block).position === "static") {
        block.classList.add("clawperf-copy-host");
      }
      block.appendChild(button(label, copied));
    });
  }

  // Material swaps content in place for instant navigation; re-run when it does.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
  document.addEventListener("DOMContentSwitch", install);
})();
