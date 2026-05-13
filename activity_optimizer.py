"""
activity_optimizer.py — ILP-based student-to-activity assignment using PuLP.

Structurally parallel to optimizer_table_mode.py (per-table seating):
students are assigned to ACTIVITIES (not tables). The optimizer minimizes
repeat tablemates [co-attendees] across activity rounds, and ALSO
minimizes repeat student-to-activity pairings ("don't let Alice tutor
every week").

Shared patterns with the seating optimizers:
  - PuLP + CBC solver
  - compute_table_targets for balanced distribution (force-fill)
  - Same linearization for pair-history (y-var per pair per activity)
  - Same status-code handling for time-limited solutions

New to this optimizer:
  - Per-student activity exclusions as hard constraints (row-level
    "Alice cannot do tutoring")
  - Student-activity repeat cost as a secondary objective term —
    lighter weight than pair repeats, nudges rotation through
    activities over time without overriding pair mixing
  - Pin target is an activity (not a seat/table)
"""

from dataclasses import dataclass, field
import pulp


@dataclass
class Activity:
    id: int
    capacity: int


@dataclass
class Student:
    id: int
    name: str
    pinned_activity_id: int | None = None
    excluded_activity_ids: list[int] = field(default_factory=list)


@dataclass
class ActivityResult:
    # (student_id, activity_id) pairs — flat assignment record.
    assignments: list[tuple[int, int]]
    # Pair-repeat cost reconstructed from the solved assignment.
    # Mirrors optimizer_table_mode's total_repeat_score: how many
    # times a previously-paired duo ended up co-assigned here.
    total_repeat_score: int
    # New signal: how many prior (student, activity) encounters were
    # repeated by this assignment. Useful for UI display ("3 students
    # doing a repeat activity this week").
    total_activity_repeat_score: int
    status: str


# ── Objective weights ──────────────────────────────────────────────────────
#
# Pair repeats are the DOMINANT signal, same as the seating optimizers.
# Activity repeats (student-repeats-activity) are a SECONDARY signal that
# nudges rotation through activities without ever overriding good pair
# mixing.
#
# Current ratio: 10:1 (pair-repeats cost 10× as much as activity-repeats).
# This means the solver would rather reassign Alice to an activity she's
# done 9 times before than co-assign her with a partner she's been paired
# with once before. That feels about right — pair mixing is the core
# "social" goal; rotating through activities is a soft preference.
#
# Tuning these is open to revision after real-world use. Both are
# integer-scaled (×100) so the ILP's integer-programming stays clean.
PAIR_REPEAT_WEIGHT     = 100
ACTIVITY_REPEAT_WEIGHT = 10


