"""Maximum-weight one-to-one assignment, shared by both experiment arms.

Blueprint §9.4 step 5 requires a constrained one-to-one assignment, and both
the prior-art baseline and the challenger's context pre-pass need one. Giving
the baseline a weaker matcher than the challenger would understate the prior
art, which §0.2's straw-man rule forbids as squarely as understating CURRENT.

`akc_cir.identity` has its own Hungarian implementation, and it stays where it
is: it is Protected Core, its helper is private, and reaching into it from an
absorption challenger would couple a shadow path to a core internal. This is
the same 1955 algorithm written for this package, verified against brute-force
enumeration in the tests.
"""

from __future__ import annotations

__all__ = ["max_weight_assignment"]


def max_weight_assignment(weights: list[list[float]]) -> dict[int, int]:
    """Row -> column for the assignment maximising total weight.

    The matrix is padded to square with zero weight, so a row or column with no
    good partner is left unmatched rather than forced onto whoever was left.
    Pairs are returned regardless of how weak they are; deciding whether a pair
    is good enough to act on belongs to the caller's thresholds, not here.
    """
    rows = len(weights)
    cols = len(weights[0]) if rows else 0
    if not rows or not cols:
        return {}
    if any(len(row) != cols for row in weights):
        raise ValueError("weight matrix rows must all have the same length")

    size = max(rows, cols)
    # Minimise cost = -weight over the padded square matrix.
    cost = [
        [-(weights[i][j] if i < rows and j < cols else 0.0) for j in range(size)]
        for i in range(size)
    ]

    inf = float("inf")
    potential_row = [0.0] * (size + 1)
    potential_col = [0.0] * (size + 1)
    parent = [0] * (size + 1)
    way = [0] * (size + 1)

    for row in range(1, size + 1):
        parent[0] = row
        col = 0
        best = [inf] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[col] = True
            current_row = parent[col]
            delta = inf
            next_col = 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                reduced = (
                    cost[current_row - 1][candidate - 1]
                    - potential_row[current_row]
                    - potential_col[candidate]
                )
                if reduced < best[candidate]:
                    best[candidate] = reduced
                    way[candidate] = col
                if best[candidate] < delta:
                    delta = best[candidate]
                    next_col = candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    potential_row[parent[candidate]] += delta
                    potential_col[candidate] -= delta
                else:
                    best[candidate] -= delta
            col = next_col
            if parent[col] == 0:
                break
        while col:
            previous = way[col]
            parent[col] = parent[previous]
            col = previous

    assignment: dict[int, int] = {}
    for column in range(1, size + 1):
        matched_row = parent[column] - 1
        matched_col = column - 1
        if matched_row < rows and matched_col < cols:
            assignment[matched_row] = matched_col
    return assignment
