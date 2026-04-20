"""
optimizer.py — ILP-based seat-level seating assignment using PuLP.

Per-seat model: students are assigned to individual seats. Pair scoring uses
a distance-bucketed adjacency weight — two students at adjacent seats count
more heavily toward repeat-pair penalties than students across a large table.
"""

from dataclasses import dataclass
import math
import pulp


@dataclass
class Seat:
    id: int
    table_id: int
    x: float
    y: float


@dataclass
class Student:
    id: int
    name: str
    pinned_seat_id: int | None = None
    pinned_table_id: int | None = None


@dataclass
class SeatingResult:
    assignments: list[tuple[int, int, int]]   # (student_id, seat_id, table_id)
    total_repeat_score: int
    status: str


# Adjacency weight tiers keyed on canvas-pixel distance between seats.
# Seats at different tables always get weight 0.
# Note the far same-table tier (>220px) is intentionally weighted 0 too.
# It was 0.15 in an earlier version but contributed very little signal
# relative to the combinatorial cost, so we now treat "opposite ends of
# a big table" the same as different tables.
ADJACENCY_TIERS = [
    (80.0,  1.00),    # adjacent (neighboring seats)
    (130.0, 0.70),    # near     (skipped one, same side)
    (220.0, 0.40),    # mid      (diagonal / small table across)
    # Beyond 220px → 0 (no interaction)
]


def _adjacency_weight(seat_a: Seat, seat_b: Seat) -> float:
    if seat_a.table_id != seat_b.table_id:
        return 0.0
    dx = seat_a.x - seat_b.x
    dy = seat_a.y - seat_b.y
    dist = math.hypot(dx, dy)
    for threshold, weight in ADJACENCY_TIERS:
        if dist <= threshold:
            return weight
    return 0.0


