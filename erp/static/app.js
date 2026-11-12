/* ERP-Software - keyboard navigation and small helpers (no external libraries). */
(function () {
  "use strict";

  function isTyping(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    var tag = el.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag === "INPUT") {
      var type = (el.getAttribute("type") || "text").toLowerCase();
      return ["checkbox", "radio", "button", "submit", "reset", "file"].indexOf(type) === -1;
    }
    return false;
  }

  function navItems() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-nav]"));
  }

  function moveFocus(step, absolute) {
    var items = navItems();
    if (!items.length) return;
    var index = items.indexOf(document.activeElement);
    if (absolute === "first") index = 0;
    else if (absolute === "last") index = items.length - 1;
    else if (index === -1) index = step > 0 ? 0 : items.length - 1;
    else index = Math.min(items.length - 1, Math.max(0, index + step));
    items[index].focus();
  }

  function go(el) {
    if (!el) return false;
    if (el.tagName === "A" || el.tagName === "BUTTON") { el.click(); return true; }
    var href = el.getAttribute("data-href");
    if (href) { window.location.href = href; return true; }
    return false;
  }

  function overlay() { return document.getElementById("keyhelp"); }

  function toggleHelp(show) {
    var box = overlay();
    if (!box) return;
    var visible = show === undefined ? box.hidden : show;
    box.hidden = !visible;
    if (visible) box.querySelector("[data-close]").focus();
  }

  function submitMain() {
    var form = document.querySelector("form[data-main]");
    if (!form) return false;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
    return true;
  }

  document.addEventListener("keydown", function (e) {
    var target = document.activeElement;
    var key = e.key;

    if (key === "Escape") {
      var box = overlay();
      if (box && !box.hidden) { toggleHelp(false); e.preventDefault(); return; }
      if (isTyping(target)) { target.blur(); e.preventDefault(); return; }
      var back = document.body.getAttribute("data-back");
      if (back) { window.location.href = back; e.preventDefault(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (key === "s" || key === "S" || key === "Enter")) {
      if (submitMain()) e.preventDefault();
      return;
    }
    if (key === "F1") { toggleHelp(); e.preventDefault(); return; }
    if (e.altKey || e.ctrlKey || e.metaKey || isTyping(target)) return;

    switch (key) {
      case "ArrowDown": moveFocus(1); e.preventDefault(); return;
      case "ArrowUp": moveFocus(-1); e.preventDefault(); return;
      case "Home": if (navItems().length) { moveFocus(0, "first"); e.preventDefault(); } return;
      case "End": if (navItems().length) { moveFocus(0, "last"); e.preventDefault(); } return;
      case "Enter":
        if (target && target.hasAttribute("data-href")) { go(target); e.preventDefault(); }
        return;
      case "PageDown": if (go(document.querySelector("[data-next]"))) e.preventDefault(); return;
      case "PageUp": if (go(document.querySelector("[data-prev]"))) e.preventDefault(); return;
      case "?": toggleHelp(); e.preventDefault(); return;
      case "/":
        var search = document.querySelector("[data-search]");
        if (search) { search.focus(); search.select(); e.preventDefault(); }
        return;
      case "0":
        if (!document.querySelector('[data-key="0"]')) { window.location.href = "/"; e.preventDefault(); return; }
        break;
      case "Delete":
        key = "del";
        break;
    }
    if (key.length > 3) return;
    var el = document.querySelector('[data-key="' + key.toLowerCase().replace(/["\\]/g, "") + '"]');
    if (el) { e.preventDefault(); go(el); }
  });

  document.addEventListener("click", function (e) {
    var row = e.target.closest ? e.target.closest("tr[data-href]") : null;
    if (row && !e.target.closest("a, button, input, select, textarea")) {
      window.location.href = row.getAttribute("data-href");
    }
    if (e.target.matches && e.target.matches("[data-close]")) toggleHelp(false);
  });

  document.addEventListener("DOMContentLoaded", function () {
    // Put the keyboard focus where work starts.
    if (!document.querySelector("[autofocus]")) {
      var field = document.querySelector("form[data-main] .row.has-error input, form[data-main] .row.has-error select, form[data-main] .row.has-error textarea")
        || document.querySelector("form[data-main] input:not([type=hidden]):not([type=checkbox]):not([disabled]), form[data-main] select, form[data-main] textarea");
      if (field) field.focus();
      else if (navItems().length) navItems()[0].focus();
    }
    initMonitor();
  });

  /* Live monitor of sensor data: refreshes at the configured reading interval. */
  function initMonitor() {
    var table = document.getElementById("monitor");
    if (!table) return;
    var tbody = table.tBodies[0];
    var status = document.getElementById("status");
    var input = document.getElementById("interval");
    var pause = document.getElementById("pause");
    var label = pause.querySelector("span");
    var interval = parseInt(table.getAttribute("data-interval"), 10) || 5000;
    var timer = null;
    var paused = false;

    function render(data) {
      while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
      data.rows.forEach(function (cells) {
        var tr = document.createElement("tr");
        cells.forEach(function (text) {
          var td = document.createElement("td");
          td.textContent = text;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      status.textContent = table.getAttribute("data-updated") + " " + data.updated;
    }

    function load() {
      fetch(table.getAttribute("data-src"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(render)
        .catch(function () { status.textContent = table.getAttribute("data-error"); })
        .then(schedule);
    }

    function schedule() {
      clearTimeout(timer);
      if (!paused) timer = setTimeout(load, interval);
    }

    input.addEventListener("change", function () {
      var v = parseInt(input.value, 10);
      if (v >= 100) { interval = v; schedule(); }
    });
    pause.addEventListener("click", function () {
      paused = !paused;
      label.textContent = label.getAttribute(paused ? "data-label-resume" : "data-label-pause");
      if (paused) clearTimeout(timer); else load();
    });
    load();
  }
})();
