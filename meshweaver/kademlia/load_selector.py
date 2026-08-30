"""
load_selector.py — Lowest-CPU node selection from the gossip/load table.

When the local node needs to route a task to another peer it should prefer the
peer with the **lowest reported CPU load**.  Load information is propagated
around the overlay by Sahil's gossip layer (``GossipManager``), which
maintains a ``peer_table`` dict whose values are :class:`ResourceStatus`
dictionaries with the structure::

    {
        "node_id":     str,          # string node identifier
        "cpu_percent": float,        # 0.0 – 100.0
        "ram_percent": float,        # 0.0 – 100.0
        "timestamp":   float,        # Unix time of last update
    }

:class:`LoadSelector` is **pure data** — it reads that dict and returns a
result; it never performs I/O, never calls :mod:`psutil`, and has no external
dependencies beyond the Python standard library.

Design notes
------------
* **No networking / no I/O** — completely testable without real nodes.
* **No extra dependencies** — standard library only (``time``, ``dataclasses``).
* **Staleness guard** — entries older than *stale_after* seconds are ignored so
  that dead nodes whose gossip has expired are never selected.
* **Local-node exclusion** — the submitting node is never selected as the
  target (it would be a no-op routing decision at best, a cycle at worst).
* **Reuses existing structures** — works alongside the existing
  :class:`~meshweaver.kademlia.peer_store.PeerStore` / routing table; does
  not replace them.

Public API
----------
- ``LoadEntry``    — typed view of a single peer's gossip load record.
- ``SelectionResult`` — the outcome of a single :meth:`LoadSelector.select` call.
- ``LoadSelector`` — stateless selector; owns the staleness / exclusion logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# LoadEntry — typed view of a single gossip record
# ---------------------------------------------------------------------------


@dataclass
class LoadEntry:
    """A validated, typed snapshot of one peer's gossip load record.

    Constructed from the raw ``dict`` stored in ``GossipManager.peer_table``.

    Attributes
    ----------
    node_id:
        String node identifier (matches the key used by the gossip layer).
    cpu_percent:
        CPU utilisation as a percentage in the range ``[0.0, 100.0]``.
    ram_percent:
        RAM utilisation as a percentage in the range ``[0.0, 100.0]``.
    timestamp:
        Unix timestamp (float) of when this reading was captured.
    """

    node_id: str
    cpu_percent: float
    ram_percent: float
    timestamp: float

    @classmethod
    def from_dict(cls, data: dict) -> "LoadEntry":
        """Parse a raw gossip record dict into a :class:`LoadEntry`.

        Parameters
        ----------
        data:
            A dict with keys ``"node_id"``, ``"cpu_percent"``,
            ``"ram_percent"``, and ``"timestamp"`` as produced by
            ``ResourceStatus.to_dict()`` in the gossip layer.

        Returns
        -------
        LoadEntry

        Raises
        ------
        KeyError
            If a required field is missing.
        ValueError
            If a numeric field cannot be converted to ``float``.
        """
        return cls(
            node_id=str(data["node_id"]),
            cpu_percent=float(data["cpu_percent"]),
            ram_percent=float(data["ram_percent"]),
            timestamp=float(data["timestamp"]),
        )

    def age(self, now: Optional[float] = None) -> float:
        """Return the age of this entry in seconds relative to *now*.

        Parameters
        ----------
        now:
            Reference Unix timestamp.  Defaults to :func:`time.time`.
        """
        if now is None:
            now = time.time()
        return now - self.timestamp

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LoadEntry("
            f"node_id={self.node_id!r}, "
            f"cpu={self.cpu_percent:.1f}%, "
            f"ram={self.ram_percent:.1f}%, "
            f"age={self.age():.1f}s)"
        )


# ---------------------------------------------------------------------------
# SelectionResult — outcome of a single select() call
# ---------------------------------------------------------------------------


@dataclass
class SelectionResult:
    """The outcome of a :meth:`LoadSelector.select` call.

    Attributes
    ----------
    winner:
        The :class:`LoadEntry` of the selected (lowest-CPU) peer, or ``None``
        if no eligible peer was found.
    candidates:
        All load entries that passed the staleness and exclusion filters.
    excluded_stale:
        Number of entries discarded because they were too old.
    excluded_local:
        Number of entries discarded because they matched the local node ID.
    """

    winner: Optional[LoadEntry]
    candidates: List[LoadEntry]
    excluded_stale: int
    excluded_local: int

    @property
    def has_winner(self) -> bool:
        """Return ``True`` if a peer was successfully selected."""
        return self.winner is not None

    def __repr__(self) -> str:  # pragma: no cover
        if self.winner:
            return (
                f"SelectionResult("
                f"winner={self.winner.node_id!r}, "
                f"cpu={self.winner.cpu_percent:.1f}%, "
                f"candidates={len(self.candidates)}, "
                f"stale={self.excluded_stale}, "
                f"local={self.excluded_local})"
            )
        return (
            f"SelectionResult("
            f"winner=None, "
            f"candidates={len(self.candidates)}, "
            f"stale={self.excluded_stale}, "
            f"local={self.excluded_local})"
        )


# ---------------------------------------------------------------------------
# LoadSelector
# ---------------------------------------------------------------------------


class LoadSelector:
    """Selects the lowest-CPU peer from a gossip load table.

    :class:`LoadSelector` is a **stateless** helper — it holds configuration
    (staleness threshold, local node ID) and applies it on demand to whatever
    snapshot of the gossip table is passed to :meth:`select`.  It never stores
    the table itself; callers always supply the current state.

    Parameters
    ----------
    local_node_id:
        String node ID of the **local** node (the one submitting the task).
        Entries with this ID are always excluded from selection so the node
        does not route a task to itself.
    stale_after:
        Maximum age (in seconds) of a gossip entry before it is considered
        stale and ignored.  Entries older than this threshold indicate that
        the peer has not gossiped recently and may be unreachable.  Defaults
        to ``30.0`` seconds.

    Examples
    --------
    >>> selector = LoadSelector(local_node_id="node-local", stale_after=30.0)
    >>> table = {
    ...     "node-a": {"node_id": "node-a", "cpu_percent": 20.0,
    ...                "ram_percent": 40.0, "timestamp": time.time()},
    ...     "node-b": {"node_id": "node-b", "cpu_percent": 10.0,
    ...                "ram_percent": 60.0, "timestamp": time.time()},
    ... }
    >>> result = selector.select(table)
    >>> result.winner.node_id
    'node-b'
    """

    DEFAULT_STALE_AFTER: float = 30.0

    def __init__(
        self,
        local_node_id: str,
        stale_after: float = DEFAULT_STALE_AFTER,
    ) -> None:
        if not local_node_id:
            raise ValueError("local_node_id must be a non-empty string")
        if stale_after <= 0:
            raise ValueError(
                f"stale_after must be a positive number of seconds, got {stale_after}"
            )
        self._local_node_id: str = local_node_id
        self._stale_after: float = stale_after

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(
        self,
        peer_table: Dict[str, dict],
        now: Optional[float] = None,
    ) -> SelectionResult:
        """Select the peer with the lowest CPU load from *peer_table*.

        For each entry in *peer_table* the method:

        1. Parses the raw dict into a :class:`LoadEntry` (skips malformed
           entries silently).
        2. Discards entries that are **stale** (older than *stale_after*
           seconds).
        3. Discards entries whose ``node_id`` matches the **local node**
           (the submitting node should not route tasks to itself).
        4. Among the remaining **candidates**, selects the one with the
           **lowest** ``cpu_percent``.  Ties are broken by the order entries
           appear after ``min()`` evaluation (stable across equal loads).

        Parameters
        ----------
        peer_table:
            The gossip load table — a ``dict`` mapping ``node_id`` (str) to
            raw load-record dicts as maintained by ``GossipManager.peer_table``.
            The dict may be empty.
        now:
            Reference Unix timestamp used for staleness checks.  Defaults to
            :func:`time.time`.  Pass an explicit value in tests to keep them
            deterministic.

        Returns
        -------
        SelectionResult
            Always returns a :class:`SelectionResult`; check
            :attr:`~SelectionResult.has_winner` to determine whether any
            eligible peer was found.
        """
        if now is None:
            now = time.time()

        excluded_stale = 0
        excluded_local = 0
        candidates: List[LoadEntry] = []

        for _key, raw in peer_table.items():
            # ---------------------------------------------------------------
            # Step 1: parse the raw dict into a typed LoadEntry.
            # ---------------------------------------------------------------
            try:
                entry = LoadEntry.from_dict(raw)
            except (KeyError, ValueError, TypeError):
                # Malformed record — skip silently.
                continue

            # ---------------------------------------------------------------
            # Step 2: exclude the local node.
            # ---------------------------------------------------------------
            if entry.node_id == self._local_node_id:
                excluded_local += 1
                continue

            # ---------------------------------------------------------------
            # Step 3: exclude stale entries.
            # ---------------------------------------------------------------
            if entry.age(now) >= self._stale_after:
                excluded_stale += 1
                continue

            candidates.append(entry)

        # -------------------------------------------------------------------
        # Step 4: pick the winner (lowest CPU among candidates).
        # -------------------------------------------------------------------
        winner: Optional[LoadEntry] = None
        if candidates:
            winner = min(candidates, key=lambda e: e.cpu_percent)

        return SelectionResult(
            winner=winner,
            candidates=candidates,
            excluded_stale=excluded_stale,
            excluded_local=excluded_local,
        )

    def filter_candidates(
        self,
        peer_table: Dict[str, dict],
        now: Optional[float] = None,
    ) -> List[LoadEntry]:
        """Return all eligible (fresh, non-local) candidates without selecting.

        A convenience method that returns the full candidate list produced
        during :meth:`select`, sorted by ``cpu_percent`` ascending (lowest
        first).  Useful for routing tables that want the top-N cheapest peers.

        Parameters
        ----------
        peer_table:
            The gossip load table.
        now:
            Reference timestamp for staleness.  Defaults to :func:`time.time`.

        Returns
        -------
        list[LoadEntry]
            Fresh, non-local entries sorted by ``cpu_percent`` ascending.
            Empty if no eligible candidates exist.
        """
        result = self.select(peer_table, now=now)
        return sorted(result.candidates, key=lambda e: e.cpu_percent)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def local_node_id(self) -> str:
        """The local node ID that is always excluded from selection."""
        return self._local_node_id

    @property
    def stale_after(self) -> float:
        """Maximum entry age in seconds before an entry is considered stale."""
        return self._stale_after

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LoadSelector("
            f"local={self._local_node_id!r}, "
            f"stale_after={self._stale_after}s)"
        )
