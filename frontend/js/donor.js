/* Donor pages: overview dashboard, post-a-donation form, donation list. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  function cancelAction(d, reload) {
    if (["posted", "matched", "accepted"].indexOf(d.status) === -1) return null;
    const btn = h("button", { class: "btn btn-danger btn-sm", type: "button", text: "Cancel" });
    btn.addEventListener("click", function () {
      if (!window.confirm("Cancel '" + d.food_name + "'?")) return;
      Dash.action(btn, function () { return API.post("/api/donations/" + d.id + "/cancel"); }, "Donation cancelled.", reload)();
    });
    return btn;
  }

  /* ---------- Overview ---------- */
  async function initDashboard() {
    const me = await FR.initApp(["donor"]);
    FR.$("#greeting").textContent = "Welcome, " + me.user.full_name;
    const statsBox = FR.$("#stats");
    const activeBox = FR.$("#active");
    const recBox = FR.$("#top-recs");

    async function load() {
      FR.loading(activeBox);
      try {
        const [summary, active] = await Promise.all([
          API.get("/api/donations/summary"),
          API.get("/api/donations?page_size=50"),
        ]);
        const s = summary.by_status;
        FR.clear(statsBox).append(
          Dash.stat("Open offers", String(s.posted + s.matched), "posted or awaiting NGO acceptance"),
          Dash.stat("In progress", String(s.accepted + s.picked_up), FR.kg(summary.kg_in_progress)),
          Dash.stat("Delivered", String(s.delivered), FR.kg(summary.kg_delivered) + " rescued"),
          Dash.stat("Expired or cancelled", String(s.expired + s.cancelled)));
        const current = active.items.filter(function (d) { return ["posted", "matched", "accepted", "picked_up"].indexOf(d.status) !== -1; });
        FR.clear(activeBox);
        if (!current.length) {
          FR.empty(activeBox, "No active donations", "Post surplus food to get ranked NGO recommendations.",
            h("a", { class: "btn btn-primary", href: "create-donation.html", text: "Post a donation" }));
        } else {
          const cards = h("div", { class: "cards" });
          current.forEach(function (d) {
            cards.appendChild(Dash.donationCard(d, { actions: [
              h("a", { class: "btn btn-secondary btn-sm", href: "match-details.html?id=" + d.id, text: "View matches & status" }),
              cancelAction(d, load)] }));
          });
          activeBox.appendChild(cards);
        }
        // Top recommendation for the most urgent open offer
        const openOffers = current.filter(function (d) { return d.status === "matched"; })
          .sort(function (a, b) { return a.remaining_hours - b.remaining_hours; });
        FR.clear(recBox);
        if (!openOffers.length) {
          FR.empty(recBox, "Nothing awaiting a decision", "Recommendations appear here once you post food.");
        } else {
          const d = openOffers[0];
          const [matches, w] = await Promise.all([API.get("/api/matches/donation/" + d.id), Scoring.weights()]);
          recBox.appendChild(h("p", { class: "small muted", text: "Most urgent open offer: " + d.food_name + " (" + FR.hours(d.remaining_hours) + " left)" }));
          if (matches[0]) recBox.appendChild(Dash.matchCard(matches[0], w));
          recBox.appendChild(h("a", { class: "btn btn-ghost btn-sm", href: "match-details.html?id=" + d.id, text: "See all " + matches.length + " recommendations" }));
        }
      } catch (e) { FR.errorBox(activeBox, e); }
    }
    await load();
  }

  /* ---------- Post a donation ---------- */
  async function initCreate() {
    await FR.initApp(["donor"]);
    const form = FR.$("#donation-form");
    const errBox = FR.$("#form-error");
    const meta = await API.get("/api/meta");
    meta.categories.forEach(function (c) { form.category.appendChild(h("option", { value: c.key, text: c.label })); });
    meta.units.forEach(function (u) { form.unit.appendChild(h("option", { value: u, text: u })); });

    const now = new Date();
    form.prepared_at.value = FR.toLocalInput(new Date(now.getTime() - 60 * 60000));
    form.pickup_start.value = FR.toLocalInput(now);
    form.pickup_end.value = FR.toLocalInput(new Date(now.getTime() + 3 * 3600000));

    const kgField = FR.$("#kg-field");
    function syncUnit() {
      const needsKg = ["kg", "litres"].indexOf(form.unit.value) === -1;
      kgField.classList.toggle("hidden", !needsKg);
      form.quantity_kg.required = needsKg;
    }
    form.unit.addEventListener("change", syncUnit);
    syncUnit();
    FR.$("#locate").addEventListener("click", function (e) { FR.geolocate(form.latitude, form.longitude, e.currentTarget); });

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      errBox.classList.add("hidden");
      if (!form.reportValidity()) return;
      const start = new Date(form.pickup_start.value);
      const end = new Date(form.pickup_end.value);
      if (end <= start) {
        errBox.textContent = "The pickup window must end after it starts.";
        errBox.classList.remove("hidden");
        form.pickup_end.setAttribute("aria-invalid", "true");
        return;
      }
      const body = {
        food_name: form.food_name.value.trim(), category: form.category.value,
        quantity: Number(form.quantity.value), unit: form.unit.value,
        quantity_kg: form.quantity_kg.value ? Number(form.quantity_kg.value) : null,
        preparation_details: form.preparation_details.value.trim() || null,
        prepared_at: form.prepared_at.value ? new Date(form.prepared_at.value).toISOString() : null,
        usable_life_hours: Number(form.usable_life_hours.value),
        pickup_address: form.pickup_address.value.trim(),
        latitude: Number(form.latitude.value), longitude: Number(form.longitude.value),
        pickup_start: start.toISOString(), pickup_end: end.toISOString(),
        notes: form.notes.value.trim() || null,
      };
      const btn = form.querySelector("button[type=submit]");
      FR.busy(btn, true);
      try {
        const d = await API.post("/api/donations", body);
        const file = form.image.files[0];
        if (file) {
          const fd = new FormData();
          fd.append("file", file);
          try { await API.upload("/api/donations/" + d.id + "/image", fd); }
          catch (err) { FR.toast("Donation posted, but the photo was not saved: " + err.message, "error"); }
        }
        window.location.href = "match-details.html?id=" + d.id;
      } catch (err) {
        errBox.textContent = err.message;
        errBox.classList.remove("hidden");
        FR.showFieldErrors(form, err);
        FR.busy(btn, false);
      }
    });
  }

  /* ---------- Donation list ---------- */
  async function initList() {
    await FR.initApp(["donor"]);
    const box = FR.$("#list");
    const tabs = FR.$("#status-tabs");
    let status = "";
    let page = 1;
    const filters = [["", "All"], ["matched", "Matched"], ["posted", "Posted"], ["accepted", "Accepted"],
      ["picked_up", "Picked up"], ["delivered", "Delivered"], ["expired", "Expired"], ["cancelled", "Cancelled"]];
    filters.forEach(function (f) {
      tabs.appendChild(h("button", { type: "button", role: "tab", "aria-selected": f[0] === status ? "true" : "false", text: f[1],
        onclick: function (e) {
          FR.$all("button", tabs).forEach(function (b) { b.setAttribute("aria-selected", "false"); });
          e.currentTarget.setAttribute("aria-selected", "true");
          status = f[0]; page = 1; load();
        } }));
    });
    async function load() {
      FR.loading(box);
      try {
        const data = await API.get("/api/donations?page=" + page + "&page_size=10" + (status ? "&status=" + status : ""));
        FR.clear(box);
        if (!data.items.length) {
          FR.empty(box, "No donations here", status ? "Try another status filter." : "Post your first donation to get started.",
            status ? null : h("a", { class: "btn btn-primary", href: "create-donation.html", text: "Post a donation" }));
          return;
        }
        const cards = h("div", { class: "cards" });
        data.items.forEach(function (d) {
          cards.appendChild(Dash.donationCard(d, { actions: [
            h("a", { class: "btn btn-secondary btn-sm", href: "match-details.html?id=" + d.id, text: "Details" }), cancelAction(d, load)] }));
        });
        box.appendChild(cards);
        Dash.pager(box, data, function (p) { page = p; load(); });
      } catch (e) { FR.errorBox(box, e); }
    }
    await load();
  }

  const page = document.body.dataset.page;
  const run = { "donor-dashboard": initDashboard, "create-donation": initCreate, donations: initList }[page];
  if (run) run().catch(function (e) { FR.errorBox(FR.$("#content"), e); });
})();
