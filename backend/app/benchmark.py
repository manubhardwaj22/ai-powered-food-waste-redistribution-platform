"""Reproducible synthetic benchmark comparing four allocation methods.

IMPORTANT: this is a SYNTHETIC experiment. No real donations, NGOs or
deployment data are involved. It reconstructs the benchmark described in the
project report (seed 7, 900 offers, 90 NGOs, five categories, ~16,915.6 kg
offered, ~15,191.2 kg aggregate capacity, ~12,299.1 kg stated demand) and
compares:

    1. Random eligible assignment
    2. Nearest eligible NGO
    3. FIFO demand/distance baseline
    4. Proposed weighted scoring (the same scoring functions as the live app)

Benchmark geometry: donors and NGOs are placed on a 30 km x 30 km planar city
grid and distance is Euclidean in km. This differs deliberately from the live
application, which uses real latitude/longitude and the Haversine formula.

Shared rules for all four methods (so the comparison is fair):
  * a pair (i, j) is feasible when NGO j accepts offer i's category, the
    distance is within MAX_RADIUS_KM, and j has remaining capacity > 0 AND
    remaining demand > 0;
  * each offer is assigned to at most one NGO, and the assigned quantity is
    a_ij = min(q_i, remaining capacity_j, remaining demand_j) (partial
    fulfilment is allowed, which is what the full-match-rate metric measures);
  * each offer's remaining usable life T_i is fixed at posting time.

Metrics:
  * quantity fulfilment  = sum(assigned) / sum(offered)
  * waste ratio          = 1 - quantity fulfilment (offered quantity left unassigned)
  * urgent-rescue rate   = share of offers with T_i <= 6 h that received any assignment
  * average distance     = mean distance over assigned offers (km)
  * full-match rate      = share of all offers whose full quantity was assigned
"""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from . import matching

SEED = 7
N_OFFERS = 900
N_NGOS = 90
GRID_KM = 30.0
MAX_RADIUS_KM = 15.0
URGENT_HOURS = 6.0

TARGET_OFFERED_KG = 16915.6
TARGET_CAPACITY_KG = 15191.2
TARGET_DEMAND_KG = 12299.1

CATEGORIES = ["prepared_meals", "bakery", "fruits_vegetables", "dairy", "packaged"]
CATEGORY_SHARE = [0.30, 0.20, 0.25, 0.10, 0.15]
# Remaining usable life (hours) at posting, uniform per category.
LIFE_RANGE = {
    "prepared_meals": (1.0, 12.0),
    "bakery": (4.0, 36.0),
    "fruits_vegetables": (8.0, 72.0),
    "dairy": (4.0, 48.0),
    "packaged": (24.0, 168.0),
}

REPORTED_PROPOSED = {
    "quantity_fulfillment_pct": 64.17,
    "waste_ratio_pct": 35.83,
    "avg_distance_km": 3.35,
    "urgent_rescue_pct": 94.65,
    "full_match_pct": 59.89,
}

METHOD_LABELS = {
    "random": "Random eligible",
    "nearest": "Nearest eligible",
    "fifo": "FIFO demand/distance",
    "proposed": "Proposed weighted",
}


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
def _scale_to(values: np.ndarray, target: float) -> np.ndarray:
    """Rescale positive draws so they sum to `target`, rounded to 0.1 kg.

    The rounding remainder is put on the largest element so the total matches
    the target to 0.1 kg (calibration to the report's published totals).
    """
    scaled = np.maximum(np.round(values * (target / values.sum()), 1), 0.1)
    scaled[np.argmax(scaled)] += round(target - scaled.sum(), 1)
    return np.round(scaled, 1)


