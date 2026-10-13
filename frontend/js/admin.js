/* Administrator dashboard. Every request is authorised again on the server. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  function table(headers, rows) {
    const tb = h("tbody");
    rows.forEach(function (r) { tb.appendChild(h("tr", {}, r)); });
    return h("div", { class: "table-wrap" },
      h("table", {}, h("thead", {}, h("tr", {}, headers.map(function (x) {
        return h("th", { class: x.num ? "num" : null, text: x.label || x });
      }))), tb));
  }
  const td = function (text, num) { return h("td", { class: num ? "num" : null, text: text === null || text === undefined ? "-" : String(text) }); };

  function hbars(entries, fmt) {
    const max = Math.max.apply(null, entries.map(function (e) { return e[1]; }).concat([1]));
    return h("div", { class: "hbars" }, entries.map(function (e) {
      return h("div", { class: "hbar" }, h("span", { text: e[0] }),
        h("div", { class: "track", title: e[0] + ": " + (fmt ? fmt(e[1]) : e[1]) }, h("div", { class: "fill", style: { width: (100 * e[1] / max).toFixed(1) + "%" } })),
        h("span", { class: "v", text: fmt ? fmt(e[1]) : e[1] }));
    }));
  }

  function activityChart(a) {
    const max = Math.max.apply(null, a.posted.concat(a.delivered).concat([1]));
    const cols = h("div", { class: "cols", role: "img", "aria-label": "Donations posted and delivered per day for 14 days" });
    const labels = h("div", { class: "cols-labels" });
    a.days.forEach(function (day, i) {
      const tip = day + ": " + a.posted[i] + " posted, " + a.delivered[i] + " delivered";
      cols.appendChild(h("div", { class: "col", title: tip },
        h("span", { class: "a", style: { height: (100 * a.posted[i] / max) + "%" } }),
        h("span", { class: "b", style: { height: (100 * a.delivered[i] / max) + "%" } })));
      labels.appendChild(h("span", { text: i % 2 === 0 ? day.slice(5) : "" }));
    });
    return h("div", {}, cols, labels, h("div", { class: "legend" }, h("span", {}, h("i", { class: "a" }), "Posted"), h("span", {}, h("i", { class: "b" }), "Delivered")));
  }

  function tabs(container, options, current, onChange) {
    FR.clear(container);
    options.forEach(function (o) {
      container.appendChild(h("button", { type: "button", role: "tab", "aria-selected": o[0] === current ? "true" : "false", text: o[1],
        onclick: function (e) {
          FR.$all("button", container).forEach(function (b) { b.setAttribute("aria-selected", "false"); });
          e.currentTarget.setAttribute("aria-selected", "true");
          onChange(o[0]);
        } }));
    });
  }

  async function init() {
    await FR.initApp(["admin"]);

    /* ---------- Overview ---------- */
    async function loadOverview() {
      const s = await API.get("/api/admin/stats");
      const ds = s.donations_by_status;
      FR.clear(FR.$("#stats")).append(
        Dash.stat("Food offered", FR.kg(s.kg_offered), Object.values(ds).reduce(function (a, b) { return a + b; }, 0) + " donations"),
        Dash.stat("Food matched", FR.kg(s.kg_matched), s.match_rate_pct + "% of offered"),
        Dash.stat("Delivered", FR.kg(s.kg_delivered), s.completed_deliveries + " deliveries"),
        Dash.stat("Pending", String(s.pending), "posted or matched"),
        Dash.stat("Delayed", String(s.delayed), "accepted, pickup window passed"),
        Dash.stat("Open reports", String(s.open_reports)));
      const u = s.users_by_role;
      FR.clear(FR.$("#users-by-role")).appendChild(hbars([["Donors", u.donor], ["NGOs", u.ngo], ["Volunteers", u.volunteer], ["Admins", u.admin]]));
      FR.clear(FR.$("#status-chart")).appendChild(hbars(Object.keys(ds).map(function (k) { return [FR.STATUS_LABELS[k], ds[k]]; })));
      const cats = Object.keys(s.kg_by_category).map(function (k) { return [k, s.kg_by_category[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
      const catBox = FR.clear(FR.$("#category-chart"));
      if (cats.length) catBox.appendChild(hbars(cats, FR.kg)); else FR.empty(catBox, "No donations yet");
      FR.clear(FR.$("#activity-chart")).appendChild(activityChart(s.activity));
      FR.clear(FR.$("#match-summary")).appendChild(h("dl", { class: "kv" },
        h("dt", { text: "Recommendations" }), h("dd", { text: Object.keys(s.recommendations).map(function (k) { return s.recommendations[k] + " " + k; }).join(", ") || "none" }),
        h("dt", { text: "NGO acceptance rate" }), h("dd", { text: s.ngo_acceptance_rate_pct === null ? "-" : s.ngo_acceptance_rate_pct + "% of decided recommendations" }),
        h("dt", { text: "Avg accepted score" }), h("dd", { text: s.avg_accepted_score === null ? "-" : FR.num(s.avg_accepted_score) }),
        h("dt", { text: "Avg accepted distance" }), h("dd", { text: FR.km(s.avg_accepted_distance_km) }),
        h("dt", { text: "Completed pickups" }), h("dd", { text: String(s.completed_pickups) })));
    }

    /* ---------- Donations ---------- */
    let donStatus = "";
    async function loadDonations(page) {
      const box = FR.$("#donations-list");
      FR.loading(box);
      try {
        const q = donStatus === "delayed" ? "delayed=true" : (donStatus ? "status=" + donStatus : "");
        const data = await API.get("/api/admin/donations?page=" + (page || 1) + "&page_size=15&" + q);
        FR.clear(box);
        if (!data.items.length) { FR.empty(box, "No donations match this filter"); return; }
        box.appendChild(table(["#", "Food", "Donor", { label: "Qty", num: true }, "Status", "Recipient", "Usable until", ""],
          data.items.map(function (d) {
            const acts = h("td", { class: "item-actions" }, h("a", { class: "btn btn-secondary btn-sm", href: "match-details.html?id=" + d.id, text: "Open" }));
            if (["posted", "matched", "accepted"].indexOf(d.status) !== -1) {
              const c = h("button", { class: "btn btn-danger btn-sm", type: "button", text: "Cancel" });
              c.addEventListener("click", function () {
                if (!window.confirm("Cancel donation #" + d.id + "?")) return;
                Dash.action(c, function () { return API.post("/api/admin/donations/" + d.id + "/cancel"); }, "Donation cancelled.", function () { return Promise.all([loadDonations(data.page), loadOverview()]); })();
              });
              acts.appendChild(c);
            }
            return [td(d.id), td(d.food_name), td(d.donor_org || d.donor_name), td(FR.kg(d.quantity_kg), true),
              h("td", {}, FR.badge(d.status), " ", Dash.urgentBadge(d)), td(d.ngo_name), td(FR.dateTime(d.expires_at)), acts];
          })));
        Dash.pager(box, data, loadDonations);
      } catch (e) { FR.errorBox(box, e); }
    }
    tabs(FR.$("#donation-tabs"), [["", "All"], ["matched", "Matched"], ["posted", "Posted"], ["accepted", "Accepted"], ["delayed", "Delayed"],
      ["picked_up", "Picked up"], ["delivered", "Delivered"], ["expired", "Expired"], ["cancelled", "Cancelled"]], "",
    function (v) { donStatus = v; loadDonations(1); });

    /* ---------- Matches ---------- */
    let matchStatus = "";
    async function loadMatches(page) {
      const box = FR.$("#matches-list");
      FR.loading(box);
      try {
        const data = await API.get("/api/admin/matches?page=" + (page || 1) + "&page_size=15" + (matchStatus ? "&status=" + matchStatus : ""));
        FR.clear(box);
        if (!data.items.length) { FR.empty(box, "No recommendations yet"); return; }
        box.appendChild(table(["Created", "Donation", "NGO", { label: "Rank", num: true }, { label: "Score", num: true }, { label: "F", num: true },
          { label: "G", num: true }, { label: "C", num: true }, { label: "Q", num: true }, { label: "P", num: true }, { label: "Dist.", num: true }, "Status"],
        data.items.map(function (m) {
          return [td(FR.dateTime(m.created_at)), h("td", {}, h("a", { href: "match-details.html?id=" + m.donation_id, text: "#" + m.donation_id })),
            td(m.ngo_name), td(m.rank, true), td(FR.num(m.score), true), td(FR.num(m.freshness, 2), true), td(FR.num(m.proximity, 2), true),
            td(FR.num(m.capacity_fit, 2), true), td(FR.num(m.demand_fit, 2), true), td(FR.num(m.priority, 2), true), td(FR.km(m.distance_km), true),
            h("td", {}, FR.badge(m.status))];
        })));
        Dash.pager(box, data, loadMatches);
      } catch (e) { FR.errorBox(box, e); }
    }
    tabs(FR.$("#match-tabs"), [["", "All"], ["proposed", "Proposed"], ["accepted", "Accepted"], ["rejected", "Declined"], ["superseded", "Superseded"]], "",
      function (v) { matchStatus = v; loadMatches(1); });

    /* ---------- Users & NGOs ---------- */
    let userRole = "";
    async function loadUsers(page) {
      const box = FR.$("#users-list");
      FR.loading(box);
      try {
        const data = await API.get("/api/admin/users?page=" + (page || 1) + "&page_size=15" + (userRole ? "&role=" + userRole : ""));
        FR.clear(box);
        box.appendChild(table(["Name", "Email", "Role", "Organisation", "Joined", "Status", ""], data.items.map(function (u) {
          const btn = h("button", { class: "btn btn-sm " + (u.is_active ? "btn-danger" : "btn-secondary"), type: "button", text: u.is_active ? "Deactivate" : "Reactivate" });
          btn.addEventListener("click", Dash.action(btn, function () { return API.patch("/api/admin/users/" + u.id + "/active", { is_active: !u.is_active }); },
            u.is_active ? "Account deactivated." : "Account reactivated.", function () { return loadUsers(data.page); }));
          return [td(u.full_name + (u.is_demo ? " (demo)" : "")), td(u.email), td(FR.ROLE_LABEL[u.role]), td(u.organization), td(FR.dateTime(u.created_at)),
            h("td", {}, FR.badge(u.is_active ? "accepted" : "cancelled", u.is_active ? "Active" : "Deactivated")), h("td", {}, u.role === "admin" ? null : btn)];
        })));
        Dash.pager(box, data, loadUsers);
      } catch (e) { FR.errorBox(box, e); }
    }
    tabs(FR.$("#user-tabs"), [["", "All"], ["donor", "Donors"], ["ngo", "NGOs"], ["volunteer", "Volunteers"], ["admin", "Admins"]], "",
      function (v) { userRole = v; loadUsers(1); });

    async function loadNgos() {
      const box = FR.$("#ngos-list");
      FR.loading(box);
      try {
        const ngos = await API.get("/api/admin/ngos");
        FR.clear(box);
        if (!ngos.length) { FR.empty(box, "No NGOs registered"); return; }
        box.appendChild(table(["Organisation", { label: "Capacity", num: true }, { label: "Unmet demand", num: true }, { label: "Priority", num: true }, "Accepts", "Location"],
          ngos.map(function (n) {
            return [td(n.org_name), td(FR.kg(n.capacity_kg), true), td(FR.kg(n.demand_kg), true), td(FR.num(n.priority, 2), true),
              td(n.categories.join(", ")), td(n.latitude.toFixed(4) + ", " + n.longitude.toFixed(4))];
          })));
      } catch (e) { FR.errorBox(box, e); }
    }

    /* ---------- Reports ---------- */
    let reportStatus = "open";
    async function loadReports() {
      const box = FR.$("#reports-list");
      FR.loading(box);
      try {
        const rows = await API.get("/api/admin/reports?status=" + reportStatus);
        FR.clear(box);
        if (!rows.length) { FR.empty(box, reportStatus === "open" ? "No open reports" : "Nothing here", "Users can report problematic donations or accounts."); return; }
        const cards = h("div", { class: "cards" });
        rows.forEach(function (r) {
          const target = r.entity_type === "donation" ? h("a", { href: "match-details.html?id=" + r.entity_id, text: "Donation #" + r.entity_id }) : h("span", { text: "User #" + r.entity_id });
          const acts = [];
          if (r.status === "open") {
            const deact = h("input", { type: "checkbox" });
            const cancel = h("input", { type: "checkbox" });
            const note = h("input", { type: "text", placeholder: "Resolution note (optional)", maxlength: 500 });
            const resolve = h("button", { class: "btn btn-primary btn-sm", type: "button", text: "Resolve" });
            const dismiss = h("button", { class: "btn btn-secondary btn-sm", type: "button", text: "Dismiss" });
            const send = function (status, btn) {
              return Dash.action(btn, function () {
                return API.post("/api/admin/reports/" + r.id + "/resolve", { status: status, resolution_note: note.value.trim() || null,
                  deactivate_user: deact.checked, cancel_donation: cancel.checked });
              }, "Report " + status + ".", function () { return Promise.all([loadReports(), loadOverview()]); });
            };
            resolve.addEventListener("click", send("resolved", resolve));
            dismiss.addEventListener("click", send("dismissed", dismiss));
            acts.push(h("div", { class: "stack", style: { width: "100%" } }, note,
              h("div", { class: "checks" }, h("label", { class: "check" }, deact, r.entity_type === "user" ? "Deactivate this user" : "Deactivate the donor"),
                r.entity_type === "donation" ? h("label", { class: "check" }, cancel, "Cancel the donation") : null),
              h("div", { class: "item-actions" }, resolve, dismiss)));
          }
          cards.appendChild(h("article", { class: "item" },
            h("div", { class: "item-head" }, h("div", {}, h("h3", {}, target), h("div", { class: "small muted", text: "Reported by " + r.reporter_name + " on " + FR.dateTime(r.created_at) })), FR.badge(r.status)),
            h("p", { class: "explain", text: r.reason }), r.resolution_note ? h("p", { class: "small", text: "Resolution: " + r.resolution_note }) : null, acts));
        });
        box.appendChild(cards);
      } catch (e) { FR.errorBox(box, e); }
    }
    tabs(FR.$("#report-tabs"), [["open", "Open"], ["resolved", "Resolved"], ["dismissed", "Dismissed"]], "open", function (v) { reportStatus = v; loadReports(); });

    /* ---------- Audit ---------- */
    async function loadAudit(page) {
      const box = FR.$("#audit-list");
      FR.loading(box);
      try {
        const data = await API.get("/api/admin/audit?page=" + (page || 1) + "&page_size=20");
        FR.clear(box);
        box.appendChild(table(["Time", "Actor", "Action", "Entity", "Details"], data.items.map(function (a) {
          return [td(FR.dateTime(a.created_at)), td(a.actor_name || (a.actor_id ? "#" + a.actor_id : "system")), td(a.action.replace(/_/g, " ")),
            td(a.entity_type + (a.entity_id ? " #" + a.entity_id : "")), h("td", {}, h("code", { text: a.details || "" }))];
        })));
        Dash.pager(box, data, loadAudit);
      } catch (e) { FR.errorBox(box, e); }
    }

    /* ---------- Benchmark ---------- */
    function renderBenchmark(res) {
      const box = FR.clear(FR.$("#benchmark-body"));
      if (!res.available) { FR.empty(box, "No benchmark results yet", "Run the synthetic benchmark to generate results and charts."); return; }
      const ds = res.dataset;
      box.appendChild(h("p", { class: "notice", text: res.note + " Dataset: seed " + ds.seed + ", " + ds.offers + " offers, " + ds.ngos + " NGOs, " +
        FR.kg(ds.offered_kg) + " offered (report: " + FR.kg(ds.targets.offered_kg) + "), capacity " + FR.kg(ds.capacity_kg) +
        " (report: " + FR.kg(ds.targets.capacity_kg) + "), demand " + FR.kg(ds.demand_kg) + " (report: " + FR.kg(ds.targets.demand_kg) + ")." }));
      const metrics = [["quantity_fulfillment_pct", "Fulfilment %"], ["waste_ratio_pct", "Waste %"], ["urgent_rescue_pct", "Urgent rescue %"],
        ["avg_distance_km", "Avg distance km"], ["full_match_pct", "Full match %"]];
      const rows = Object.keys(res.methods).map(function (k) {
        const m = res.methods[k];
        return [td(m.label + " (calculated)")].concat(metrics.map(function (x) { return td(m[x[0]], true); }));
      });
      const ref = res.reported_proposed_reference;
      rows.push([td("Proposed - published in report (reference)")].concat(metrics.map(function (x) { return td(ref[x[0]], true); })));
      box.appendChild(table(["Method"].concat(metrics.map(function (x) { return { label: x[1], num: true }; })), rows));
      const stamp = "?v=" + Date.now();
      box.appendChild(h("div", { class: "grid-2", style: { marginTop: "16px" } },
        (res.charts || []).map(function (src) { return h("img", { class: "chart-img", src: src + stamp, alt: "Benchmark chart " + src.split("/").pop(), loading: "lazy" }); })));
    }
    async function loadBenchmark() {
      try { renderBenchmark(await API.get("/api/admin/benchmark")); } catch (e) { FR.errorBox(FR.$("#benchmark-body"), e); }
    }
    const runBtn = FR.$("#run-benchmark");
    runBtn.addEventListener("click", async function () {
      FR.busy(runBtn, true);
      try { renderBenchmark(await API.post("/api/admin/benchmark/run")); FR.toast("Benchmark finished.", "success"); }
      catch (e) { FR.toast(e.message, "error"); }
      finally { FR.busy(runBtn, false); }
    });
    const maintBtn = FR.$("#run-maintenance");
    maintBtn.addEventListener("click", async function () {
      FR.busy(maintBtn, true);
      try {
        const r = await API.post("/api/admin/maintenance/run");
        FR.toast("Sweep done: " + r.expired + " expired, " + r.warned + " expiry warnings, " + r.overdue + " overdue alerts.", "success");
        await Promise.all([loadOverview(), loadDonations(1)]);
      } catch (e) { FR.toast(e.message, "error"); }
      finally { FR.busy(maintBtn, false); }
    });

    await loadOverview().catch(function (e) { FR.errorBox(FR.$("#stats"), e); });
    await Promise.all([loadDonations(1), loadMatches(1), loadUsers(1), loadNgos(), loadReports(), loadAudit(1), loadBenchmark()]);
  }

  init().catch(function (e) { FR.errorBox(FR.$("#content"), e); });
})();