def optimise_seating(
    students: list[Student],
    seats: list[Seat],
    pair_history: dict[tuple[int, int], int],
    forbidden_pairs: list[tuple[int, int]] | None = None,
    time_limit_seconds: int | None = 30,
    seat_history: dict[tuple[int, int], int] | None = None,
) -> SeatingResult:
    """Solve the seat assignment ILP.

    pair_history: {(student_a, student_b): count} — how many times these
        two students have sat together at the same table. Used as the
        dominant optimization signal.

    seat_history: {(student_id, seat_id): count} — how many times this
        student has sat at this particular seat. Used as a smaller
        tiebreaker signal: when pair-history leaves the objective
        indifferent (many equivalent zero-cost solutions), seat-history
        rotates students through different seats round-to-round instead
        of letting CBC's internal ordering anchor the same student to
        the same seat every time.

    time_limit_seconds: hard wall-clock cap on solver runtime. Default 30s.
    """
    forbidden_pairs = forbidden_pairs or []
    seat_history   = seat_history or {}

    if not students:
        return SeatingResult(assignments=[], total_repeat_score=0, status="Optimal")

    if len(seats) < len(students):
        return SeatingResult(
            assignments=[], total_repeat_score=0,
            status=f"Infeasible: only {len(seats)} seats for {len(students)} students"
        )

    seat_by_id = {k.id: k for k in seats}
    seat_ids = [k.id for k in seats]
    s_ids = [s.id for s in students]

    seats_by_table: dict[int, list[int]] = {}
    for k in seats:
        seats_by_table.setdefault(k.table_id, []).append(k.id)

    # ── Validate pins ────────────────────────────────────────────────────────
    seat_id_set = set(seat_ids)
    pin_seat_taken: set[int] = set()
    pin_table_counts: dict[int, int] = {}
    for s in students:
        if s.pinned_seat_id is not None:
            if s.pinned_seat_id not in seat_id_set:
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status=f"Infeasible: {s.name}'s pinned seat is not available")
            if s.pinned_seat_id in pin_seat_taken:
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status="Infeasible: two students pinned to the same seat")
            pin_seat_taken.add(s.pinned_seat_id)
        elif s.pinned_table_id is not None:
            if s.pinned_table_id not in seats_by_table:
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status=(f"Infeasible: {s.name} is pinned to a table that "
                            "isn't in this round (maybe excluded?)"))
            pin_table_counts[s.pinned_table_id] = (
                pin_table_counts.get(s.pinned_table_id, 0) + 1)
            if pin_table_counts[s.pinned_table_id] > len(seats_by_table[s.pinned_table_id]):
                return SeatingResult(
                    assignments=[], total_repeat_score=0,
                    status="Infeasible: too many students pinned to one table")

    # ── Problem ──────────────────────────────────────────────────────────────
    prob = pulp.LpProblem("SeatingChart", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", (s_ids, seat_ids), cat="Binary")

    # Precompute same-table seat pairs with nonzero adjacency weight
    adj_pairs: list[tuple[int, int, float]] = []
    for table_id, seat_list in seats_by_table.items():
        for i in range(len(seat_list)):
            for j in range(i + 1, len(seat_list)):
                sa, sb = seat_list[i], seat_list[j]
                w = _adjacency_weight(seat_by_id[sa], seat_by_id[sb])
                if w > 0:
                    adj_pairs.append((sa, sb, w))

    s_id_set = set(s_ids)
    relevant_history = {
        (a, b): cnt for (a, b), cnt in pair_history.items()
        if cnt > 0 and a in s_id_set and b in s_id_set
    }

    COST_SCALE = 100
    # Option 3: drop y-vars whose scaled cost would be below this threshold.
    # Pairs with (history × weight × COST_SCALE) below this get no variable
    # and contribute 0 to the objective. Threshold of 50 means:
    #   - 1 meeting × adjacent (weight 1.0)    = 100 → kept
    #   - 1 meeting × near (weight 0.7)        = 70  → kept
    #   - 1 meeting × mid (weight 0.4)         = 40  → PRUNED
    #   - 2 meetings × mid (weight 0.4)        = 80  → kept
    # So a pair that's met once at mid-distance carries no penalty, but the
    # moment they meet a second time, the optimizer starts actively avoiding
    # that combination. One-round lag on mid-distance optimization in exchange
    # for drastically reducing the variable count. Adjacent and near pairings
    # remain fully optimized from the first meeting.
    MIN_COST_THRESHOLD = 50

    # Option 1: one y-var per (student_pair, UNORDERED seat_pair) instead of
    # two. y = 1 iff both students occupy this seat pair in either order.
    # This halves the variable count relative to the previous two-ordering
    # formulation without losing any expressiveness — both orderings carried
    # identical cost anyway.
    #
    # Linearisation for the unordered variable:
    #   y <= x[a][sa] + x[a][sb]      (a must occupy one of these two seats)
    #   y <= x[b][sa] + x[b][sb]      (b must occupy one of these two seats)
    #   y <= x[a][sa] + x[b][sa]      (seat sa must be held by a or b)
    #   y <= x[a][sb] + x[b][sb]      (seat sb must be held by a or b)
    #   y >= x[a][sa] + x[b][sb] + x[a][sb] + x[b][sa] - 1   (lower bound)
    # Combined, these encode: y = 1 iff {a,b} occupy {sa,sb} as a set.
    y: dict = {}
    cost_terms = []
    pruned_count = 0
    for (a, b), history_count in relevant_history.items():
        for (sa, sb, w) in adj_pairs:
            cost = int(history_count * w * COST_SCALE)
            if cost < MIN_COST_THRESHOLD:
                pruned_count += 1
                continue
            v = pulp.LpVariable(f"y_{a}_{b}_{sa}_{sb}", cat="Binary")
            y[(a, b, sa, sb)] = v
            # Upper bounds (y forced to 0 unless both students are present
            # at both seats)
            prob += v <= x[a][sa] + x[a][sb]
            prob += v <= x[b][sa] + x[b][sb]
            prob += v <= x[a][sa] + x[b][sa]
            prob += v <= x[a][sb] + x[b][sb]
            # Lower bound: y >= 1 when the pair-of-students covers the pair-
            # of-seats. The sum on the RHS equals 2 in both valid orderings
            # (a@sa+b@sb or a@sb+b@sa), so -1 gives us the expected 1.
            prob += v >= (x[a][sa] + x[b][sb] +
                          x[a][sb] + x[b][sa] - 1)
            cost_terms.append(cost * v)

    # ── Objective ────────────────────────────────────────────────────────────
    # Seat-history tiebreaker: nudge students away from seats they've already
    # occupied, so the optimizer picks genuinely varied seat assignments when
    # pair-history leaves the objective indifferent. Weight deliberately tiny
    # compared to pair costs — we want seat rotation to break ties between
    # equally-good pair arrangements, NOT to override real pair optimization.
    #
    # Even the smallest surviving pair cost (1 meeting × 0.7 weight × 100 = 70)
    # outweighs 6 prior same-seat sittings (6 × 10 = 60). So the solver
    # strictly prefers "avoid pair-repeats" over "rotate seats."
    SEAT_HISTORY_WEIGHT = 10
    seat_terms = []
    if seat_history:
        for (stu_id, seat_id), count in seat_history.items():
            if stu_id in s_id_set and seat_id in seat_ids and count > 0:
                seat_terms.append(SEAT_HISTORY_WEIGHT * count * x[stu_id][seat_id])

    objective_terms = cost_terms + seat_terms
    if objective_terms:
        prob += pulp.lpSum(objective_terms)
    else:
        prob += 0

    # ── Constraints ──────────────────────────────────────────────────────────
    for s in s_ids:
        prob += pulp.lpSum(x[s][k] for k in seat_ids) == 1

    for k in seat_ids:
        prob += pulp.lpSum(x[s][k] for s in s_ids) <= 1

    for s in students:
        if s.pinned_seat_id is not None:
            prob += x[s.id][s.pinned_seat_id] == 1

    for s in students:
        if s.pinned_seat_id is None and s.pinned_table_id is not None:
            prob += pulp.lpSum(
                x[s.id][k] for k in seats_by_table.get(s.pinned_table_id, [])
            ) == 1

    for (a, b) in forbidden_pairs:
        if a in s_id_set and b in s_id_set:
            for table_id, seat_list in seats_by_table.items():
                prob += (pulp.lpSum(x[a][k] for k in seat_list) +
                         pulp.lpSum(x[b][k] for k in seat_list) <= 1)

    # ── Solve ────────────────────────────────────────────────────────────────
    import time
    solver_kwargs = {"msg": 0}
    if time_limit_seconds is not None:
        solver_kwargs["timeLimit"] = time_limit_seconds
    solver = pulp.PULP_CBC_CMD(**solver_kwargs)
    t_start = time.monotonic()
    prob.solve(solver)
    elapsed = time.monotonic() - t_start

    # CBC status codes:
    #   1 = Optimal
    #   0 = Not Solved (includes time-limit-hit-with-feasible-solution)
    #  -1 = Infeasible
    #  -2 = Unbounded
    #  -3 = Undefined
    status_code = prob.status

    if status_code == 1:
        status = "Optimal"
    elif status_code == 0 and s_ids:
        # Solver returned without proving optimality (usually time limit).
        # Verify every student actually got a seat assigned — CBC sometimes
        # returns partial or null solutions at the time limit that would
        # leave students unseated. Anything less than a complete assignment
        # is not usable.
        seated_count = 0
        for s in s_ids:
            if any(pulp.value(x[s][k]) is not None and pulp.value(x[s][k]) > 0.5
                    for k in seat_ids):
                seated_count += 1
        if seated_count < len(s_ids):
            return SeatingResult(
                assignments=[], total_repeat_score=0,
                status=(f"Infeasible (solver ran out of time — only "
                        f"{seated_count}/{len(s_ids)} students could be seated). "
                        "Try a longer time limit."))
        if time_limit_seconds is not None and elapsed >= time_limit_seconds * 0.9:
            status = f"Feasible (time limit hit after {int(elapsed)}s — best effort)"
        else:
            status = "Feasible"
    elif status_code == 0:
        return SeatingResult(assignments=[], total_repeat_score=0,
                             status="Infeasible (no solution found)")
    else:
        return SeatingResult(assignments=[], total_repeat_score=0,
                             status=f"Infeasible (solver status {status_code})")

    assignments = []
    for s in s_ids:
        for k in seat_ids:
            val = pulp.value(x[s][k])
            if val is not None and val > 0.5:
                table_id = seat_by_id[k].table_id
                assignments.append((s, k, table_id))
                break

    # Compute the "pair cost" portion of the objective separately from the
    # seat-history tiebreaker portion. The reported score should reflect
    # only the pair-related signal; seat-history is internal noise to help
    # the optimizer rotate seating without changing the meaning of score.
    pair_cost_actual = 0
    for (a, b, sa, sb), v in y.items():
        if pulp.value(v) is not None and pulp.value(v) > 0.5:
            w = _adjacency_weight(seat_by_id[sa], seat_by_id[sb])
            pair_cost_actual += int(pair_history[(a, b)] * w * COST_SCALE)
    repeat_score = int(pair_cost_actual / COST_SCALE)
    return SeatingResult(assignments=assignments,
                         total_repeat_score=repeat_score,
                         status=status)