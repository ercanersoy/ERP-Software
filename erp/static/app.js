/*
 * ERP-Software - keyboard navigation, touch support and small helpers.
 *
 * The program is built so that every screen can be used with the keyboard
 * alone (see the "?" overlay in base.html) as well as with a mouse or a touch
 * screen.  This file adds:
 *
 *   - single key shortcuts: elements with data-key="x" are activated by "x",
 *   - arrow key movement between elements marked with data-nav,
 *   - Esc to go back (the server puts the target URL into <body data-back>),
 *   - Ctrl+S / Ctrl+Enter to submit the main form (form[data-main]),
 *   - a warning before unsaved form input is thrown away,
 *   - protection against submitting a form twice (double taps / clicks),
 *   - clickable table rows (tr[data-href]),
 *   - the live monitor of sensor data (table#monitor).
 *
 * No external libraries are used and the page works without JavaScript too:
 * every action is also a normal link or form.  The code is plain ES5 so that
 * old browsers on shop floor terminals keep working.
 */
(function () {
  "use strict";

  /* True on devices whose main input is a finger (phones, tablets, kiosks).
   * Used to avoid behaviour that only makes sense with a hardware keyboard,
   * e.g. focusing a text field on load, which pops up the on-screen keyboard. */
  var touchOnly = !!(window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches);

  /* Is the user typing into a control?  Then single letter shortcuts must not
   * fire ("n" in a name field must type an "n", not open a new record). */
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

  /* Elements that take part in arrow key navigation (menu items, table rows). */
  function navItems() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-nav]"));
  }

  /* Move the focus ``step`` items up or down, or to the first/last item. */
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

  /* Activate a link, button or clickable row.  Returns true when something happened. */
  function go(el) {
    if (!el) return false;
    if (el.tagName === "A" || el.tagName === "BUTTON") { el.click(); return true; }
    var href = el.getAttribute("data-href");
    if (href) { window.location.href = href; return true; }
    return false;
  }

  /* ------------------------------------------------------------------ unsaved changes
   * A form counts as "dirty" once the user changed one of its controls.  Leaving
   * the page then asks first: with our own text for in-app navigation (Esc, the
   * back button) and with the browser's standard question for everything else
   * (closing the tab, the browser's back button, following another link).
   * Forms marked data-nodirty (login, confirmations) are not tracked. */
  var dirty = false;
  var leaving = false;  // set once the user agreed to leave, so we do not ask twice

  function trackedForm(el) {
    var form = el && el.form ? el.form : (el && el.closest ? el.closest("form") : null);
    return form && form.hasAttribute("data-main") && !form.hasAttribute("data-nodirty") ? form : null;
  }

  function markDirty(e) {
    if (trackedForm(e.target)) dirty = true;
  }
  document.addEventListener("input", markDirty);
  document.addEventListener("change", markDirty);

  /* Ask before throwing away unsaved input; true means "go ahead". */
  function confirmLeave() {
    if (!dirty || leaving) return true;
    if (window.confirm(document.body.getAttribute("data-unsaved") || "")) {
      leaving = true;
      return true;
    }
    return false;
  }

  /* Navigate within the application, respecting unsaved changes. */
  function navigate(url) {
    if (confirmLeave()) window.location.href = url;
  }

  window.addEventListener("beforeunload", function (e) {
    if (dirty && !leaving) {
      e.preventDefault();
      e.returnValue = "";  // older browsers need a value to show their dialog
    }
  });

  /* ------------------------------------------------------------------ double submission
   * A slow network plus an impatient double tap would otherwise create two
   * records.  The second submit of the same form is ignored for a while.  The
   * buttons are not disabled: a disabled button would drop its name/value from
   * the request (e.g. "save and new").  The guard is lifted after a few seconds
   * because download forms (exports, backups) stay on the same page. */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.getAttribute("data-busy")) { e.preventDefault(); return; }
    form.setAttribute("data-busy", "1");
    form.setAttribute("aria-busy", "true");
    dirty = false;  // the input is being saved, no warning needed any more
    setTimeout(function () {
      form.removeAttribute("data-busy");
      form.removeAttribute("aria-busy");
    }, 4000);
  });

  /* Pages restored from the browser's back/forward cache keep their old state. */
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    Array.prototype.forEach.call(document.querySelectorAll("form[data-busy]"), function (form) {
      form.removeAttribute("data-busy");
      form.removeAttribute("aria-busy");
    });
    leaving = false;
  });

  /* ------------------------------------------------------------------ shortcut help */
  var helpOpener = null;  // element that had the focus before the overlay opened

  function overlay() { return document.getElementById("keyhelp"); }

  function toggleHelp(show) {
    var box = overlay();
    if (!box) return;
    var visible = show === undefined ? box.hidden : show;
    if (visible === !box.hidden) return;
    box.hidden = !visible;
    if (visible) {
      helpOpener = document.activeElement;
      box.querySelector("[data-close]").focus();
    } else if (helpOpener && helpOpener.focus) {
      helpOpener.focus();  // give the focus back where it was (accessibility)
      helpOpener = null;
    }
  }

  /* Submit the main form of the page (Ctrl+S).  requestSubmit() runs the
   * browser's validation and submit handlers, form.submit() would skip them. */
  function submitMain() {
    var form = document.querySelector("form[data-main]");
    if (!form) return false;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
    return true;
  }

  /* ------------------------------------------------------------------ keyboard */
  document.addEventListener("keydown", function (e) {
    var target = document.activeElement;
    var key = e.key;

    if (key === "Escape") {
      // Esc closes the overlay, then leaves a text field, then goes back.
      var box = overlay();
      if (box && !box.hidden) { toggleHelp(false); e.preventDefault(); return; }
      if (isTyping(target)) { target.blur(); e.preventDefault(); return; }
      var back = document.body.getAttribute("data-back");
      if (back) { navigate(back); e.preventDefault(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (key === "s" || key === "S" || key === "Enter")) {
      if (submitMain()) e.preventDefault();
      return;
    }
    if (key === "F1") { toggleHelp(); e.preventDefault(); return; }
    // Everything below is a plain key: leave modified keys and typing alone.
    if (e.altKey || e.ctrlKey || e.metaKey || isTyping(target)) return;

    switch (key) {
      case "ArrowDown": moveFocus(1); e.preventDefault(); return;
      case "ArrowUp": moveFocus(-1); e.preventDefault(); return;
      case "Home": if (navItems().length) { moveFocus(0, "first"); e.preventDefault(); } return;
      case "End": if (navItems().length) { moveFocus(0, "last"); e.preventDefault(); } return;
      case "Enter":
        // Links and buttons handle Enter themselves; rows need help.
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
        // "0" is the main menu unless the page uses it as a menu key itself.
        if (!document.querySelector('[data-key="0"]')) { navigate("/"); e.preventDefault(); return; }
        break;
      case "Delete":
        key = "del";
        break;
    }
    if (key.length > 3) return;  // named keys such as "Shift" or "Tab"
    // Remove quotes and backslashes so the key can not break the CSS selector.
    var el = document.querySelector('[data-key="' + key.toLowerCase().replace(/["\\]/g, "") + '"]');
    if (el) { e.preventDefault(); go(el); }
  });

  /* ------------------------------------------------------------------ mouse / touch */
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t.closest) return;
    // Table rows act as one big link, except where a real control was hit.
    var row = t.closest("tr[data-href]");
    if (row && !t.closest("a, button, input, select, textarea, label")) {
      navigate(row.getAttribute("data-href"));
      return;
    }
    if (t.closest("[data-close]")) { toggleHelp(false); return; }
    if (t.closest("[data-keyhelp]")) { toggleHelp(true); return; }
    // A click on the dimmed area around the dialog closes it, like Esc.
    if (t.id === "keyhelp") { toggleHelp(false); return; }
    // The back button follows the same rules as Esc.
    var backLink = t.closest("[data-back-link]");
    if (backLink && !confirmLeave()) e.preventDefault();
  });

  document.addEventListener("DOMContentLoaded", function () {
    // Put the keyboard focus where work starts: the first field with an error,
    // else the first field of the main form, else the first menu item or row.
    // On touch screens a focused text field would open the on-screen keyboard
    // and cover half of the page, so only fields with errors get the focus.
    if (!document.querySelector("[autofocus]")) {
      var errorField = document.querySelector("form[data-main] .row.has-error input, form[data-main] .row.has-error select, form[data-main] .row.has-error textarea");
      var field = errorField || (touchOnly ? null : document.querySelector(
        "form[data-main] input:not([type=hidden]):not([type=checkbox]):not([disabled]), form[data-main] select, form[data-main] textarea"));
      if (field) {
        field.focus();
        if (touchOnly && field.scrollIntoView) field.scrollIntoView({ block: "center" });
      } else if (!touchOnly && navItems().length) {
        navItems()[0].focus();
      }
    }
    initMonitor();
  });

  /* ------------------------------------------------------------------ live monitor
   * Shows the newest records of a sensor data screen and reloads them at the
   * reading interval.  The interval can be changed on the page; "p" pauses. */
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

    // Rebuild the table body.  textContent (not innerHTML) keeps record values
    // from being interpreted as HTML.
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
        .then(schedule);  // the next request starts only after this one ended
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
      pause.setAttribute("aria-pressed", paused ? "true" : "false");
      if (paused) clearTimeout(timer); else load();
    });
    load();
  }
})();
