/* About page: public header and the live weight table from the API. */
(function () {
  "use strict";
  const h = FR.h;
  FR.initPublicHeader();
  const box = FR.$("#weights");
  Scoring.weights().then(function (w) {
    FR.clear(box);
    Scoring.COMPONENTS.forEach(function (c) {
      box.appendChild(h("div", { class: "hbar" }, h("span", { text: c.label + " (w" + c.symbol + ")" }),
        h("div", { class: "track" }, h("div", { class: "fill", style: { width: (w[c.key] * 100).toFixed(2) + "%" } })),
        h("span", { class: "v", text: w[c.key].toFixed(4) })));
    });
  }).catch(function (e) { FR.errorBox(box, e); });
})();
