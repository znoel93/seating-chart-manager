"""
seating_distribution.py — Balanced student-count distribution across
tables for the seating optimizer.

Problem: given N students and M tables of (possibly different)
capacities, decide how many students each table should hold so that
the distribution is as even as possible — avoiding the "lonely student
at an otherwise-empty table" failure mode the old <= capacity
formulation was prone to.

The optimizer then receives these counts as hard "== target" constraints
and only decides WHICH students go where, not HOW MANY per table.

Policy:
  - Every table gets N // M as its base target.
  - Any surplus (if base exceeds a table's capacity) overflows into the
    remainder pool.
  - The remainder (N % M + any overflow from capacity-capped tables) is
    distributed one-at-a-time, preferring larger tables first, skipping
    any table that's already at its capacity.
  - Pins are honored by bumping up targets on pinned tables and reducing
    targets on others, subject to feasibility.

Raises InfeasibleDistribution when the inputs can't be reconciled —
e.g. pins concentrated on one table beyond its capacity, or N exceeding
total capacity. The optimizer surfaces this to the caller as a normal
infeasibility error.
"""

from dataclasses import dataclass


class InfeasibleDistribution(Exception):
    """Raised when a balanced distribution isn't achievable with the
    given inputs. Message is user-readable."""


@dataclass
class _TableSpec:
    id: int
    capacity: int


