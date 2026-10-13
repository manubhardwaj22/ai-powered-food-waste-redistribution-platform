/* NGO / food-bank dashboard: recommended offers, incoming donations, capacity & demand. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  async function init() {
    let me = await FR.initApp(["ngo"]);
    FR.$("#org-name").textContent = me.ngo ? me.ngo.org_name : me.user.full_name;
    const statsBox = FR.$("#stats");
    const offersBox = FR.$("#offers-list");
    const assignedBox = FR.$("#assigned-list");
    const tabs = FR.$("#assigned-tabs");
    const form = FR.$("#needs-form");
    let assignedStatus = "accepted";

    /* Needs form */
    const meta = await API.get("/api/meta");
    const catBox = FR.$("#needs-categories");
    meta.categories.forEach(function (c) {
      catBox.appendChild(h("label", { class: "check" }, h("input", { type: "checkbox", name: "accepted_categories", value: c.key }), c.label));
    });
    function fillForm(p) {
      form.capacity_kg.value = p.capacity_kg;
      form.demand_kg.value = p.demand_kg;
      form.priority.value = p.priority;
      form.address.value = p.address;
      form.latitude.value = p.latitude;
      form.longitude.value = p.longitude;
      form.contact_phone.value = p.contact_phone || "";
      FR.$all("input[name=accepted_categories]", form).forEach(function (c) { c.checked = p.categories.indexOf(c.value) !== -1; });
    }
    fillForm(me.ngo);
    FR.$("#locate").addEventListener("click", function (e) { FR.geolocate(form.latitude, form.longitude, e.currentTarget); });
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const cats = FR.$all("input[name=accepted_categories]:checked", form).map(function (c) { return c.value; });
      if (!cats.length) { FR.toast("Select at least one accepted food category.", "error"); return; }
      const btn = form.querySelector("button[type=submit]");
      FR.busy(btn, true);
      try {
        const p = await API.patch("/api/ngo/profile", {
          capacity_kg: Number(form.capacity_kg.value), demand_kg: Number(form.demand_kg.value),
          priority: Number(form.priority.value), address: form.address.value.trim(),
          latitude: Number(form.latitude.value), longitude: Number(form.longitude.value),
          contact_phone: form.contact_phone.value.trim() || null, accepted_categories: cats,
        });
        me.ngo = p;
        fillForm(p);
        FR.toast("Needs updated. Open donations were re-matched.", "success");
        await Promise.all([loadStats(), loadOffers()]);
      } catch (err) { FR.toast(err.message, "error"); FR.showFieldErrors(form, err); }
      finally { FR.busy(btn, false); }
    });

    async function loadStats() {
      const s = await API.get("/api/ngo/stats");
      FR.clear(statsBox).append(
        Dash.stat("Offers awaiting you", String(s.pending_offers)),
        Dash.stat("Available capacity", FR.kg(s.capacity_kg), "after reservations"),
        Dash.stat("Unmet demand", FR.kg(s.demand_kg)),
        Dash.stat("Incoming", FR.kg(s.kg_incoming), s.accepted + " accepted, " + s.in_transit + " in transit"),
        Dash.stat("Received", FR.kg(s.kg_received), s.delivered + " deliveries"));
    }

    async function loadOffers() {
      FR.loading(offersBox);
      try {
        const [rows, w] = await Promise.all([API.get("/api/ngo/recommendations"), Scoring.weights()]);
        FR.clear(offersBox);
        if (!rows.length) {
          FR.empty(offersBox, "No offers recommended right now",
            "Offers appear when a donation fits your accepted categories, capacity, unmet demand and location. Keep your needs up to date below.");
          return;
        }
        const cards = h("div", { class: "cards" });
        rows.forEach(function (r) {
          const m = r.match;
          const d = r.donation;
          const acc = h("button", { class: "btn btn-primary btn-sm", type: "button", text: "Accept donation" });
          acc.addEventListener("click", Dash.action(acc, function () { return API.post("/api/matches/" + m.id + "/accept"); },
            "Accepted. Please inspect the food on arrival.", refreshAll));
          const rej = h("button", { class: "btn btn-secondary btn-sm", type: "button", text: "Decline" });
          rej.addEventListener("click", function () {
            const reason = window.prompt("Reason for declining (optional):", "");
            if (reason === null) return;
            Dash.action(rej, function () { return API.post("/api/matches/" + m.id + "/reject", { reason: reason || null }); }, "Offer declined.", refreshAll)();
          });
          const breakdown = h("details", {}, h("summary", { class: "small", text: "Score " + FR.num(m.score) + " - why this offer?" }),
            h("div", { style: { marginTop: "10px" } }, Scoring.scoreBar(m, w), Scoring.scoreLegend(m, w), h("p", { class: "explain", style: { marginTop: "10px" }, text: m.explanation })));
          cards.appendChild(Dash.donationCard(d, { showDonor: true, distance: m.distance_km, extra: breakdown,
            actions: [acc, rej, h("a", { class: "btn btn-ghost btn-sm", href: "match-details.html?id=" + d.id, text: "Details" })] }));
        });
        offersBox.appendChild(cards);
      } catch (e) { FR.errorBox(offersBox, e); }
    }

    async function loadAssigned(page) {
      FR.loading(assignedBox);
      try {
        const data = await API.get("/api/ngo/donations?page=" + (page || 1) + "&page_size=10&status=" + assignedStatus);
        FR.clear(assignedBox);
        if (!data.items.length) { FR.empty(assignedBox, "Nothing in this list", "Accepted donations and their delivery progress appear here."); return; }
        const cards = h("div", { class: "cards" });
        data.items.forEach(function (d) {
          cards.appendChild(Dash.donationCard(d, { showDonor: true, extra: d.task_status
            ? h("div", { class: "small" }, "Delivery task: ", FR.badge(d.task_status, d.task_status === "open" ? "Waiting for a volunteer" : null)) : null,
          actions: [h("a", { class: "btn btn-secondary btn-sm", href: "match-details.html?id=" + d.id, text: "Track" }),
            h("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Report a problem", onclick: function () { FR.reportDialog("donation", d.id); } })] }));
        });
        assignedBox.appendChild(cards);
        Dash.pager(assignedBox, data, loadAssigned);
      } catch (e) { FR.errorBox(assignedBox, e); }
    }

    [["accepted", "Accepted"], ["picked_up", "In transit"], ["delivered", "Received"], ["expired", "Expired"], ["cancelled", "Cancelled"]]
      .forEach(function (t) {
        tabs.appendChild(h("button", { type: "button", role: "tab", "aria-selected": t[0] === assignedStatus ? "true" : "false", text: t[1],
          onclick: function (e) {
            FR.$all("button", tabs).forEach(function (b) { b.setAttribute("aria-selected", "false"); });
            e.currentTarget.setAttribute("aria-selected", "true");
            assignedStatus = t[0];
            loadAssigned(1);
          } }));
      });

    async function refreshAll() {
      me = await API.get("/api/auth/me");
      fillForm(me.ngo);
      await Promise.all([loadStats(), loadOffers(), loadAssigned(1)]);
      FR.refreshNotifCount();
    }
    await refreshAll();
  }

  init().catch(function (e) { FR.errorBox(FR.$("#content"), e); });
})();
