# Matching Algorithm and Benchmark

Implementation: [`backend/app/matching.py`](../backend/app/matching.py) (live engine) and
[`backend/app/benchmark.py`](../backend/app/benchmark.py) (synthetic evaluation).

## 1. What kind of "AI" this is

The decision engine is an **explainable, AI-assisted weighted scoring model** (a
multi-criteria decision method). It is **not** a trained machine-learning model: there is no
training data, no learned parameters and no neural network. Five interpretable factors are
combined with five fixed weights taken from the project report, so every recommendation can
be reproduced by hand and explained in plain language.

## 2. Pipeline for one donation

1. **Validate the donation** — status must be `posted`/`matched`, quantity > 0, valid
   coordinates, not expired, pickup window still open and starting before the food expires.
2. **Feasibility filter** (hard constraints, applied before any scoring). An NGO is rejected if:
   - it does not accept the food category;
   - its available capacity is 0 or smaller than the donation (whole donations are accepted);
   - its unmet demand is 0;
   - it is outside `MAX_MATCH_DISTANCE_KM` (default 25 km) or has invalid coordinates;
   - its account is inactive, or it already declined this donation.
   - Optional (`REQUIRE_VOLUNTEER_FEASIBILITY=true`): at least one available volunteer must be
     within their own travel limit of the pickup point with enough vehicle capacity.
3. **Score** each feasible pair with the five components.
4. **Weighted score** `S_ij`.
5. **Rank** by score (ties: shorter distance, then NGO id).
6. **Explain** — a sentence generated from the computed values, plus the largest weighted
   contribution.
7. **Persist** the top `MAX_RECOMMENDATIONS` (default 5) as `match_recommendations` rows.
8. **Accept** — the recommended NGO accepts; capacity and demand are reserved atomically.
9. **History** — superseded / rejected / accepted rows and audit-log entries are kept.

## 3. Formulas

| Component | Formula | Notes |
|---|---|---|
| Freshness urgency | `F_i = 1 − min(T_i, 24) / 24` | `T_i` = remaining usable life (h). Negative/invalid → treated as 0 h. |
| Geographic proximity | `G_ij = exp(−D_ij / 5)` | `D_ij` in km. Live app: Haversine on lat/lon. |
| Capacity fit | `C_ij = min(q_i, c_j) / max(q_i, c_j)` | 0 if either side ≤ 0 (no division by zero). |
| Demand fit | `Q_ij = min(q_i, d_j) / max(q_i, d_j)` | 0 if either side ≤ 0. |
| Recipient priority | `P_j ∈ [0, 1]` | Clamped to the range. |

`S_ij = w_F·F_i + w_G·G_ij + w_C·C_ij + w_Q·Q_ij + w_P·P_j`

| Weight | Value |
|---|---|
| w_F (freshness) | 0.0714 |
| w_G (proximity) | 0.7280 |
| w_C (capacity) | 0.0654 |
| w_Q (demand) | 0.0464 |
| w_P (priority) | 0.0888 |
| **Sum** | **1.0000** |

### Worked example
Donation: 18 kg, 4 h left. NGO: 2.4 km away, capacity 40 kg, demand 25 kg, priority 0.8.

- F = 1 − 4/24 = 0.833 → 0.0714 × 0.833 = 0.060
- G = e^(−2.4/5) = 0.619 → 0.728 × 0.619 = 0.450
- C = 18/40 = 0.450 → 0.0654 × 0.450 = 0.029
- Q = 18/25 = 0.720 → 0.0464 × 0.720 = 0.033
- P = 0.8 → 0.0888 × 0.8 = 0.071
- **S = 0.644**