def compute_table_targets(
    num_students: int,
    tables: list[tuple[int, int]],
    pin_counts: dict[int, int] | None = None,
) -> dict[int, int]:
    """Compute how many students each table should hold.

    Args:
        num_students: count of participating students this round
            (already filtered to exclude absent students)
        tables: list of (table_id, capacity) tuples for active
            (non-excluded) tables only. Excluded tables should be
            removed by the caller before invoking this function.
        pin_counts: {table_id: num_students_pinned_here}. May be None
            or empty. Tables not in the dict are assumed to have 0
            pins.

    Returns:
        {table_id: target_count} mapping. The sum of values equals
        num_students. Each target is in [0, capacity] for its table.

    Raises:
        InfeasibleDistribution if no valid target assignment exists.
    """
    pin_counts = dict(pin_counts or {})

    if num_students < 0:
        raise InfeasibleDistribution(
            f"Invalid student count: {num_students}")

    if not tables:
        if num_students == 0:
            return {}
        raise InfeasibleDistribution(
            "No tables available for this round.")

    specs = [_TableSpec(tid, cap) for tid, cap in tables]
    total_capacity = sum(s.capacity for s in specs)

    if num_students > total_capacity:
        raise InfeasibleDistribution(
            f"Not enough seats: {num_students} students but only "
            f"{total_capacity} seats across available tables.")

    # Validate pins reference real tables with room
    table_ids = {s.id for s in specs}
    cap_by_id = {s.id: s.capacity for s in specs}
    for tid, count in pin_counts.items():
        if tid not in table_ids:
            raise InfeasibleDistribution(
                f"Pinned to a table (id {tid}) that isn't in this round.")
        if count > cap_by_id[tid]:
            raise InfeasibleDistribution(
                f"Too many students pinned to table {tid} "
                f"({count} pinned, capacity {cap_by_id[tid]}).")
    total_pinned = sum(pin_counts.values())
    if total_pinned > num_students:
        # Shouldn't happen in practice but guard anyway
        raise InfeasibleDistribution(
            f"More students pinned ({total_pinned}) than present "
            f"({num_students}).")

    # ── Phase A: base allocation ────────────────────────────────────
    # Each table starts at N // M, capped by its own capacity. Any
    # capacity-clipped surplus gets added to the remainder pool for
    # Phase B redistribution.
    num_tables = len(specs)
    base = num_students // num_tables
    remainder = num_students % num_tables

    targets: dict[int, int] = {}
    for s in specs:
        give = min(base, s.capacity)
        targets[s.id] = give
        # Any unassignable base counts (because capacity was below
        # base) feed back into the remainder pool.
        remainder += (base - give)

    # ── Phase B: distribute remainder, larger tables first ──────────
    # Sort by capacity descending so surplus goes to tables that feel
    # emptier when under-filled. Ties broken by id for determinism.
    by_capacity = sorted(specs, key=lambda s: (-s.capacity, s.id))

    # Loop through tables; each eligible table gets +1 per pass until
    # remainder is exhausted. A table is eligible if it still has
    # capacity left. We cap the pass count defensively to avoid
    # infinite loops on pathological inputs (should be unreachable
    # given the feasibility checks above, but belt-and-braces).
    max_passes = num_students + num_tables + 1
    passes = 0
    while remainder > 0 and passes < max_passes:
        progress_this_pass = False
        for s in by_capacity:
            if remainder == 0:
                break
            if targets[s.id] < s.capacity:
                targets[s.id] += 1
                remainder -= 1
                progress_this_pass = True
        if not progress_this_pass:
            break
        passes += 1

    if remainder > 0:
        # Total capacity was enough (we checked earlier) so this
        # shouldn't happen. If it does, the algorithm has a bug.
        raise InfeasibleDistribution(
            f"Could not distribute {remainder} remaining student(s). "
            "This is a bug — please report.")

    # ── Phase C: honor pins ─────────────────────────────────────────
    # If any table has more pins than its current target, bump that
    # table's target up to the pin count. Reduce another table's
    # target by the same amount to preserve the total count of N.
    #
    # The reduction target is chosen as "the table whose current
    # target is furthest above its own pin count" — guaranteeing we
    # never reduce a table below ITS pin count in a single adjustment.
    # If we can't find such a table, the pin configuration is
    # infeasible.
    def _adjust_once():
        """Find a single conflict, fix it, and return True. Return
        False if no conflict exists."""
        # Find the most over-pinned table (target < pin_count)
        worst_over = None
        worst_deficit = 0
        for s in specs:
            pin_here = pin_counts.get(s.id, 0)
            deficit = pin_here - targets[s.id]
            if deficit > worst_deficit:
                worst_deficit = deficit
                worst_over = s
        if worst_over is None:
            return False

        # Find the table with the largest slack above its own pin count
        # (where slack = target - pin_count). It must be reducible —
        # i.e. slack > 0 — and must not be the conflicted table itself.
        best_donor = None
        best_slack = 0
        for s in specs:
            if s.id == worst_over.id:
                continue
            pin_here = pin_counts.get(s.id, 0)
            slack = targets[s.id] - pin_here
            if slack > best_slack:
                best_slack = slack
                best_donor = s
        if best_donor is None:
            # Nowhere to take from — pins are infeasible
            raise InfeasibleDistribution(
                f"Pins conflict with balanced distribution — too many "
                f"students pinned to one area without room to adjust.")

        # Move 1 from donor to over-pinned table
        targets[best_donor.id] -= 1
        targets[worst_over.id] += 1
        return True

    # Iterate until no more conflicts exist. Bounded by the total
    # number of students (each adjustment fixes 1 unit of deficit).
    max_adjustments = num_students + 1
    for _ in range(max_adjustments):
        if not _adjust_once():
            break

    # ── Validate invariants before returning ────────────────────────
    if sum(targets.values()) != num_students:
        raise InfeasibleDistribution(
            f"Internal error: targets sum to {sum(targets.values())}, "
            f"expected {num_students}.")
    for s in specs:
        if targets[s.id] < 0 or targets[s.id] > s.capacity:
            raise InfeasibleDistribution(
                f"Internal error: table {s.id} target "
                f"{targets[s.id]} out of range [0, {s.capacity}].")
        pin_here = pin_counts.get(s.id, 0)
        if targets[s.id] < pin_here:
            raise InfeasibleDistribution(
                f"Pin conflict on table {s.id}: {pin_here} pinned, "
                f"but only {targets[s.id]} seats allocated.")

    return targets