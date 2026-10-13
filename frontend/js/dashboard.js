/* Shared dashboard components (donation and match cards) and the match-details page. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  const SAFETY_NOTE = "Matching does not certify food safety. The donor and receiving organisation must check " +
    "condition, temperature and packaging before handover and before distribution.";

  function urgentBadge(d) {
    const open = ["posted", "matched", "accepted", "picked_up"].indexOf(d.status) !== -1;
    return open && d.remaining_hours > 0 && d.remaining_hours <= 6 ? FR.badge("urgent", "Urgent: " + FR.hours(d.remaining_hours) + " left") : null;
  }

  function donationCard(d, opts) {
    opts = opts || {};
    const open = ["posted", "matched", "accepted", "picked_up"].indexOf(d.status) !== -1;
    return h("article", { class: "item" },
      h("div", { class: "item-head" },
        h("div", {}, h("h3", {}, h("a", { href: "match-details.html?id=" + d.id, text: d.food_name })),
          h("div", { class: "small muted", text: d.category_label + (opts.showDonor && d.donor_org ? " from " + d.donor_org : "") })),
        h("div", { class: "row" }, urgentBadge(d), FR.badge(d.status))),
      h("div", { class: "meta" },
        h("span", {}, "Quantity ", h("b", { text: d.quantity + " " + d.unit + (d.unit !== "kg" ? " (" + FR.kg(d.quantity_kg) + ")" : "") })),
        open ? h("span", {}, "Usable for ", h("b", { text: FR.hours(d.remaining_hours) })) : null,
        h("span", {}, "Pickup ", h("b", { text: FR.timeOnly(d.pickup_start) + " to " + FR.dateTime(d.pickup_end) })),
        opts.distance !== undefined ? h("span", {}, "Distance ", h("b", { text: FR.km(opts.distance) })) : null,
        d.ngo_name ? h("span", {}, "Recipient ", h("b", { text: d.ngo_name })) : null),
      opts.extra || null,
      opts.actions && opts.actions.length ? h("div", { class: "item-actions" }, opts.actions) : null);
  }

  function matchCard(m, w, opts) {
    opts = opts || {};
    return h("article", { class: "item" },
      h("div", { class: "item-head" },
        h("div", { class: "row" }, h("span", { class: "rank", text: "#" + m.rank, title: "Rank by score" }),
          h("div", {}, h("h3", { text: m.ngo_name || ("NGO " + m.ngo_id) }),
            h("div", { class: "small muted", text: FR.km(m.distance_km) + " straight-line distance" }))),
        h("div", { class: "row" }, FR.badge(m.status), h("span", { class: "score-num", text: FR.num(m.score) }))),
      Scoring.scoreBar(m, w),
      Scoring.scoreLegend(m, w),
      h("p", { class: "explain", text: m.explanation }),
      opts.actions && opts.actions.length ? h("div", { class: "item-actions" }, opts.actions) : null);
  }

  function pager(container, data, onPage) {
    const pages = Math.max(1, Math.ceil(data.total / data.page_size));
    if (pages <= 1) return;
    container.appendChild(h("div", { class: "pager" },
      h("button", { class: "btn btn-secondary btn-sm", type: "button", disabled: data.page <= 1, text: "Previous",
        onclick: function () { onPage(data.page - 1); } }),
      h("span", { text: "Page " + data.page + " of " + pages + " (" + data.total + ")" }),
      h("button", { class: "btn btn-secondary btn-sm", type: "button", disabled: data.page >= pages, text: "Next",
        onclick: function () { onPage(data.page + 1); } })));
  }

  function stat(label, value, sub) {
    return h("div", { class: "stat" }, h("div", { class: "label", text: label }), h("div", { class: "value", text: value }),
      sub ? h("div", { class: "sub", text: sub }) : null);
  }

  /** Disable a button while an async action runs; toast success or error, then refresh. */
  function action(btn, fn, successMsg, after) {
    return async function () {
      FR.busy(btn, true);
      try {
        await fn();
        if (successMsg) FR.toast(successMsg, "success");
        if (after) await after();
      } catch (e) {
        FR.toast(e.message, "error");
      } finally {
        FR.busy(btn, false);
      }
    };
  }

  /* ---------------- Match details page ---------------- */
  const STEPS = ["posted", "matched", "accepted", "picked_up", "delivered"];

  function timeline(d, matches) {
    const accepted = matches.find(function (m) { return m.status === "accepted"; });
    const times = {
      posted: d.posted_at,
      matched: matches.length ? matches[matches.length - 1].created_at : null,
      accepted: accepted ? accepted.decided_at : null,
    };
    const idx = STEPS.indexOf(d.status);
    const list = h("ol", { class: "timeline", "aria-label": "Donation progress" });
    STEPS.forEach(function (s, i) {
      const cls = idx === -1 ? "" : i < idx ? "done" : i === idx ? "current" : "";
      list.appendChild(h("li", { class: cls }, FR.STATUS_LABELS[s], times[s] && i <= idx ? h("time", { text: FR.dateTime(times[s]) }) : null));
    });
    return list;
  }

  async function initMatchDetails() {
    const me = await FR.initApp();
    const id = Number(new URLSearchParams(window.location.search).get("id"));
    const root = FR.$("#content");
    if (!id) { FR.empty(root, "No donation selected", "Open a donation from your dashboard."); return; }

    async function load() {
      FR.loading(root);
      let d, matches, w;
      try {
        const history = me.user.role === "admin" || me.user.role === "donor";
        [d, matches, w] = await Promise.all([
          API.get("/api/donations/" + id),
          API.get("/api/matches/donation/" + id + (history ? "?include_history=true" : "")),
          Scoring.weights(),
        ]);
      } catch (e) { FR.errorBox(root, e); return; }
      FR.$("#page-title").textContent = d.food_name;
      document.title = d.food_name + " | FoodRescue AI";
      FR.clear(root);

      const isOwner = me.user.role === "donor" && d.donor_id === me.user.id;
      const isAdmin = me.user.role === "admin";
      const open = ["posted", "matched"].indexOf(d.status) !== -1;
      const cancellable = ["posted", "matched", "accepted"].indexOf(d.status) !== -1;

      // Summary panel
      const actions = [];
      if ((isOwner || isAdmin) && open) {
        const rerun = h("button", { class: "btn btn-secondary btn-sm", type: "button", text: "Re-run matching" });
        rerun.addEventListener("click", action(rerun, function () { return API.post("/api/matches/donation/" + id + "/run"); }, "Recommendations refreshed.", load));
        actions.push(rerun);
      }
      if ((isOwner || isAdmin) && cancellable) {
        const cancel = h("button", { class: "btn btn-danger btn-sm", type: "button", text: "Cancel donation" });
        cancel.addEventListener("click", function () {
          if (!window.confirm("Cancel this donation? Any reserved NGO capacity will be released.")) return;
          action(cancel, function () { return API.post((isAdmin ? "/api/admin/donations/" : "/api/donations/") + id + "/cancel"); }, "Donation cancelled.", load)();
        });
        actions.push(cancel);
      }
      if (!isOwner) {
        actions.push(h("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Report a problem",
          onclick: function () { FR.reportDialog("donation", id); } }));
      }

      const kv = h("dl", { class: "kv" },
        h("dt", { text: "Category" }), h("dd", { text: d.category_label }),
        h("dt", { text: "Quantity" }), h("dd", { text: d.quantity + " " + d.unit + " (" + FR.kg(d.quantity_kg) + " used for matching)" }),
        h("dt", { text: "Donor" }), h("dd", { text: (d.donor_org || d.donor_name || "-") }),
        h("dt", { text: "Prepared" }), h("dd", { text: d.prepared_at ? FR.dateTime(d.prepared_at) : "Not stated" }),
        h("dt", { text: "Posted" }), h("dd", { text: FR.dateTime(d.posted_at) }),
        h("dt", { text: "Usable until" }), h("dd", {}, FR.dateTime(d.expires_at), " ", urgentBadge(d)),
        h("dt", { text: "Pickup window" }), h("dd", { text: FR.dateTime(d.pickup_start) + " to " + FR.dateTime(d.pickup_end) }),
        h("dt", { text: "Pickup address" }), h("dd", { text: d.pickup_address + " (" + d.latitude.toFixed(4) + ", " + d.longitude.toFixed(4) + ")" }),
        d.preparation_details ? [h("dt", { text: "Handling" }), h("dd", { text: d.preparation_details })] : null,
        d.notes ? [h("dt", { text: "Notes" }), h("dd", { text: d.notes })] : null,
        d.ngo_name ? [h("dt", { text: "Recipient" }), h("dd", { text: d.ngo_name })] : null,
        d.task_status ? [h("dt", { text: "Delivery task" }), h("dd", {}, FR.badge(d.task_status))] : null);

      root.appendChild(h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("div", { class: "row" }, h("h2", { text: "Donation #" + d.id }), FR.badge(d.status)),
          h("div", { class: "item-actions" }, actions)),
        d.status === "cancelled" || d.status === "expired"
          ? h("div", { class: "notice", style: { marginBottom: "16px" }, text: "This donation is " + d.status + ". No further action is possible." })
          : timeline(d, matches),
        h("div", { class: "grid-2", style: { marginTop: "20px" } }, kv,
          d.image_url ? h("img", { class: "donation-photo", src: d.image_url, alt: "Photo of " + d.food_name }) : null),
        h("p", { class: "notice", style: { marginTop: "16px", marginBottom: "0" }, text: SAFETY_NOTE })));

      // Recommendations
      const recPanel = h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: me.user.role === "ngo" ? "Your recommendation" : "Recommended NGOs" }),
          h("a", { href: "about.html#algorithm", class: "small", text: "How scores are calculated" })));
      const list = h("div", { class: "cards" });
      recPanel.appendChild(list);
      root.appendChild(recPanel);
      const visible = matches.filter(function (m) { return m.status === "proposed" || m.status === "accepted"; });
      const shown = (isOwner || isAdmin) ? visible : matches;
      if (!shown.length) {
        FR.empty(list, open ? "No feasible NGO right now" : "No active recommendations",
          open ? "No NGO currently accepts this category with enough capacity and unmet demand within range. Matching re-runs automatically when NGOs update their needs." : "");
      }
      shown.forEach(function (m) {
        const acts = [];
        if (me.user.role === "ngo" && m.status === "proposed" && me.ngo && m.ngo_id === me.ngo.id) {
          const acc = h("button", { class: "btn btn-primary btn-sm", type: "button", text: "Accept donation" });
          acc.addEventListener("click", action(acc, function () { return API.post("/api/matches/" + m.id + "/accept"); }, "Donation accepted. A pickup task was created.", load));
          const rej = h("button", { class: "btn btn-secondary btn-sm", type: "button", text: "Decline" });
          rej.addEventListener("click", function () {
            const reason = window.prompt("Reason for declining (optional):", "") ;
            if (reason === null) return;
            action(rej, function () { return API.post("/api/matches/" + m.id + "/reject", { reason: reason || null }); }, "Offer declined.", load)();
          });
          acts.push(acc, rej);
        }
        list.appendChild(matchCard(m, w, { actions: acts }));
      });

      if ((isOwner || isAdmin) && matches.some(function (m) { return m.status === "rejected" || m.status === "superseded"; })) {
        const hist = h("details", { style: { marginTop: "12px" } }, h("summary", { text: "Match history" }));
        const tbl = h("table", {}, h("thead", {}, h("tr", {}, ["Created", "NGO", "Rank", "Score", "Distance", "Status"].map(function (t) { return h("th", { text: t }); }))));
        const tb = h("tbody");
        matches.forEach(function (m) {
          tb.appendChild(h("tr", {}, h("td", { text: FR.dateTime(m.created_at) }), h("td", { text: m.ngo_name }), h("td", { text: m.rank }),
            h("td", { class: "num", text: FR.num(m.score) }), h("td", { class: "num", text: FR.km(m.distance_km) }), h("td", {}, FR.badge(m.status))));
        });
        tbl.appendChild(tb);
        hist.appendChild(h("div", { class: "table-wrap", style: { marginTop: "8px" } }, tbl));
        recPanel.appendChild(hist);
      }
    }
    await load();
  }

  window.Dash = { donationCard: donationCard, matchCard: matchCard, pager: pager, stat: stat, action: action,
    urgentBadge: urgentBadge, SAFETY_NOTE: SAFETY_NOTE };

  if (document.body.dataset.page === "match-details") {
    initMatchDetails().catch(function (e) { FR.errorBox(FR.$("#content"), e); });
  }
})();
