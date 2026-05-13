"""
optimizer_table_mode.py — ILP-based table-level seating assignment using PuLP.

Per-table model: students are assigned to TABLES (not individual seats). The
optimizer minimizes repeated tablemates against pair history. There's no
adjacency scoring, no seat_history tiebreaker — just "who sits at which
table". Much simpler and faster than the per-seat variant; appropriate for
teachers who don't care about specific seat positions.

Exposes the same SeatingResult shape as optimizer.py (per-seat) so the
caller's dispatch code is uniform. In per-table mode, each assignment's
seat_id is None — seats are ignored entirely.
"""

from dataclasses import dataclass
import pulp


@dataclass
class Table:
    id: int
    capacity: int


@dataclass
class Student:
    id: int
    name: str
    pinned_table_id: int | None = None


@dataclass
class SeatingResult:
    # (student_id, seat_id, table_id) for uniformity with optimizer.py.
    # In per-table mode seat_id is ALWAYS None — caller should not use it.
    assignments: list[tuple[int, int | None, int]]
    total_repeat_score: int
    status: str


# The smallest pair-history weight that earns a linearization variable.
# Pairs below this threshold still accumulate in the objective via the
# `total_repeat_score` sum, but aren't linearized as separate y-variables
# (pruning trick copied from the per-seat optimizer). In practice with
# only pair_history as the signal, we keep all non-zero pairs.
MIN_PAIR_WEIGHT = 1