Because w_G = 0.728, distance dominates the ranking; freshness matters mainly when several
offers compete for the same NGO (see the benchmark's global greedy below).

## 4. Distance handling: live app vs benchmark

| | Live application | Synthetic benchmark |
|---|---|---|
| Coordinates | Real latitude/longitude | Points on a 30 km × 30 km plane |
| Distance | Haversine great-circle (km) | Euclidean (km) |
| Routing | None (straight line). Volunteers get an OpenStreetMap link for directions. | None |

## 5. Synthetic benchmark (`python run.py benchmark`)

> **Synthetic only.** No real donors, NGOs or deployments are involved.

### Dataset (seed 7)
The PDF report was not available while building, so the generator was reconstructed from the
characteristics listed in the brief and **calibrated to the published totals**:

| Characteristic | Report | Reproduced |
|---|---:|---:|
| Donation offers | 900 | 900 |
| NGO nodes | 90 | 90 |
| Food categories | 5 | 5 |
| Offered food | ≈16,915.6 kg | 16,915.6 kg |
| Aggregate NGO capacity | ≈15,191.2 kg | 15,191.2 kg |
| Stated demand | ≈12,299.1 kg | 12,299.1 kg |
| Urgent offers (≤ 6 h) | not stated here | 151 |

Generator assumptions (ours, documented in code): category shares 30/20/25/10/15 %; quantities
log-normal and rescaled to the total; usable life uniform per category (prepared meals 1–12 h,
bakery 4–36 h, produce 8–72 h, dairy 4–48 h, packaged 24–168 h); NGOs accept each category with
probability 0.7; capacity gamma-distributed; demand correlated with capacity (55–100 %);
priority uniform 0.2–1.0; feasibility radius 15 km.

### Methods (identical feasibility and accounting)
1. **Random eligible** — offers in arrival order; a uniformly random feasible NGO.
2. **Nearest eligible** — offers in arrival order; the closest feasible NGO.
3. **FIFO demand/distance** — offers in arrival order; NGO maximising `d_j / (1 + D_ij)`.
   *Reconstructed from the brief's description; check it against the report's exact rule.*
4. **Proposed weighted** — global greedy on `S_ij` with lazy re-scoring as residual capacity and
   demand shrink. Urgent offers win contested nearby NGOs through the F term.

Assigned quantity is `min(q_i, remaining capacity, remaining demand)`; partial fulfilment is
allowed, which is what the full-match rate measures.

### Metrics
- **Quantity fulfilment** = assigned kg / offered kg
- **Waste ratio** = 1 − fulfilment (offered quantity left unassigned)
- **Urgent-rescue rate** = share of offers with T ≤ 6 h that received any assignment
- **Average match distance** = mean distance of assigned offers
- **Full-match rate** = share of offers whose entire quantity was assigned

### Results (calculated by this implementation, seed 7)

| Method | Fulfilment % | Waste % | Urgent rescue % | Avg distance km | Full match % |
|---|---:|---:|---:|---:|---:|
| Random eligible | 71.66 | 28.34 | 78.81 | 9.28 | 70.22 |
| Nearest eligible | 71.53 | 28.47 | 77.48 | 3.78 | 68.56 |
| FIFO demand/distance | 72.04 | 27.96 | 80.79 | 4.19 | 70.33 |
| **Proposed weighted** | **70.83** | **29.17** | **94.70** | **2.40** | **69.22** |
| *Proposed — published in report (reference only)* | *64.17* | *35.83* | *94.65* | *3.35* | *59.89* |

Charts: [`docs/charts/benchmark_percent_metrics.png`](charts/benchmark_percent_metrics.png),
[`benchmark_avg_distance.png`](charts/benchmark_avg_distance.png),
[`benchmark_vs_report.png`](charts/benchmark_vs_report.png).

### How the reproduction differs from the report, and why
- **Urgent-rescue rate matches closely** (94.70 % vs 94.65 %) — the proposed method's main
  advantage over the baselines (+14 to +17 points) is reproduced.
- **Shorter distance** (2.40 km vs 3.35 km) and the proposed method is still the best of the four.
- **Higher fulfilment and full-match rates** (70.8 % vs 64.2 %; 69.2 % vs 59.9 %). The most
  likely cause is our demand generator: demand is correlated with capacity, so most NGOs'
  binding constraint is demand and almost all of the 12,299 kg demand can be filled. The report's
  dataset probably has more capacity/demand/category mismatch or a smaller radius.
- In our run the proposed method trades ~1 point of fulfilment versus the baselines for much
  better urgency and distance; whether that matches the report's baseline numbers cannot be
  checked without the report's baseline table.

These figures are recalculated every time the benchmark runs; nothing is hard-coded. The
reference row is labelled as such in the table, the admin dashboard and the comparison chart.
