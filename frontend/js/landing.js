/* Landing page: public header behaviour and the interactive scoring example. */
(function () {
  "use strict";
  FR.initPublicHeader();
  const calc = FR.$("#calculator");
  if (calc) Scoring.initCalculator(calc);
})();