def optimise_seating(
    students: list[Student],
    tables: list[Table],
    pair_history: dict[tuple[int, int], int],
    forbidden_pairs: list[tuple[int, int]] | None = None,
    tag_pair_costs: list[tuple[int, int, int]] | None = None,
    time_limit_seconds: int | None = 30,
) -> SeatingResult:
    """Solve the table assignment ILP.

    students: list of Student objects. pinned_table_id is honored.
    tables: list of Table objects. capacity is seat count.
    pair_history: {(student_a, student_b) sorted: count} — how many past
        rounds these two have shared a table. Dominant optimization signal.
    forbidden_pairs: list of (sid_a, sid_b) that must NOT share a table.
        Hard constraint.
    tag_pair_costs: list of (sid_a, sid_b, weight_delta) — soft costs
        injected by the tag system. Positive weights discourage sharing
        (distribute, keep_apart); negative weights encourage sharing
        (cluster). Same y-variable framework as pair_history; this is
        an additional cost source layered on top.
    time_limit_seconds: hard wall-clock cap on solver. Default 30s.

    Returns SeatingResult whose assignments list has seat_id=None on every
    entry.
    """
    forbidden_pairs = forbidden_pairs or []
    tag_pair_costs  = tag_pair_costs or []

    if not students:
        return SeatingResult(assignments=[], total_repeat_score=0, status="Optimal")

    total_capacity = sum(t.capacity for t in tables)
    if total_capacity < len(students):
        return SeatingResult(
            assignments=[], total_repeat_score=0,
            status=(f"Infeasible: only {total_capacity} seats across tables "
                    f"for {len(students)} students")
        )

    s_ids = [s.id for s in students]
    t_ids = [t.id for t in tables]
    t_cap = {t.id: t.capacity for t in tables}
    t_id_set = set(t_ids)

    # ── Validate pins ────────────────────────────────────────────────────────
    pin_table_counts: dict[int, int] = {}
    for s in students:
        if s.pinned_table_id is not None:
            if s.pinned_table_id not in t_id_set:
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status=(f"Infeasible: {s.name} is pinned to a table that "
                            "isn't in this round (maybe excluded?)"))
            pin_table_counts[s.pinned_table_id] = (
                pin_table_counts.get(s.pinned_table_id, 0) + 1)
            if pin_table_counts[s.pinned_table_id] > t_cap[s.pinned_table_id]:
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status=(f"Infeasible: too many students pinned to "
                            f"table {s.pinned_table_id}"))

    # ── Compute balanced per-table targets ───────────────────────────────────
    # Force-fill: instead of letting the optimizer freely distribute
    # students across tables (which would leave lonely students at
    # near-empty tables when roster < total capacity), we pre-compute
    # exact per-table counts and pass them as hard == constraints.
    # The optimizer then only decides WHICH students go where.
    from seating_distribution import compute_table_targets, InfeasibleDistribution
    try:
        targets = compute_table_targets(
            num_students=len(students),
            tables=[(t.id, t.capacity) for t in tables],
            pin_counts=pin_table_counts,
        )
    except InfeasibleDistribution as e:
        return SeatingResult(
            assignments=[], total_repeat_score=0,
            status=f"Infeasible: {e}")

    # ── Problem ──────────────────────────────────────────────────────────────
    prob = pulp.LpProblem("table_seating", pulp.LpMinimize)

    # x[sid][tid] = 1 if student sid is at table tid
    x: dict[int, dict[int, pulp.LpVariable]] = {}
    for s in students:
        x[s.id] = {}
        if s.pinned_table_id is not None:
            # Force this student to their pinned table
            for tid in t_ids:
                x[s.id][tid] = pulp.LpVariable(
                    f"x_{s.id}_{tid}", cat="Binary")
                if tid == s.pinned_table_id:
                    prob += x[s.id][tid] == 1
                else:
                    prob += x[s.id][tid] == 0
        else:
            for tid in t_ids:
                x[s.id][tid] = pulp.LpVariable(
                    f"x_{s.id}_{tid}", cat="Binary")

    # Each student at exactly one table
    for sid in s_ids:
        prob += pulp.lpSum(x[sid][tid] for tid in t_ids) == 1

    # Each table holds exactly its target count (force-fill). This is
    # the key difference from the old <= capacity formulation — we
    # know exactly how many students go to each table before solving,
    # so the optimizer only decides WHICH students go where. Targets
    # are capped by capacity at computation time, so this is always
    # at least as tight as the old <= cap constraint.
    for tid in t_ids:
        prob += pulp.lpSum(x[sid][tid] for sid in s_ids) == targets[tid]

    # Forbidden pairs: can't share any table
    s_id_set = set(s_ids)
    for (a, b) in forbidden_pairs:
        if a in s_id_set and b in s_id_set:
            for tid in t_ids:
                prob += x[a][tid] + x[b][tid] <= 1

    # ── Objective: minimize weighted co-occurrence ──────────────────────────
    # For each relevant pair (a, b) with a non-zero weight (from pair
    # history and/or tag costs), and each table t, define y[a,b,t] = 1
    # iff both a and b are at t. Add weight * y to the objective.
    #
    # Linearization: y <= x_a, y <= x_b, y >= x_a + x_b - 1.
    # Because we're MINIMIZING, only the upper-bound constraints matter for
    # y to take the right value at optimum — but we include the lower bound
    # so reconstruction of the cost from the solved y's is accurate.
    #
    # Pair-history and tag costs are summed into a single weight per pair
    # so we only create one y-variable per (a, b, table) regardless of
    # how many sources contributed to the cost. This keeps variable count
    # bounded as more cost sources get added in later steps (cluster,
    # keep_apart).
    #
    # Pair-history is the dominant signal (weight 1 per past meeting in
    # this optimizer; tag costs use TAG_OPERATION_WEIGHT=30) so the
    # solver still prioritizes avoiding repeat tablemates over honoring
    # distribute rules when the two conflict.
    pair_weight: dict[tuple[int, int], int] = {}
    forbidden_set = set()
    for (a, b) in forbidden_pairs:
        forbidden_set.add((a, b))
        forbidden_set.add((b, a))

    for (a, b), count in pair_history.items():
        if count < MIN_PAIR_WEIGHT:
            continue
        if a not in s_id_set or b not in s_id_set:
            continue
        if (a, b) in forbidden_set:
            continue
        key = (a, b) if a < b else (b, a)
        pair_weight[key] = pair_weight.get(key, 0) + count

    for (a, b, delta) in tag_pair_costs:
        if a not in s_id_set or b not in s_id_set:
            continue
        if (a, b) in forbidden_set:
            continue
        key = (a, b) if a < b else (b, a)
        pair_weight[key] = pair_weight.get(key, 0) + delta

    # One y-variable per PAIR (not per pair × table) — the indicator we
    # need is "do a and b share ANY table this round," which fires the
    # cost once regardless of which table. Per-table y-vars are
    # wasteful for our purposes: the cost is the same whichever table
    # ends up holding both students. This cuts the binary variable
    # count by a factor of (num_tables), which dramatically improves
    # solver time on classes with several tables and tag rules.
    #
    # Only lower-bound constraints are needed for each table since
    # we're MINIMIZING. The solver naturally sets y = 0 when none of
    # the lower bounds force it to 1.
    #
    # IMPORTANT: this y = 0 default only works for POSITIVE coefficients
    # (the solver wants y small). For NEGATIVE coefficients (cluster
    # discounts), the solver wants y = 1 and would set it without
    # waiting for a lower bound to force it. To handle those correctly
    # we use a separate per-table y-var formulation with full upper +
    # lower bounds. Cluster pairs are typically small (close-knit
    # buddy groups), so the per-table multiplier stays bounded in
    # practice.
    #
    # Coefficient threshold: pairs whose total weight is below this
    # don't meaningfully shift the solution and slow branch-and-bound.
    # In table mode pair_history weight is 1:1, so MIN_PAIR_COST=1
    # keeps all single-meeting history pairs but filters truly net-
    # zero pairs (e.g. cluster discounts offsetting one meeting).
    MIN_PAIR_COST = 1

    obj_terms = []
    # Positive-weight y-vars: keyed by pair (one per pair, any-table)
    y_vars: dict[tuple[int, int], pulp.LpVariable] = {}
    for (a, b), weight in pair_weight.items():
        if abs(weight) < MIN_PAIR_COST:
            continue
        if weight > 0:
            # Positive: lower-bound formulation, one y per pair
            y = pulp.LpVariable(f"yp_{a}_{b}", cat="Binary")
            y_vars[(a, b)] = y
            for tid in t_ids:
                prob += y >= x[a][tid] + x[b][tid] - 1
            obj_terms.append(weight * y)
        else:
            # Negative: per-table y-vars with full linearization. The
            # cost of one cluster discount activating is exactly
            # `weight`; sum is across tables so a pair clustered at
            # SOME table gets the discount once.
            for tid in t_ids:
                y = pulp.LpVariable(f"yc_{a}_{b}_{tid}", cat="Binary")
                # Full linearization: y = 1 iff both at this table
                prob += y <= x[a][tid]
                prob += y <= x[b][tid]
                prob += y >= x[a][tid] + x[b][tid] - 1
                obj_terms.append(weight * y)
            # Note: at most one of these y's can be 1 (a pair can only
            # share one table), so the total discount per pair is at
            # most `weight` (single fire). Correct semantics.

    if obj_terms:
        prob += pulp.lpSum(obj_terms)
    else:
        # No pair history yet (first round) — any feasible assignment is
        # optimal. Give CBC a dummy zero objective.
        prob += 0

    # ── Solve ────────────────────────────────────────────────────────────────
    solver_kwargs = {"msg": 0}
    if time_limit_seconds is not None:
        solver_kwargs["timeLimit"] = time_limit_seconds
    solver = pulp.PULP_CBC_CMD(**solver_kwargs)
    prob.solve(solver)

    status_code = pulp.LpStatus[prob.status]
    # Check that we got a solution with every student placed
    assignments: list[tuple[int, int | None, int]] = []
    placed = 0
    for sid in s_ids:
        for tid in t_ids:
            v = x[sid][tid].value()
            if v is not None and v > 0.5:
                assignments.append((sid, None, tid))
                placed += 1
                break

    if placed < len(students):
        # Solver hit time limit or infeasibility without placing everyone
        return SeatingResult(
            assignments=[], total_repeat_score=0,
            status=(f"Infeasible (solver could not place all students — "
                    f"only {placed}/{len(students)} placed). "
                    f"Try a longer time limit.")
        )

    # Reconstruct total_repeat_score from the y-variables. y_vars is
    # keyed by (a, b) only (one any-table indicator per pair); a y
    # firing means the pair sat together at some table this round.
    score = 0
    for (a, b), y in y_vars.items():
        v = y.value()
        if v is not None and v > 0.5:
            score += pair_history.get((a, b), 0)

    if status_code == "Optimal":
        final_status = "Optimal"
    elif prob.status == pulp.LpStatusNotSolved or status_code in ("Not Solved", "Undefined"):
        # Time-limited termination but all students placed → best-effort.
        final_status = (f"Feasible (time limit hit after "
                        f"{time_limit_seconds}s — best effort)")
    else:
        final_status = status_code

    return SeatingResult(
        assignments=assignments,
        total_repeat_score=score,
        status=final_status,
    )