/**
 * Shared helpers for /agents and /developers static docs pages.
 * No dependencies. Progressive enhancement only.
 */
(function () {
  "use strict";

  var MCP_URL = "https://api.githired.ca/mcp";
  var MCP_CONFIG = JSON.stringify(
    { mcpServers: { githired: { url: MCP_URL } } },
    null,
    2
  );

  function announce(msg) {
    var live = document.getElementById("docs-live");
    if (live) live.textContent = msg;
  }

  async function copyText(text, button) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      if (button) {
        var prev = button.getAttribute("data-label") || button.textContent;
        button.setAttribute("data-label", prev);
        button.setAttribute("data-copied", "true");
        button.textContent = "Copied";
        announce("Copied to clipboard");
        window.setTimeout(function () {
          button.removeAttribute("data-copied");
          button.textContent = button.getAttribute("data-label") || prev;
        }, 1600);
      }
    } catch (err) {
      announce("Copy failed — select the text manually");
    }
  }

  function bindCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var kind = btn.getAttribute("data-copy");
        if (kind === "mcp-url") return copyText(MCP_URL, btn);
        if (kind === "mcp-config") return copyText(MCP_CONFIG, btn);
        var sel = btn.getAttribute("data-copy-target");
        if (sel) {
          var el = document.querySelector(sel);
          if (el) return copyText(el.textContent.trim(), btn);
        }
        var inline = btn.getAttribute("data-copy-text");
        if (inline) return copyText(inline, btn);
      });
    });
  }

  async function loadHealth() {
    var el = document.getElementById("api-status");
    if (!el) return;
    el.setAttribute("data-state", "loading");
    el.innerHTML =
      '<span class="docs-status-dot" aria-hidden="true"></span>' +
      "<span>Checking API health…</span>";
    try {
      var res = await fetch("https://api.githired.ca/api/v1/health", {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      var data = await res.json();
      var fresh = data && data.dataset && data.dataset.fresh === true;
      var status = data && data.status === "ok" && fresh ? "ok" : "degraded";
      var count = (data.dataset && data.dataset.count) || "?";
      var gen = (data.dataset && data.dataset.generated_at) || "";
      var age = data.dataset && data.dataset.age_hours;
      var updated = "";
      if (gen) {
        var d = new Date(gen);
        if (!isNaN(d.getTime())) {
          updated = d.toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          });
        }
      }
      var label =
        status === "ok"
          ? "API healthy · " +
            count +
            " jobs" +
            (updated ? " · updated " + updated : "")
          : "API degraded · dataset may be stale" +
            (age != null ? " (" + age + "h)" : "");
      el.setAttribute("data-state", status);
      el.innerHTML =
        '<span class="docs-status-dot" aria-hidden="true"></span><span>' +
        label +
        "</span>";
      el.setAttribute("aria-label", label);
      if (gen) el.title = "Dataset generated " + gen;
    } catch (err) {
      el.setAttribute("data-state", "error");
      el.innerHTML =
        '<span class="docs-status-dot" aria-hidden="true"></span>' +
        "<span>Could not reach api.githired.ca</span>";
    }
  }

  function bindDocsNav() {
    var devToggle = document.getElementById("nav-dev-toggle");
    var devMenu = document.getElementById("nav-dev-menu");
    var menuToggle = document.getElementById("menu-toggle");
    var mobileMenu = document.getElementById("mobile-menu");

    function setOpen(el, toggle, open) {
      if (!el || !toggle) return;
      if (open) {
        el.removeAttribute("hidden");
        el.hidden = false;
        el.classList.add("is-open");
      } else {
        el.setAttribute("hidden", "");
        el.hidden = true;
        el.classList.remove("is-open");
      }
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    if (devToggle && devMenu) {
      devToggle.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var open = devToggle.getAttribute("aria-expanded") !== "true";
        setOpen(devMenu, devToggle, open);
        if (menuToggle) setOpen(mobileMenu, menuToggle, false);
      });
    }

    if (menuToggle && mobileMenu) {
      menuToggle.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var open = menuToggle.getAttribute("aria-expanded") !== "true";
        setOpen(mobileMenu, menuToggle, open);
        if (open) {
          menuToggle.setAttribute("aria-label", "Close menu");
          document.body.classList.add("menu-open");
        } else {
          menuToggle.setAttribute("aria-label", "Open menu");
          document.body.classList.remove("menu-open");
        }
        if (devToggle) setOpen(devMenu, devToggle, false);
      });
    }

    document.addEventListener("click", function (e) {
      if (!e.target.closest("#nav-developers") && devToggle) {
        setOpen(devMenu, devToggle, false);
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (devToggle) setOpen(devMenu, devToggle, false);
      if (menuToggle) {
        setOpen(mobileMenu, menuToggle, false);
        menuToggle.setAttribute("aria-label", "Open menu");
        document.body.classList.remove("menu-open");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindCopyButtons();
    bindDocsNav();
    loadHealth();
  });
})();
