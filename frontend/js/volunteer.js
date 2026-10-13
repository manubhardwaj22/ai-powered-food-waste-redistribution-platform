/* Volunteer / driver dashboard: availability, task board and delivery updates. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  /** Link to an external route planner. In-app distances are straight-line only. */
  function routeLink(t) {
    const url = "https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=" +
      t.pickup_lat + "%2C" + t.pickup_lon + "%3B" + t.ngo_lat + "%2C" + t.ngo_lon;
    return h("a", { class: "btn btn-ghost btn-sm", href: url, target: "_blank", rel: "noopener noreferrer", text: "Open route in OpenStreetMap" });
  }

  function taskCard(t, actions, showContacts) {
    return h("article", { class: "item" },
      h("div", { class: "item-head" },
        h("div", {}, h("h3", { text: t.food_name }), h("div", { class: "small muted", text: t.category + ", " + FR.kg(t.quantity_kg) })),
        h("div", { class: "row" },
          t.remaining_hours > 0 && t.remaining_hours <= 6 && ["open", "accepted", "picked_up"].indexOf(t.status) !== -1
            ? FR.badge("urgent", "Urgent: " + FR.hours(t.remaining_hours) + " left") : null,
          FR.badge(t.status))),
      h("dl", { class: "kv" },
        h("dt", { text: "Pickup" }), h("dd", { text: t.pickup_address + (showContacts && t.donor_name ? " - " + t.donor_name + (t.donor_phone ? ", " + t.donor_phone : "") : "") }),
        h("dt", { text: "Pickup window" }), h("dd", { text: FR.dateTime(t.pickup_start) + " to " + FR.dateTime(t.pickup_end) }),
        h("dt", { text: "Deliver to" }), h("dd", { text: t.ngo_name + ", " + t.ngo_address + (showContacts && t.ngo_phone ? " (" + t.ngo_phone + ")" : "") }),
        h("dt", { text: "Distances" }), h("dd", { text: (t.distance_from_you_km !== null && t.distance_from_you_km !== undefined ? FR.km(t.distance_from_you_km) + " from you to pickup, " : "") +
          FR.km(t.distance_km) + " pickup to NGO (straight line)" }),
        t.accepted_at ? [h("dt", { text: "Accepted" }), h("dd", { text: FR.dateTime(t.accepted_at) })] : null,
        t.picked_up_at ? [h("dt", { text: "Picked up" }), h("dd", { text: FR.dateTime(t.picked_up_at) })] : null,
        t.delivered_at ? [h("dt", { text: "Delivered" }), h("dd", { text: FR.dateTime(t.delivered_at) })] : null),
      t.eligible === false && t.status === "open" ? h("p", { class: "notice", style: { margin: "0" }, text: "Not eligible: " + t.ineligible_reason }) : null,
      h("div", { class: "item-actions" }, actions, routeLink(t)));
  }

  async function init() {
    const me = await FR.initApp(["volunteer"]);
    const form = FR.$("#profile-form");
    const availBox = FR.$("#available-list");
    const mineBox = FR.$("#mine-list");
    const doneBox = FR.$("#done-list");
    const statsBox = FR.$("#stats");
    const availToggle = FR.$("#availability");

    function fill(v) {
      form.area.value = v.area;
      form.latitude.value = v.latitude;
      form.longitude.value = v.longitude;
      form.vehicle_type.value = v.vehicle_type;
      form.vehicle_capacity_kg.value = v.vehicle_capacity_kg;
      form.max_distance_km.value = v.max_distance_km;
      form.constraints.value = v.constraints || "";
      availToggle.checked = v.is_available;
      FR.$("#availability-label").textContent = v.is_available ? "You are available for pickups" : "You are currently unavailable";
    }
    fill(me.volunteer);

    availToggle.addEventListener("change", async function () {
      try {
        const v = await API.patch("/api/volunteer/profile", { is_available: availToggle.checked });
        fill(v);
        FR.toast(v.is_available ? "You are now available." : "You are now unavailable.", "success");
        await loadAvailable();
      } catch (e) { availToggle.checked = !availToggle.checked; FR.toast(e.message, "error"); }
    });
    FR.$("#locate").addEventListener("click", function (e) { FR.geolocate(form.latitude, form.longitude, e.currentTarget); });
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const btn = form.querySelector("button[type=submit]");
      FR.busy(btn, true);
      try {
        const v = await API.patch("/api/volunteer/profile", {
          area: form.area.value.trim(), latitude: Number(form.latitude.value), longitude: Number(form.longitude.value),
          vehicle_type: form.vehicle_type.value, vehicle_capacity_kg: Number(form.vehicle_capacity_kg.value),
          max_distance_km: Number(form.max_distance_km.value), constraints: form.constraints.value.trim() || null,
        });
        fill(v);
        FR.toast("Profile saved.", "success");
        await loadAvailable();
      } catch (err) { FR.toast(err.message, "error"); FR.showFieldErrors(form, err); }
      finally { FR.busy(btn, false); }
    });

    async function loadAvailable() {
      FR.loading(availBox);
      try {
        const tasks = await API.get("/api/volunteer/tasks/available");
        FR.clear(availBox);
        if (!tasks.length) { FR.empty(availBox, "No open pickup tasks", "Tasks appear when an NGO accepts a donation."); return; }
        const cards = h("div", { class: "cards" });
        tasks.forEach(function (t) {
          const btn = h("button", { class: "btn btn-primary btn-sm", type: "button", text: "Accept task", disabled: !t.eligible });
          btn.addEventListener("click", Dash.action(btn, function () { return API.post("/api/volunteer/tasks/" + t.id + "/accept"); },
            "Task accepted. Contact details are now visible under My tasks.", refresh));
          cards.appendChild(taskCard(t, [btn], false));
        });
        availBox.appendChild(cards);
      } catch (e) { FR.errorBox(availBox, e); }
    }

    async function loadMine() {
      FR.loading(mineBox);
      try {
        const tasks = await API.get("/api/volunteer/tasks/mine");
        const active = tasks.filter(function (t) { return t.status === "accepted" || t.status === "picked_up"; });
        const done = tasks.filter(function (t) { return t.status === "delivered" || t.status === "cancelled"; });
        FR.clear(statsBox).append(
          Dash.stat("Active tasks", String(active.length)),
          Dash.stat("Deliveries completed", String(tasks.filter(function (t) { return t.status === "delivered"; }).length)),
          Dash.stat("Food delivered", FR.kg(tasks.filter(function (t) { return t.status === "delivered"; })
            .reduce(function (s, t) { return s + t.quantity_kg; }, 0))));
        FR.clear(mineBox);
        if (!active.length) FR.empty(mineBox, "No active tasks", "Accept an available task to start a pickup.");
        else {
          const cards = h("div", { class: "cards" });
          active.forEach(function (t) {
            const next = t.status === "accepted" ? ["picked_up", "Confirm pickup"] : ["delivered", "Confirm delivery"];
            const btn = h("button", { class: "btn btn-primary btn-sm", type: "button", text: next[1] });
            btn.addEventListener("click", Dash.action(btn, function () { return API.post("/api/volunteer/tasks/" + t.id + "/status", { status: next[0] }); },
              next[0] === "picked_up" ? "Pickup confirmed." : "Delivery confirmed. Thank you!", refresh));
            const rep = h("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Report a problem", onclick: function () { FR.reportDialog("donation", t.donation_id); } });
            cards.appendChild(taskCard(t, [btn, rep], true));
          });
          mineBox.appendChild(cards);
        }
        FR.clear(doneBox);
        if (!done.length) { FR.empty(doneBox, "No completed tasks yet"); return; }
        const tbl = h("table", {}, h("thead", {}, h("tr", {}, ["Food", "Delivered to", "Quantity", "Picked up", "Delivered", "Status"].map(function (x) { return h("th", { text: x }); }))));
        const tb = h("tbody");
        done.forEach(function (t) {
          tb.appendChild(h("tr", {}, h("td", { text: t.food_name }), h("td", { text: t.ngo_name }), h("td", { class: "num", text: FR.kg(t.quantity_kg) }),
            h("td", { text: FR.dateTime(t.picked_up_at) }), h("td", { text: FR.dateTime(t.delivered_at) }), h("td", {}, FR.badge(t.status))));
        });
        tbl.appendChild(tb);
        doneBox.appendChild(h("div", { class: "table-wrap" }, tbl));
      } catch (e) { FR.errorBox(mineBox, e); }
    }

    async function refresh() {
      await Promise.all([loadAvailable(), loadMine()]);
      FR.refreshNotifCount();
    }
    await refresh();
  }

  init().catch(function (e) { FR.errorBox(FR.$("#content"), e); });
})();
