/* Score-breakdown rendering shared by the landing page and dashboards.
 * Scores shown in dashboards always come from the server's matching engine;
 * the landing-page calculator evaluates the same formulas with the weights
 * fetched from /api/matches/weights, as a clearly labelled worked example. */
(function () {
  "use strict";
  const h = function () { return FR.h.apply(null, arguments); };

  const COMPONENTS = [
    { key: "freshness", cls: "f", label: "Freshness", symbol: "F" },
    { key: "proximity", cls: "g", label: "Proximity", symbol: "G" },
    { key: "capacity_fit", cls: "c", label: "Capacity fit", symbol: "C" },
    { key: "demand_fit", cls: "q", label: "Demand fit", symbol: "Q" },
    { key: "priority", cls: "p", label: "Priority", symbol: "P" },
  ];

  let weightsPromise = null;
  function weights() {
    if (!weightsPromise) weightsPromise = API.get("/api/matches/weights").then(function (r) { return r.weights; });
    return weightsPromise;
  }

  /** Stacked bar: each segment = w_k * component_k, so the bar length equals S_ij (out of 1). */
  function scoreBar(values, w) {
    const bar = h("div", { class: "score-bar", role: "img",
      "aria-label": "Score " + FR.num(values.score) + " made of " + COMPONENTS.map(function (c) {
        return c.label + " " + FR.num(values[c.key], 2);
      }).join(", ") });
    COMPONENTS.forEach(function (c) {
      const contrib = w[c.key] * (values[c.key] || 0);
      bar.appendChild(h("span", { class: c.cls, title: c.label + ": " + FR.num(values[c.key], 3) + " x " + w[c.key] + " = " + FR.num(contrib, 3),
        style: { width: (contrib * 100).toFixed(2) + "%" } }));
    });
    return bar;
  }

  function scoreLegend(values, w) {
    const box = h("div", { class: "score-legend" });
    COMPONENTS.forEach(function (c) {
      box.appendChild(h("div", { class: c.cls }, h("i"), c.label,
        h("b", { text: FR.num(values[c.key], 3) }),
        h("span", { class: "small", text: "x " + w[c.key] + " = " + FR.num(w[c.key] * (values[c.key] || 0), 3) })));
    });
    return box;
  }

  /* Formulas (identical to backend/app/matching.py) */
  const F = function (t) { t = Math.max(0, t); return 1 - Math.min(t, 24) / 24; };
  const G = function (d) { return d < 0 ? 0 : Math.exp(-d / 5); };
  const R = function (a, b) { return a > 0 && b > 0 ? Math.min(a, b) / Math.max(a, b) : 0; };

  async function initCalculator(root) {
    let w;
    try { w = await weights(); } catch (e) { FR.errorBox(root, e); return; }
    const inputs = {
      t: { label: "Usable life left", min: 0.5, max: 48, step: 0.5, value: 4, unit: " h" },
      d: { label: "Distance to NGO", min: 0, max: 25, step: 0.1, value: 2.4, unit: " km" },
      q: { label: "Donation size", min: 1, max: 100, step: 1, value: 18, unit: " kg" },
      c: { label: "NGO capacity", min: 0, max: 200, step: 1, value: 40, unit: " kg" },
      dm: { label: "NGO unmet demand", min: 0, max: 200, step: 1, value: 25, unit: " kg" },
      p: { label: "NGO priority", min: 0, max: 1, step: 0.05, value: 0.8, unit: "" },
    };
    const scoreEl = h("div", { class: "score-big", "aria-live": "polite" });
    const barSlot = h("div");
    const legendSlot = h("div");
    const controls = h("div", { class: "controls" });
    Object.keys(inputs).forEach(function (k) {
      const cfg = inputs[k];
      const out = h("output", { text: cfg.value + cfg.unit });
      const range = h("input", { type: "range", min: cfg.min, max: cfg.max, step: cfg.step, value: cfg.value,
        "aria-label": cfg.label,
        oninput: function () { cfg.value = Number(range.value); out.textContent = cfg.value + cfg.unit; render(); } });
      controls.appendChild(h("label", {}, h("span", { text: cfg.label }), range, out));
    });
    function render() {
      const v = {
        freshness: F(inputs.t.value), proximity: G(inputs.d.value), capacity_fit: R(inputs.q.value, inputs.c.value),
        demand_fit: R(inputs.q.value, inputs.dm.value), priority: inputs.p.value,
      };
      v.score = COMPONENTS.reduce(function (s, c) { return s + w[c.key] * v[c.key]; }, 0);
      scoreEl.textContent = v.score.toFixed(3);
      FR.clear(barSlot).appendChild(scoreBar(v, w));
      FR.clear(legendSlot).appendChild(scoreLegend(v, w));
    }
    FR.clear(root).append(
      h("div", { class: "row between" }, h("strong", { text: "Try the scoring formula" }), h("span", { class: "small muted", text: "Worked example" })),
      h("div", { class: "row", style: { alignItems: "baseline", marginTop: "8px" } }, scoreEl, h("span", { class: "muted", text: "match score S out of 1" })),
      controls, barSlot, legendSlot,
      h("p", { class: "small muted", style: { marginTop: "12px", marginBottom: "0" } },
        "Real recommendations are computed on the server from live NGO capacity, demand and location."));
    render();
  }

  window.Scoring = { COMPONENTS: COMPONENTS, weights: weights, scoreBar: scoreBar, scoreLegend: scoreLegend, initCalculator: initCalculator };
})();
