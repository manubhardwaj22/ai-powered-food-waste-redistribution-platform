/* FoodRescue AI - shared UI helpers: safe DOM builder, formatting, toasts, app shell. */
(function () {
  "use strict";

  /* ---------- Safe DOM builder (never uses innerHTML with data) ---------- */
  function h(tag, attrs) {
    const node = document.createElement(tag);
    const a = attrs || {};
    Object.keys(a).forEach(function (k) {
      const v = a[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.indexOf("on") === 0 && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, String(v));
    });
    for (let i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }
  function append(node, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(node, c); }); return; }
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------- Formatting ---------- */
  function parseDate(iso) {
    if (!iso) return null;
    // The API returns naive UTC timestamps; mark them as UTC before parsing.
    const s = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z";
    const d = new Date(s);
    return isNaN(d) ? null : d;
  }
  function dateTime(iso) {
    const d = parseDate(iso);
    return d ? d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "-";
  }
  function timeOnly(iso) {
    const d = parseDate(iso);
    return d ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "-";
  }
  function hours(h) {
    if (h === null || h === undefined) return "-";
    if (h <= 0) return "expired";
    if (h < 1) return Math.round(h * 60) + " min";
    if (h < 48) return (Math.round(h * 10) / 10) + " h";
    return Math.floor(h / 24) + " d " + Math.round(h % 24) + " h";
  }
  function kg(v) {
    if (v === null || v === undefined) return "-";
    return (Math.round(v * 10) / 10).toLocaleString() + " kg";
  }
  function km(v) { return v === null || v === undefined ? "-" : (Math.round(v * 10) / 10) + " km"; }
  function num(v, d) { return v === null || v === undefined ? "-" : Number(v).toFixed(d === undefined ? 3 : d); }
  function toLocalInput(date) {
    const pad = function (n) { return String(n).padStart(2, "0"); };
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" +
      pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  const STATUS_LABELS = {
    posted: "Posted", matched: "Matched", accepted: "Accepted", picked_up: "Picked up",
    delivered: "Delivered", cancelled: "Cancelled", expired: "Expired", proposed: "Proposed",
    rejected: "Declined", superseded: "Superseded", open: "Open", resolved: "Resolved", dismissed: "Dismissed",
  };
  function badge(status, label) {
    return h("span", { class: "badge " + status, text: label || STATUS_LABELS[status] || status });
  }

  /* ---------- Feedback ---------- */
  function toast(message, type) {
    let box = $("#toasts");
    if (!box) { box = h("div", { id: "toasts", class: "toasts", "aria-live": "polite" }); document.body.appendChild(box); }
    const t = h("div", { class: "toast " + (type || ""), role: type === "error" ? "alert" : "status", text: message });
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, type === "error" ? 6500 : 4000);
  }
  function busy(btn, on) {
    if (!btn) return;
    btn.disabled = !!on;
    btn.classList.toggle("is-loading", !!on);
  }
  function loading(container, text) {
    clear(container).appendChild(h("div", { class: "loading", text: text || "Loading..." }));
  }
  function empty(container, title, body, action) {
    clear(container).appendChild(h("div", { class: "empty" }, h("strong", { text: title }), body ? h("span", { text: body }) : null,
      action ? h("div", { style: { marginTop: "12px" } }, action) : null));
  }
  function errorBox(container, err) {
    clear(container).appendChild(h("div", { class: "notice error", role: "alert", text: (err && err.message) || String(err) }));
  }
  /** Mark form inputs that the API rejected. */
  function showFieldErrors(form, err) {
    $all("[aria-invalid]", form).forEach(function (i) { i.removeAttribute("aria-invalid"); });
    $all(".field .error", form).forEach(function (e) { e.textContent = ""; });
    Object.keys((err && err.fields) || {}).forEach(function (name) {
      const input = form.elements[name];
      if (!input || !input.closest) return;
      input.setAttribute("aria-invalid", "true");
      const box = input.closest(".field") && input.closest(".field").querySelector(".error");
      if (box) box.textContent = err.fields[name];
    });
  }

  /* ---------- Geolocation helper ---------- */
  function geolocate(latInput, lonInput, btn) {
    if (!navigator.geolocation) { toast("Location is not available in this browser. Enter coordinates manually.", "error"); return; }
    busy(btn, true);
    navigator.geolocation.getCurrentPosition(function (pos) {
      latInput.value = pos.coords.latitude.toFixed(6);
      lonInput.value = pos.coords.longitude.toFixed(6);
      busy(btn, false);
      toast("Location filled in.", "success");
    }, function () {
      busy(btn, false);
      toast("Could not read your location. Enter latitude and longitude manually.", "error");
    }, { timeout: 10000 });
  }

  /* ---------- Roles and navigation ---------- */
  const HOME = {
    donor: "donor-dashboard.html", ngo: "ngo-dashboard.html",
    volunteer: "volunteer-dashboard.html", admin: "admin-dashboard.html",
  };
  const NAV = {
    donor: [["donor-dashboard.html", "Overview"], ["create-donation.html", "Post a donation"], ["donations.html", "My donations"]],
    ngo: [["ngo-dashboard.html", "Overview"], ["ngo-dashboard.html#offers", "Recommended offers"],
      ["ngo-dashboard.html#assigned", "Incoming & received"], ["ngo-dashboard.html#needs", "Capacity & demand"]],
    volunteer: [["volunteer-dashboard.html", "Overview"], ["volunteer-dashboard.html#available", "Available tasks"],
      ["volunteer-dashboard.html#mine", "My tasks"], ["volunteer-dashboard.html#profile", "Availability"]],
    admin: [["admin-dashboard.html", "Overview"], ["admin-dashboard.html#donations", "Donations"],
      ["admin-dashboard.html#matches", "Matching results"], ["admin-dashboard.html#users", "Users & NGOs"],
      ["admin-dashboard.html#reports", "Reports"], ["admin-dashboard.html#audit", "Audit log"],
      ["admin-dashboard.html#benchmark", "Benchmark"]],
  };
  const ROLE_LABEL = { donor: "Donor", ngo: "NGO / food bank", volunteer: "Volunteer", admin: "Administrator" };

  function brand(href) {
    return h("a", { class: "brand", href: href || "index.html" },
      h("img", { class: "brand-mark", src: "assets/images/logo.svg", alt: "" }), "FoodRescue AI");
  }

  function logout() {
    API.clearSession();
    window.location.href = "login.html";
  }

  function buildSidebar(me) {
    const side = $("#sidebar");
    if (!side) return;
    const here = window.location.pathname.split("/").pop() || "index.html";
    const nav = h("nav", { "aria-label": "Main" });
    (NAV[me.user.role] || []).forEach(function (item, idx) {
      const isCurrent = item[0] === here && idx === 0 || (item[0] === here && !item[0].includes("#"));
      nav.appendChild(h("a", { href: item[0], "aria-current": isCurrent ? "page" : null, text: item[1] }));
    });
    nav.appendChild(h("div", { class: "nav-label", text: "Platform" }));
    nav.appendChild(h("a", { href: "about.html", text: "How matching works" }));
    nav.appendChild(h("a", { href: "index.html", text: "Public home" }));
    clear(side).appendChild(brand(HOME[me.user.role]));
    side.appendChild(nav);
    side.appendChild(h("div", { class: "sidebar-foot" },
      h("strong", { text: me.user.full_name }),
      h("span", { text: ROLE_LABEL[me.user.role] + (me.user.is_demo ? " (demo)" : "") }),
      h("button", { class: "btn btn-sm", type: "button", onclick: logout, text: "Sign out" })));
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") side.classList.remove("open");
    });
  }

  /* ---------- Notifications ---------- */
  let notifPanel = null;
  async function refreshNotifCount() {
    const countEl = $("#notif-count");
    if (!countEl) return;
    try {
      const data = await API.get("/api/notifications?unread_only=true&limit=1");
      countEl.textContent = data.unread > 99 ? "99+" : String(data.unread);
      countEl.classList.toggle("hidden", data.unread === 0);
    } catch (e) { /* ignore transient failures */ }
  }
  async function openNotifications() {
    if (notifPanel) { notifPanel.remove(); notifPanel = null; return; }
    notifPanel = h("section", { class: "notif-panel", "aria-label": "Notifications" });
    const list = h("div");
    notifPanel.appendChild(h("header", {},
      h("strong", { text: "Notifications" }),
      h("button", {
        class: "btn btn-ghost btn-sm", type: "button", text: "Mark all read",
        onclick: async function () { await API.post("/api/notifications/read-all"); refreshNotifCount(); notifPanel.remove(); notifPanel = null; },
      })));
    notifPanel.appendChild(list);
    document.body.appendChild(notifPanel);
    loading(list);
    try {
      const data = await API.get("/api/notifications?limit=30");
      clear(list);
      if (!data.items.length) { empty(list, "No notifications yet", "Updates about your donations and tasks appear here."); return; }
      data.items.forEach(function (n) {
        list.appendChild(h("button", {
          type: "button", class: "notif-item" + (n.is_read ? "" : " unread"),
          onclick: async function () {
            if (!n.is_read) { try { await API.post("/api/notifications/" + n.id + "/read"); } catch (e) { /* ignore */ } }
            if (n.link) window.location.href = n.link; else { notifPanel.remove(); notifPanel = null; refreshNotifCount(); }
          },
        }, n.message, h("time", { text: dateTime(n.created_at) })));
      });
    } catch (e) { errorBox(list, e); }
  }
  document.addEventListener("click", function (e) {
    if (notifPanel && !notifPanel.contains(e.target) && !e.target.closest("#bell")) { notifPanel.remove(); notifPanel = null; }
  });

  function buildTopbar() {
    const actions = $("#topbar-actions");
    if (actions) {
      clear(actions).appendChild(h("button", {
        id: "bell", class: "btn btn-secondary btn-sm bell", type: "button", "aria-label": "Notifications", onclick: openNotifications,
      }, h("img", { src: "assets/images/bell.svg", alt: "", width: 18, height: 18 }),
      h("span", { id: "notif-count", class: "count hidden", text: "0" })));
    }
    const menu = $("#menu-btn");
    if (menu) menu.addEventListener("click", function (e) { e.stopPropagation(); $("#sidebar").classList.toggle("open"); });
    document.addEventListener("click", function (e) {
      const side = $("#sidebar");
      if (side && side.classList.contains("open") && !side.contains(e.target) && e.target !== menu) side.classList.remove("open");
    });
  }

  /**
   * Initialise a signed-in page: verify the session with the server, enforce the
   * page's roles client-side (the server enforces them again on every call),
   * and render the sidebar + notifications bell.
   */
  async function initApp(allowedRoles) {
    if (!API.token()) {
      window.location.href = "login.html?next=" + encodeURIComponent(window.location.pathname.split("/").pop() + window.location.search);
      return new Promise(function () {});
    }
    const me = await API.get("/api/auth/me");
    if (allowedRoles && allowedRoles.indexOf(me.user.role) === -1) {
      window.location.href = HOME[me.user.role];
      return new Promise(function () {});
    }
    buildSidebar(me);
    buildTopbar();
    refreshNotifCount();
    setInterval(refreshNotifCount, 30000);
    return me;
  }

  /* ---------- Report dialog (any signed-in user) ---------- */
  function reportDialog(entityType, entityId) {
    const reason = h("textarea", { name: "reason", required: true, minlength: 5, maxlength: 500,
      placeholder: "Describe the problem (e.g. unsafe packaging, incorrect quantity, no-show)" });
    const form = h("form", { method: "dialog", class: "stack" },
      h("h3", { text: "Report a problem" }),
      h("p", { class: "muted small", text: "An administrator will review this " + entityType + "." }),
      h("div", { class: "field" }, h("label", { text: "Reason" }), reason),
      h("div", { class: "row" },
        h("button", { class: "btn btn-primary", type: "submit", value: "send", text: "Send report" }),
        h("button", { class: "btn btn-secondary", type: "button", text: "Close", onclick: function () { dlg.close(); } })));
    const dlg = h("dialog", {}, form);
    document.body.appendChild(dlg);
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      if (reason.value.trim().length < 5) { reason.setAttribute("aria-invalid", "true"); return; }
      try {
        await API.post("/api/reports", { entity_type: entityType, entity_id: entityId, reason: reason.value.trim() });
        toast("Report sent to the administrators.", "success");
        dlg.close();
      } catch (err) { toast(err.message, "error"); }
    });
    dlg.addEventListener("close", function () { dlg.remove(); });
    dlg.showModal();
  }

  /* ---------- Public header (landing/about) ---------- */
  function initPublicHeader() {
    const toggle = $(".menu-toggle");
    if (toggle) toggle.addEventListener("click", function () {
      const nav = $(".site-nav");
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    const user = API.user();
    const slot = $("#account-link");
    if (slot && user && API.token()) {
      slot.textContent = "Open dashboard";
      slot.setAttribute("href", HOME[user.role] || "login.html");
      const reg = $("#register-link");
      if (reg) reg.classList.add("hidden");
    }
  }

  window.FR = {
    h: h, clear: clear, $: $, $all: $all, append: append,
    parseDate: parseDate, dateTime: dateTime, timeOnly: timeOnly, hours: hours, kg: kg, km: km, num: num,
    toLocalInput: toLocalInput, badge: badge, STATUS_LABELS: STATUS_LABELS, ROLE_LABEL: ROLE_LABEL, HOME: HOME,
    toast: toast, busy: busy, loading: loading, empty: empty, errorBox: errorBox, showFieldErrors: showFieldErrors,
    geolocate: geolocate, initApp: initApp, reportDialog: reportDialog, initPublicHeader: initPublicHeader,
    refreshNotifCount: refreshNotifCount, logout: logout,
  };
})();
