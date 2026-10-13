# Viva Preparation: Questions and Answers

**Project:** AI-Powered Food Waste Donation & Redistribution Platform (FoodRescue AI)
**Team 56, Bennett University** — Manu Bhardwaj (S24BCAU0034), Amul Sharma (S24BCAU0013)

---

## Objective and problem

**1. What is the objective of the project?**
To reduce edible food waste by connecting donors (restaurants, hotels, bakeries, caterers,
retailers) with NGOs and food banks that need food, and by coordinating volunteers who deliver
it — quickly enough that perishable food is still usable.

**2. What problem does it solve?**
Surplus food is often wasted because the right recipient isn't found in time. Three things go
wrong: time (perishables expire within hours), mismatch (an NGO may not accept that category, may
be full, or may not need it) and logistics (no one available to carry it). The platform handles
all three: urgency-aware ranking, feasibility checks on category/capacity/demand, and volunteer
task coordination.

## Architecture and technology

**3. Describe the system architecture.**
Three layers: a vanilla HTML/CSS/JavaScript frontend; a FastAPI REST backend split into routes,
services (state machine), the matching engine, notifications, analytics and benchmark modules; and
a SQLite database accessed through SQLAlchemy. FastAPI also serves the static frontend, so the
browser talks to one origin. See `docs/architecture.md`.

**4. What are the user roles?**
- **Donor** — posts food, sees ranked NGOs with explanations, tracks status, can cancel.
- **NGO / food bank** — sets capacity, unmet demand, priority and accepted categories; accepts or
  declines offers; tracks deliveries and impact.
- **Volunteer** — sets location, vehicle capacity, travel limit and availability; accepts tasks;
  confirms pickup and delivery.
- **Administrator** — monitors everything, manages users and reports, views audit logs and runs
  the benchmark. Admins are created from the command line only.

**5. Why FastAPI?**
Fast to develop, automatic request validation with Pydantic, automatic interactive API docs
(`/docs`), dependency injection that makes role checks reusable, and good performance.

**6. Why SQLite?**
Zero setup (a single file), included with Python, transactional (ACID) and sufficient for a
prototype. SQLAlchemy keeps the code portable to PostgreSQL later by changing `DATABASE_URL`.

**7. Why vanilla JavaScript and no framework?**
The brief required it, and it keeps the project easy to read: each page has its own script, with
shared helpers in `common.js`, `api.js`, `scoring.js` and `dashboard.js`.

## The matching algorithm

**8. What does the matching algorithm do?**
For each donation it (1) validates the offer, (2) removes infeasible NGOs, (3) computes five scores
for each remaining NGO, (4) combines them with fixed weights into one score, (5) ranks NGOs, and
(6) explains each recommendation in plain language. The top five are stored and shown.

**9. Explain the five scoring components.**
- **Freshness urgency** `F = 1 − min(T,24)/24`: food with less life left gets a higher value
  (2 h left → 0.92; 24 h or more → 0).
- **Geographic proximity** `G = exp(−D/5)`: 1 at 0 km, 0.37 at 5 km, 0.05 at 15 km.
- **Capacity fit** `C = min(q,c)/max(q,c)`: 1 when donation size equals available capacity.
- **Demand fit** `Q = min(q,d)/max(q,d)`: 1 when donation size equals unmet demand.
- **Recipient priority** `P` in [0,1]: higher for vulnerable groups.

**10. What are the weights and why does proximity dominate?**
wF 0.0714, wG 0.7280, wC 0.0654, wQ 0.0464, wP 0.0888 (sum 1). They come from the report.
Proximity has the largest weight because travel time is the main reason perishable food fails to
arrive; the other factors refine the choice among nearby NGOs.

**11. What is the difference between feasibility and scoring?**
Feasibility rules are hard constraints — a pair that breaks one (wrong category, too little
capacity, zero demand, too far, expired) is never recommended, regardless of score. Scoring only
ranks pairs that already passed.

**12. Why is it called "AI-assisted" and not machine learning?**
It automates a decision that normally needs human judgement by combining several criteria — a
classical decision-support technique. But nothing is learned from data: there is no training set,
no model fitting, and the weights are fixed. Calling it a trained ML model would be inaccurate.
The advantage is transparency: every score can be recomputed by hand and explained.

**13. How do you prevent the same donation from being given to two NGOs?**
Acceptance uses conditional (compare-and-set) SQL updates in one transaction: the donation moves
to `accepted` only if it is still `posted`/`matched`, and capacity is reduced only if enough
remains. If either update changes zero rows, everything rolls back and the API returns 409. A test
runs three simultaneous acceptances and checks that exactly one succeeds.