def generate_dataset(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    # NGOs -----------------------------------------------------------------
    ngo_xy = rng.uniform(0, GRID_KM, size=(N_NGOS, 2))
    accepts = rng.random((N_NGOS, len(CATEGORIES))) < 0.7
    for j in range(N_NGOS):  # every NGO accepts at least one category
        if not accepts[j].any():
            accepts[j, rng.integers(len(CATEGORIES))] = True
    capacity = _scale_to(rng.gamma(2.0, 1.0, N_NGOS), TARGET_CAPACITY_KG)
    # Unmet demand is correlated with capacity (larger food banks serve more people).
    demand = _scale_to(capacity * rng.uniform(0.55, 1.0, N_NGOS), TARGET_DEMAND_KG)
    priority = np.round(rng.uniform(0.2, 1.0, N_NGOS), 3)
    ngos = pd.DataFrame({
        "ngo_id": np.arange(N_NGOS),
        "x": ngo_xy[:, 0], "y": ngo_xy[:, 1],
        "capacity_kg": capacity, "demand_kg": demand, "priority": priority,
        "categories": [[c for c, ok in zip(CATEGORIES, row) if ok] for row in accepts],
    })

    # Offers ---------------------------------------------------------------
    cats = rng.choice(CATEGORIES, size=N_OFFERS, p=CATEGORY_SHARE)
    qty = _scale_to(rng.lognormal(mean=2.6, sigma=0.75, size=N_OFFERS), TARGET_OFFERED_KG)
    life = np.array([rng.uniform(*LIFE_RANGE[c]) for c in cats])
    offer_xy = rng.uniform(0, GRID_KM, size=(N_OFFERS, 2))
    offers = pd.DataFrame({
        "offer_id": np.arange(N_OFFERS),  # also the arrival (posting) order
        "category": cats, "quantity_kg": qty, "remaining_hours": np.round(life, 2),
        "x": offer_xy[:, 0], "y": offer_xy[:, 1],
    })
    return offers, ngos


def dataset_summary(offers: pd.DataFrame, ngos: pd.DataFrame) -> dict:
    return {
        "seed": SEED,
        "offers": len(offers),
        "ngos": len(ngos),
        "categories": len(CATEGORIES),
        "offered_kg": round(float(offers.quantity_kg.sum()), 1),
        "capacity_kg": round(float(ngos.capacity_kg.sum()), 1),
        "demand_kg": round(float(ngos.demand_kg.sum()), 1),
        "urgent_offers": int((offers.remaining_hours <= URGENT_HOURS).sum()),
        "targets": {"offered_kg": TARGET_OFFERED_KG, "capacity_kg": TARGET_CAPACITY_KG,
                    "demand_kg": TARGET_DEMAND_KG},
        "category_counts": offers.category.value_counts().to_dict(),
    }


# ---------------------------------------------------------------------------
# Allocation methods
# ---------------------------------------------------------------------------
@dataclass
class State:
    offers: pd.DataFrame
    ngos: pd.DataFrame

    def __post_init__(self):
        self.q = self.offers.quantity_kg.to_numpy(float)
        self.T = self.offers.remaining_hours.to_numpy(float)
        self.cat = self.offers.category.to_numpy()
        self.cap = self.ngos.capacity_kg.to_numpy(float).copy()
        self.dem = self.ngos.demand_kg.to_numpy(float).copy()
        self.prio = self.ngos.priority.to_numpy(float)
        ox = self.offers[["x", "y"]].to_numpy()
        nx = self.ngos[["x", "y"]].to_numpy()
        self.dist = np.sqrt(((ox[:, None, :] - nx[None, :, :]) ** 2).sum(axis=2))
        cat_ok = np.array([[c in set(cs) for cs in self.ngos.categories] for c in self.cat])
        self.static_ok = cat_ok & (self.dist <= MAX_RADIUS_KM)
        self.assigned = np.zeros(len(self.q))
        self.assigned_dist = np.full(len(self.q), np.nan)

    def eligible(self, i: int) -> np.ndarray:
        return np.flatnonzero(self.static_ok[i] & (self.cap > 1e-9) & (self.dem > 1e-9))

    def assign(self, i: int, j: int) -> None:
        a = min(self.q[i], self.cap[j], self.dem[j])
        self.cap[j] -= a
        self.dem[j] -= a
        self.assigned[i] = a
        self.assigned_dist[i] = self.dist[i, j]


def run_random(state: State, rng: np.random.Generator) -> None:
    for i in range(len(state.q)):
        e = state.eligible(i)
        if e.size:
            state.assign(i, int(rng.choice(e)))


def run_nearest(state: State, _rng) -> None:
    for i in range(len(state.q)):
        e = state.eligible(i)
        if e.size:
            state.assign(i, int(e[np.argmin(state.dist[i, e])]))


def run_fifo(state: State, _rng) -> None:
    """Offers served first-in-first-out; each goes to the eligible NGO with the
    highest remaining demand per km of travel, d_j / (1 + D_ij).

    NOTE: reconstructed from the prompt's description ("demand/distance
    heuristic"); verify against the report's exact definition.
    """
    for i in range(len(state.q)):
        e = state.eligible(i)
        if e.size:
            state.assign(i, int(e[np.argmax(state.dem[e] / (1.0 + state.dist[i, e]))]))


def _score(state: State, i: int, j: int) -> float:
    return matching.weighted_score(
        matching.freshness_urgency(state.T[i]),
        matching.geographic_proximity(state.dist[i, j]),
        matching.capacity_fit(state.q[i], state.cap[j]),
        matching.demand_fit(state.q[i], state.dem[j]),
        matching.recipient_priority(state.prio[j]),
    )


def run_proposed(state: State, _rng) -> None:
    """Global greedy on S_ij with lazy re-scoring.

    All feasible pairs are placed in a max-heap by S_ij. When a pair is popped,
    its score is recomputed with the NGO's *current* residual capacity/demand;
    if the score dropped, the pair is pushed back. Because F_i differs across
    offers, urgent offers win ties for the same nearby NGO - which is how the
    freshness term acts in a batch setting.
    """
    heap: list[tuple[float, int, int]] = []
    for i in range(len(state.q)):
        for j in state.eligible(i):
            heapq.heappush(heap, (-_score(state, i, int(j)), i, int(j)))
    done = np.zeros(len(state.q), dtype=bool)
    while heap:
        neg, i, j = heapq.heappop(heap)
        if done[i] or state.cap[j] <= 1e-9 or state.dem[j] <= 1e-9:
            continue
        current = _score(state, i, j)
        if current < -neg - 1e-12:
            heapq.heappush(heap, (-current, i, j))
            continue
        state.assign(i, j)
        done[i] = True


METHODS: dict[str, Callable] = {
    "random": run_random,
    "nearest": run_nearest,
    "fifo": run_fifo,
    "proposed": run_proposed,
}


def evaluate(state: State) -> dict:
    offered = state.q.sum()
    got = state.assigned
    urgent = state.T <= URGENT_HOURS
    matched = got > 0
    return {
        "quantity_fulfillment_pct": round(float(100 * got.sum() / offered), 2),
        "waste_ratio_pct": round(float(100 * (1 - got.sum() / offered)), 2),
        "urgent_rescue_pct": round(float(100 * matched[urgent].mean()), 2) if urgent.any() else None,
        "avg_distance_km": round(float(np.nanmean(state.assigned_dist[matched])), 2) if matched.any() else None,
        "full_match_pct": round(float(100 * np.mean(got >= state.q - 1e-9)), 2),
        "assigned_kg": round(float(got.sum()), 1),
        "matched_offers": int(matched.sum()),
    }


def run_benchmark(seed: int = SEED) -> dict:
    offers, ngos = generate_dataset(seed)
    results = {}
    for name, fn in METHODS.items():
        state = State(offers, ngos)
        fn(state, np.random.default_rng(seed))
        results[name] = evaluate(state)
    return {
        "synthetic": True,
        "note": "Synthetic benchmark only - not a real-world deployment evaluation.",
        "dataset": dataset_summary(offers, ngos),
        "settings": {"grid_km": GRID_KM, "max_radius_km": MAX_RADIUS_KM, "urgent_hours": URGENT_HOURS,
                     "weights": matching.WEIGHTS, "distance": "Euclidean on a planar km grid"},
        "methods": {k: {"label": METHOD_LABELS[k], **v} for k, v in results.items()},
        "reported_proposed_reference": REPORTED_PROPOSED,
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated categorical slots 1-4
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def make_charts(res: dict, out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    methods = list(res["methods"])
    labels = [res["methods"][m]["label"] for m in methods]
    paths: list[Path] = []

    # 1) Percentage metrics, grouped by metric, one bar per method.
    metrics = [("quantity_fulfillment_pct", "Quantity\nfulfilment"), ("waste_ratio_pct", "Waste\nratio"),
               ("urgent_rescue_pct", "Urgent\nrescue"), ("full_match_pct", "Full\nmatch")]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    width = 0.2
    x = np.arange(len(metrics))
    for k, m in enumerate(methods):
        vals = [res["methods"][m][key] or 0 for key, _ in metrics]
        bars = ax.bar(x + (k - 1.5) * width, vals, width * 0.92, color=SERIES[k], label=labels[k])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}", ha="center", va="bottom",
                    fontsize=7.5, color=INK2)
    ax.set_xticks(x, [lbl for _, lbl in metrics], color=INK)
    ax.set_ylabel("Percent (%)", color=INK2)
    ax.set_ylim(0, 110)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.1), labelcolor=INK)
    ax.set_title("Synthetic benchmark (seed 7): reproduced results by method", color=INK, pad=34, loc="left")
    fig.tight_layout()
    p = out_dir / "benchmark_percent_metrics.png"
    fig.savefig(p, facecolor=SURFACE)
    plt.close(fig)
    paths.append(p)

    # 2) Average match distance.
    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    vals = [res["methods"][m]["avg_distance_km"] or 0 for m in methods]
    bars = ax.bar(labels, vals, 0.55, color=SERIES[: len(methods)])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.1, f"{v:.2f} km", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.set_ylabel("Average match distance (km)", color=INK2)
    ax.set_title("Average donor-to-NGO distance (lower is better)", color=INK, loc="left")
    fig.tight_layout()
    p = out_dir / "benchmark_avg_distance.png"
    fig.savefig(p, facecolor=SURFACE)
    plt.close(fig)
    paths.append(p)

    # 3) Reproduced proposed method vs the values published in the report.
    keys = [("quantity_fulfillment_pct", "Fulfilment %"), ("waste_ratio_pct", "Waste %"),
            ("urgent_rescue_pct", "Urgent rescue %"), ("full_match_pct", "Full match %")]
    fig, ax = plt.subplots(figsize=(8.5, 4.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    x = np.arange(len(keys))
    rep = [res["reported_proposed_reference"][k] for k, _ in keys]
    ours = [res["methods"]["proposed"][k] or 0 for k, _ in keys]
    b1 = ax.bar(x - 0.18, ours, 0.34, color=SERIES[0], label="Reproduced here (calculated)")
    b2 = ax.bar(x + 0.18, rep, 0.34, color="#9b9a95", label="Published in report (reference, not recalculated)")
    for bars, vals in ((b1, ours), (b2, rep)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(x, [lbl for _, lbl in keys], color=INK)
    ax.set_ylim(0, 110)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=1, labelcolor=INK, fontsize=8.5)
    ax.set_title("Proposed method: reproduction vs. report", color=INK, loc="left", pad=40)
    fig.tight_layout()
    p = out_dir / "benchmark_vs_report.png"
    fig.savefig(p, facecolor=SURFACE)
    plt.close(fig)
    paths.append(p)
    return paths


def run_and_save(results_path: Path, charts_dir: Path, seed: int = SEED) -> dict:
    res = run_benchmark(seed)
    res["charts"] = [f"/charts/{p.name}" for p in make_charts(res, charts_dir)]
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return res


if __name__ == "__main__":  # pragma: no cover
    from .config import CHARTS_DIR, DATA_DIR

    out = run_and_save(DATA_DIR / "benchmark_results.json", CHARTS_DIR)
    print(json.dumps({k: v for k, v in out.items() if k != "charts"}, indent=2, default=str))
