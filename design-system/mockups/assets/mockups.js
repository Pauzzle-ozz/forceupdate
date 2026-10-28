// forceupdate — script des maquettes (E13). Rien de l'interface réelle : seulement
// de quoi parcourir les états d'un écran. Paramètres d'adresse : ?theme=light|dark|system
// et ?state=<état> (les captures d'écran s'en servent).

(function () {
  "use strict";

  var params = new URLSearchParams(location.search);

  function readTheme() {
    var fromUrl = params.get("theme");
    if (fromUrl) return fromUrl;
    try { return localStorage.getItem("fu-mock-theme") || "system"; } catch (e) { return "system"; }
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    try { localStorage.setItem("fu-mock-theme", theme); } catch (e) { /* stockage indisponible */ }
    document.querySelectorAll("[data-theme-choice]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-theme-choice") === theme));
    });
  }

  // Le thème est posé avant l'affichage (script chargé dans <head>, sans defer).
  applyTheme(readTheme());

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(readTheme());

    document.querySelectorAll("[data-theme-choice]").forEach(function (b) {
      b.addEventListener("click", function () { applyTheme(b.getAttribute("data-theme-choice")); });
    });

    // ----- États -----
    var select = document.getElementById("mock-state");
    function applyState(state) {
      document.body.setAttribute("data-state", state);
      document.querySelectorAll("[data-show]").forEach(function (el) {
        var states = el.getAttribute("data-show").split(/\s+/);
        el.hidden = states.indexOf(state) === -1;
      });
      if (select) {
        select.value = state;
        var option = select.selectedOptions[0];
        var sheet = option && option.getAttribute("data-open-sheet");
        if (sheet) setTimeout(function () { openSheet(sheet); }, 0);
        else closeSheets();
        var step = Number((option && option.getAttribute("data-step")) || 0);
        document.querySelectorAll(".stepper li").forEach(function (li, i) {
          if (!step) return;
          li.classList.toggle("is-done", i + 1 < step);
          if (i + 1 === step) li.setAttribute("aria-current", "step");
          else li.removeAttribute("aria-current");
          if (li.hasAttribute("data-hide-upload")) li.hidden = state === "fichier-envoye";
        });
      }
      var url = new URL(location.href);
      url.searchParams.set("state", state);
      history.replaceState(null, "", url);
      document.dispatchEvent(new Event("mock:state"));
    }
    if (select) {
      select.addEventListener("change", function () { applyState(select.value); });
      applyState(params.get("state") || select.value);
    }
    document.querySelectorAll("[data-go-state]").forEach(function (b) {
      b.addEventListener("click", function (ev) {
        ev.preventDefault();
        applyState(b.getAttribute("data-go-state"));
        var main = document.getElementById("contenu");
        if (main) { main.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }
      });
    });

    // ----- Menu des petites largeurs -----
    var menuButton = document.querySelector(".menu-button");
    var nav = document.getElementById("nav");
    if (menuButton && nav) {
      menuButton.addEventListener("click", function () {
        var open = nav.classList.toggle("is-open");
        menuButton.setAttribute("aria-expanded", String(open));
      });
    }

    // ----- Panneau latéral -----
    var opener = null;
    function openSheet(id) {
      var sheet = document.getElementById(id);
      var scrim = document.getElementById(id + "-scrim");
      if (!sheet) return;
      opener = document.activeElement;
      sheet.hidden = false;
      if (scrim) scrim.hidden = false;
      var title = sheet.querySelector("[data-autofocus]") || sheet;
      title.focus();
    }
    function closeSheets() {
      document.querySelectorAll(".sheet, .dialog, .scrim").forEach(function (el) {
        if (!el.hasAttribute("data-show")) el.hidden = true;
      });
      if (opener) { opener.focus(); opener = null; }
    }
    document.querySelectorAll("[data-open]").forEach(function (b) {
      b.addEventListener("click", function () { openSheet(b.getAttribute("data-open")); });
    });
    document.querySelectorAll("[data-close], .scrim").forEach(function (b) {
      b.addEventListener("click", closeSheets);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeSheets();
    });
    if (params.get("open")) openSheet(params.get("open"));

    // ----- Copier une commande -----
    var live = document.getElementById("live");
    document.querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var text = b.getAttribute("data-copy");
        var done = function () {
          var label = b.querySelector(".label");
          if (label) {
            label.textContent = "Copié";
            setTimeout(function () { label.textContent = "Copier"; }, 2000);
          }
          if (live) live.textContent = "Commande copiée.";
        };
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
        else done();
      });
    });

    // ----- Boutons à bascule (filtres segmentés) -----
    document.querySelectorAll(".segmented").forEach(function (group) {
      group.addEventListener("click", function (ev) {
        var b = ev.target.closest("button");
        if (!b) return;
        group.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        var table = document.getElementById(group.getAttribute("data-filters"));
        if (table) filterTable(table);
      });
    });

    // ----- Filtre du tableau des dépendances -----
    function filterTable(table) {
      var input = document.querySelector('[data-filter="' + table.id + '"]');
      var seg = document.querySelector('[data-filters="' + table.id + '"] [aria-pressed="true"]');
      var q = input ? input.value.trim().toLowerCase() : "";
      var kind = seg ? seg.getAttribute("data-value") : "all";
      var shown = 0;
      table.querySelectorAll("tbody tr[data-name]").forEach(function (tr) {
        var ok = (!q || tr.getAttribute("data-name").indexOf(q) !== -1) &&
          (kind === "all" || tr.getAttribute("data-kind") === kind);
        tr.hidden = !ok;
        if (ok) shown++;
      });
      var count = document.querySelector('[data-count="' + table.id + '"]');
      if (count) count.textContent = shown + (shown > 1 ? " dépendances" : " dépendance");
    }
    document.querySelectorAll("[data-filter]").forEach(function (input) {
      input.addEventListener("input", function () {
        filterTable(document.getElementById(input.getAttribute("data-filter")));
      });
    });

    // ----- Écran 5 : sélection des mises à jour -----
    var updates = Array.prototype.slice.call(document.querySelectorAll(".update[data-update]"));
    function radios(u) { return Array.prototype.slice.call(u.querySelectorAll('input[type="radio"]')); }
    function refresh() {
      var count = 0, fixes = 0, majors = 0, files = {}, locks = {}, total = 0, vulns = 0;
      updates.forEach(function (u) {
        if (u.closest("[hidden]")) return;
        total++;
        vulns += Number(u.getAttribute("data-vulns") || 0);
        var box = u.querySelector(".update-toggle");
        var chosen = radios(u).filter(function (r) { return r.checked; })[0];
        u.classList.toggle("is-on", !!chosen);
        if (box) box.checked = !!chosen;
        if (!chosen) return;
        count++;
        fixes += Number(chosen.getAttribute("data-fixes") || 0);
        if (chosen.getAttribute("data-gap") === "major") majors++;
        (chosen.getAttribute("data-files") || "").split(" ").forEach(function (f) { if (f) files[f] = 1; });
        (chosen.getAttribute("data-lock") || "").split(" ").forEach(function (f) { if (f) locks[f] = 1; });
      });
      var set = function (key, value) {
        document.querySelectorAll('[data-sum="' + key + '"]').forEach(function (el) { el.textContent = value; });
      };
      set("count", count);
      set("fixes", fixes);
      set("left", vulns - fixes);
      set("total", total);
      set("vulns", vulns);
      set("majors", majors);
      set("files", Object.keys(files).length);
      set("locks", Object.keys(locks).length);
      set("file-list", Object.keys(files).join(", ") || "aucun");
      set("lock-list", Object.keys(locks).join(", ") || "aucun");
      document.querySelectorAll("[data-needs-selection]").forEach(function (b) {
        b.toggleAttribute("disabled", count === 0);
      });
      var majorWarn = document.getElementById("major-warning");
      if (majorWarn) majorWarn.hidden = majors === 0;
    }
    updates.forEach(function (u) {
      var box = u.querySelector(".update-toggle");
      if (box) {
        box.addEventListener("change", function () {
          if (box.checked) {
            var def = u.querySelector('input[type="radio"][data-default]') || radios(u)[0];
            if (def) def.checked = true;
          } else {
            radios(u).forEach(function (r) { r.checked = false; });
          }
          refresh();
        });
      }
      radios(u).forEach(function (r) { r.addEventListener("change", refresh); });
    });
    document.querySelectorAll('[data-action="reset"]').forEach(function (b) {
      b.addEventListener("click", function () {
        updates.forEach(function (u) {
          radios(u).forEach(function (r) { r.checked = r.hasAttribute("data-default"); });
        });
        refresh();
      });
    });
    document.querySelectorAll('[data-action="none"]').forEach(function (b) {
      b.addEventListener("click", function () {
        updates.forEach(function (u) { radios(u).forEach(function (r) { r.checked = false; }); });
        refresh();
      });
    });
    if (updates.length) {
      refresh();
      document.addEventListener("mock:state", refresh);
    }
  });
})();