def optimise_activity_assignment(
    students: list[Student],
    activities: list[Activity],
    pair_history: dict[tuple[int, int], int],
    student_activity_history: dict[tuple[int, int], int],
    forbidden_pairs: list[tuple[int, int]] | None = None,
    tag_pair_costs: list[tuple[int, int, int]] | None = None,
    time_limit_seconds: int | None = 30,
) -> ActivityResult:
    """Solve the activity assignment ILP.

    students: list of Student objects. pinned_activity_id honored as hard
        constraint; excluded_activity_ids honored as hard constraint.
    activities: list of Activity objects. capacity is the max (and also
        the exact — force-fill enforces == target).
    pair_history: {(a, b) sorted: count} — past same-activity
        co-occurrences (or seating co-occurrences if pair_history_mode
        is 'combined'). Caller decides via db.get_pair_history_for_mode.
    student_activity_history: {(student_id, activity_id): count} — past
        assignments of this student to this activity. Used as the
        secondary minimization signal.
    forbidden_pairs: global "never pair X with Y" rules. Applies across
        seating and activity rounds uniformly.
    tag_pair_costs: list of (sid_a, sid_b, weight_delta) — soft costs
        injected by the tag system. Positive weights discourage sharing
        (distribute, keep_apart); negative weights encourage sharing
        (cluster). Layered on top of pair_history × PAIR_REPEAT_WEIGHT
        via the same y-variable framework.
    time_limit_seconds: hard wall-clock cap on solver. Default 30.
    """
    forbidden_pairs = forbidden_pairs or []
    tag_pair_costs  = tag_pair_costs or []

    if not students:
        return ActivityResult(
            assignments=[], total_repeat_score=0,
            total_activity_repeat_score=0, status="Optimal")

    total_capacity = sum(a.capacity for a in activities)
    if total_capacity < len(students):
        return ActivityResult(
            assignments=[], total_repeat_score=0,
            total_activity_repeat_score=0,
            status=(f"Infeasible: only {total_capacity} activity slots "
                    f"available for {len(students)} students"))

    s_ids = [s.id for s in students]
    a_ids = [a.id for a in activities]
    a_cap = {a.id: a.capacity for a in activities}
    a_id_set = set(a_ids)

    # ── Validate pins ────────────────────────────────────────────────────────
    # A pinned student gets x[sid][pinned_aid] == 1 forced. A student
    # pinned to a nonexistent (excluded-from-round) activity is
    # infeasible upfront.
    pin_activity_counts: dict[int, int] = {}
    for s in students:
        if s.pinned_activity_id is not None:
            if s.pinned_activity_id not in a_id_set:
                return ActivityResult(
                    assignments=[], total_repeat_score=0,
                    total_activity_repeat_score=0,
                    status=(f"Infeasible: {s.name} is pinned to an activity "
                            "that isn't in this round (maybe excluded?)"))
            # Pin conflicts with exclusion? Flag loudly — the teacher
            # has an inconsistency to resolve.
            if s.pinned_activity_id in (s.excluded_activity_ids or []):
                return ActivityResult(
                    assignments=[], total_repeat_score=0,
                    total_activity_repeat_score=0,
                    status=(f"Infeasible: {s.name} is both pinned to and "
                            "excluded from the same activity."))
            pin_activity_counts[s.pinned_activity_id] = (
                pin_activity_counts.get(s.pinned_activity_id, 0) + 1)
            if pin_activity_counts[s.pinned_activity_id] > a_cap[s.pinned_activity_id]:
                return ActivityResult(
                    assignments=[], total_repeat_score=0,
                    total_activity_repeat_score=0,
                    status=(f"Infeasible: too many students pinned to "
                            f"activity {s.pinned_activity_id}"))

    # ── Compute balanced per-activity targets ────────────────────────────────
    # Force-fill: pre-compute exact counts so distribution is even.
    # Same algorithm used by both seating optimizers, with activities
    # substituted for tables.
    from seating_distribution import compute_table_targets, InfeasibleDistribution
    try:
        targets = compute_table_targets(
            num_students=len(students),
            tables=[(a.id, a.capacity) for a in activities],
            pin_counts=pin_activity_counts,
        )
    except InfeasibleDistribution as e:
        return ActivityResult(
            assignments=[], total_repeat_score=0,
            total_activity_repeat_score=0,
            status=f"Infeasible: {e}")

    # ── Problem setup ───────────────────────────────────────────────────────
    prob = pulp.LpProblem("activity_assignment", pulp.LpMinimize)

    # Decision variable: x[sid][aid] = 1 if student sid at activity aid
    x: dict[int, dict[int, pulp.LpVariable]] = {}
    for s in students:
        x[s.id] = {}
        for aid in a_ids:
            x[s.id][aid] = pulp.LpVariable(
                f"x_{s.id}_{aid}", cat="Binary")

    # ── Hard constraints ────────────────────────────────────────────────────
    # Each student assigned to exactly one activity
    for sid in s_ids:
        prob += pulp.lpSum(x[sid][aid] for aid in a_ids) == 1

    # Each activity holds exactly its target count (force-fill)
    for aid in a_ids:
        prob += pulp.lpSum(x[sid][aid] for sid in s_ids) == targets[aid]

    # Pins: force pinned student INTO their pinned activity
    for s in students:
        if s.pinned_activity_id is not None:
            prob += x[s.id][s.pinned_activity_id] == 1

    # Exclusions: force excluded student OUT of excluded activity
    for s in students:
        for excluded_aid in (s.excluded_activity_ids or []):
            if excluded_aid in a_id_set:
                prob += x[s.id][excluded_aid] == 0

    # Forbidden pairs: a and b can't share an activity (all of them)
    s_id_set = set(s_ids)
    for (a, b) in forbidden_pairs:
        if a in s_id_set and b in s_id_set:
            for aid in a_ids:
                prob += x[a][aid] + x[b][aid] <= 1

    # ── Objective ───────────────────────────────────────────────────────────
    # Three weighted cost terms:
    #   (1) pair-repeat cost: y_pair[a,b] = 1 iff a and b share ANY
    #       activity in this round. Cost = coeff × y_pair where coeff
    #       merges pair_history × PAIR_REPEAT_WEIGHT and any tag costs.
    #   (2) student-activity-repeat cost: for each (s, aid) with prior
    #       history, cost = count × ACTIVITY_REPEAT_WEIGHT × x[s][aid].
    #       No linearization needed — x is already our decision variable.
    #
    # We use ONE y-var per pair rather than one per (pair × activity)
    # because we only need an "any" indicator — the cost fires once if
    # the pair shares any activity, regardless of which. This is a
    # significant variable-count reduction vs the per-activity scheme:
    # for N activities and P relevant pairs, it cuts y-var count from
    # N×P to P (e.g. 6 activities × 200 pairs = 1200 → 200). Solver
    # times improve substantially on the typical 24-student × 6-
    # activity class.
    #
    # Only the LOWER bound y >= x[a][k] + x[b][k] - 1 needs to be
    # encoded for each activity k, since we're MINIMIZING. The upper
    # bound (y <= sum_k x[a][k]) is implied by the natural domain of
    # y as a binary variable and isn't needed for correctness — the
    # solver will set y = 0 whenever no LB forces y = 1.
    forbidden_set = set()
    for (a, b) in forbidden_pairs:
        forbidden_set.add((a, b))
        forbidden_set.add((b, a))

    # Compute total coefficient per (a, b) pair from history + tags
    pair_coeff: dict[tuple[int, int], int] = {}
    for (a, b), count in pair_history.items():
        if count <= 0:
            continue
        if a not in s_id_set or b not in s_id_set:
            continue
        if (a, b) in forbidden_set:
            continue
        key = (a, b) if a < b else (b, a)
        pair_coeff[key] = pair_coeff.get(key, 0) + count * PAIR_REPEAT_WEIGHT

    for (a, b, delta) in tag_pair_costs:
        if a not in s_id_set or b not in s_id_set:
            continue
        if (a, b) in forbidden_set:
            continue
        key = (a, b) if a < b else (b, a)
        pair_coeff[key] = pair_coeff.get(key, 0) + delta

    # Coefficient threshold: pairs whose total cost is below this don't
    # meaningfully shift the solution; we save solver time by not even
    # creating a y-variable. Matches the per-seat optimizer's pruning
    # strategy. Most "first round" tag-only pairs with weight=30 stay
    # in; this primarily filters tiny cluster discounts (Step 7) and
    # near-zero net-cost pairs.
    MIN_PAIR_COST = 10

    pair_obj_terms = []
    # y_vars indexed by (a, b) for positive coefficients (one any-
    # activity indicator per pair) and by (a, b, aid) for negative
    # coefficients (full linearization per activity, needed because
    # the solver wants negative-weight indicators to fire and would
    # set them to 1 without an upper bound).
    # Cluster pairs are typically small (close-knit buddy groups);
    # the per-activity multiplier remains bounded in practice.
    y_vars: dict[tuple[int, int], pulp.LpVariable] = {}
    for (a, b), coeff in pair_coeff.items():
        if abs(coeff) < MIN_PAIR_COST:
            continue
        if coeff > 0:
            # Positive: any-activity indicator, lower bounds only
            y = pulp.LpVariable(f"yp_{a}_{b}", cat="Binary")
            y_vars[(a, b)] = y
            for aid in a_ids:
                prob += y >= x[a][aid] + x[b][aid] - 1
            pair_obj_terms.append(coeff * y)
        else:
            # Negative: per-activity y-vars with full bounds
            for aid in a_ids:
                y = pulp.LpVariable(f"yc_{a}_{b}_{aid}", cat="Binary")
                prob += y <= x[a][aid]
                prob += y <= x[b][aid]
                prob += y >= x[a][aid] + x[b][aid] - 1
                pair_obj_terms.append(coeff * y)
            # Note: at most one of these y's can be 1 (a pair shares
            # at most one activity), so the total discount per pair is
            # at most `coeff` (single fire). Correct semantics.

    activity_obj_terms = []
    for (sid, aid), count in student_activity_history.items():
        if count <= 0:
            continue
        if sid not in s_id_set or aid not in a_id_set:
            continue
        activity_obj_terms.append(count * ACTIVITY_REPEAT_WEIGHT * x[sid][aid])

    all_terms = pair_obj_terms + activity_obj_terms
    if all_terms:
        prob += pulp.lpSum(all_terms)
    else:
        # First round — no history anywhere. Dummy zero objective.
        prob += 0

    # ── Solve ───────────────────────────────────────────────────────────────
    solver_kwargs = {"msg": 0}
    if time_limit_seconds is not None:
        solver_kwargs["timeLimit"] = time_limit_seconds
    solver = pulp.PULP_CBC_CMD(**solver_kwargs)
    prob.solve(solver)

    status_code_str = pulp.LpStatus[prob.status]

    # Collect the assignments
    assignments: list[tuple[int, int]] = []
    placed = 0
    for sid in s_ids:
        for aid in a_ids:
            v = x[sid][aid].value()
            if v is not None and v > 0.5:
                assignments.append((sid, aid))
                placed += 1
                break

    if placed < len(students):
        return ActivityResult(
            assignments=[], total_repeat_score=0,
            total_activity_repeat_score=0,
            status=(f"Infeasible (solver could not place all students — "
                    f"only {placed}/{len(students)} placed). "
                    "Try a longer time limit."))

    # ── Reconstruct reported scores ─────────────────────────────────────────
    # The objective value includes weighted terms; we want separate
    # natural-count totals to display to the teacher:
    #   - total_repeat_score: number of prior pairings that recurred
    #     (NOT the weighted cost — the raw sum of prior counts for
    #     the pairings that ended up sharing an activity here).
    #   - total_activity_repeat_score: number of prior student-activity
    #     assignments that recurred (again, raw sum).
    # y_vars is keyed by (a, b) only (the "any activity" indicator);
    # a y firing means the pair shared SOME activity in this round.
    pair_score = 0
    for (a, b), y in y_vars.items():
        v = y.value()
        if v is not None and v > 0.5:
            pair_score += pair_history.get((a, b), 0)

    sa_score = 0
    for (sid, aid) in assignments:
        sa_score += student_activity_history.get((sid, aid), 0)

    if status_code_str == "Optimal":
        final_status = "Optimal"
    elif prob.status == pulp.LpStatusNotSolved or status_code_str in ("Not Solved", "Undefined"):
        final_status = (f"Feasible (time limit hit after "
                        f"{time_limit_seconds}s — best effort)")
    else:
        final_status = status_code_str

    return ActivityResult(
        assignments=assignments,
        total_repeat_score=pair_score,
        total_activity_repeat_score=sa_score,
        status=final_status,
    )