**14. What happens when an NGO declines?**
The recommendation is marked rejected and the donor is notified. If no candidates remain, matching
re-runs and permanently excludes the NGO that declined.

## Workflow (donor to NGO, end to end)

**15. Walk through the full workflow.**
1. Donor posts food (name, category, quantity + kg, preparation details, remaining life, pickup
   location and window, optional photo). Status **Posted**.
2. The engine runs immediately; if feasible NGOs exist, the top five are stored with scores and
   explanations. Status **Matched**. Donor and NGOs are notified.
3. An NGO reviews the offer and score breakdown and accepts. Capacity and demand are reserved;
   a delivery task is created; nearby eligible volunteers are notified. Status **Accepted**.
4. A volunteer within range with enough vehicle capacity accepts the task and sees contact details.
5. Volunteer confirms pickup (**Picked up**) then delivery (**Delivered**); timestamps are stored.
6. At any time before pickup the donor can cancel; if the food's usable life runs out it becomes
   **Expired**. Both release reserved capacity. Every step is in the audit log.

**16. Does the platform guarantee food safety?**
No. The interface states clearly that matching does not certify safety; donors and NGOs must
inspect condition, temperature and packaging before handover and distribution.

## Dataset and evaluation

**17. How was the synthetic dataset generated?**
`benchmark.py` uses NumPy with random seed 7 to create 900 offers and 90 NGOs on a 30 × 30 km grid,
across five categories, calibrated so totals match the report: 16,915.6 kg offered, 15,191.2 kg
capacity, 12,299.1 kg demand.

**18. Why use a fixed random seed?**
So the experiment is reproducible: the same seed always produces the same dataset and results,
which lets anyone verify the numbers. A test checks this.

**19. Which evaluation metrics are used?**
Quantity fulfilment (assigned ÷ offered), waste ratio (1 − fulfilment), urgent-rescue rate (share
of offers with ≤ 6 h left that got any assignment), average match distance, and full-match rate
(share of offers fully assigned).

**20. What baselines were compared?**
Random eligible NGO, nearest eligible NGO, and a FIFO baseline that serves offers in arrival order
and picks the NGO with the most remaining demand per km. All use the same feasibility rules.

**21. What were the results?**
Report (proposed method): 64.17 % fulfilment, 35.83 % waste, 3.35 km, 94.65 % urgent rescue,
59.89 % full match. Our reproduction: 70.83 %, 29.17 %, 2.40 km, 94.70 %, 69.22 %. The proposed
method gave by far the best urgent-rescue rate (≈95 % vs 77–81 % for baselines) and the shortest
distance, at a cost of about one point of fulfilment. Differences from the report come from our
reconstructed data generator (see `docs/algorithm.md`).

**22. Is this a real-world evaluation?**
No. It is a synthetic simulation. It shows how the algorithm behaves under controlled assumptions,
not how it performs with real donors and NGOs.

## Security and testing

**23. What security controls are implemented?**
bcrypt password hashing, JWT tokens signed with an environment secret, server-side role and
ownership checks on every endpoint, no admin self-registration, Pydantic input validation, login
throttling, CSP and other security headers, XSS-safe DOM rendering, validated image uploads,
contact details hidden until a volunteer accepts, and a full audit log.

**24. How was the system tested?**
69 automated pytest tests (formulas, edge cases, ranking, feasibility, auth, permissions,
validation, lifecycle, duplicate and concurrent acceptance, volunteer tasks, persistence,
benchmark metrics) on a separate test database, plus a browser run of every role's workflow.

**25. Give an example of an edge case you tested.**
Zero capacity or demand: the fit formulas return 0 instead of dividing by zero, and the
feasibility filter rejects the NGO. Invalid coordinates are rejected rather than crashing.

## Limitations and future work

**26. What are the current limitations?**
Synthetic evaluation only; straight-line distances, no road routing; weights are fixed rather than
tuned; in-app notifications only; whole-donation acceptance (no splitting across NGOs); SQLite
limits concurrent writers; no food-safety verification; tested on Linux, not Windows.

**27. What future enhancements would you add?**
Road-network travel times (e.g. OSRM), splitting large donations across NGOs, learning or tuning
weights from real outcome data, SMS/WhatsApp notifications, maps in the UI, PostgreSQL for
production, multilingual interface, and a pilot with real organisations.
