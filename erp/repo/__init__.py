"""Data access functions.

Every function takes a :class:`erp.db.Conn` as its first argument and runs
inside the transaction opened by :meth:`erp.db.Database.run`.
"""

#: Sort orders are stored in 64 bit integer columns; numbers typed into the
#: forms are limited to this range so no database rejects them.
SORT_ORDER_LIMIT = 1_000_000_000


def clamp_order(value) -> int:
    """A sort order as an integer within ``±SORT_ORDER_LIMIT`` (invalid values give 0)."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(-SORT_ORDER_LIMIT, min(SORT_ORDER_LIMIT, number))
