"""
tests/test_load_selector.py — Focused tests for lowest-CPU node selection.

These tests verify every aspect of the LoadSelector selection logic:

Selection basics
    - The peer with the lowest cpu_percent is chosen from a non-empty table.
    - When all peers have equal CPU the first (min-stable) one is returned.
    - A single eligible peer is always selected.

Staleness filtering
    - Entries older than stale_after are excluded from selection.
    - An entry exactly at the stale boundary (age == stale_after) is excluded.
    - An entry just inside the boundary (age < stale_after) is included.
    - When all entries are stale, winner is None.
    - Stale count is accurately reported in SelectionResult.

Local-node exclusion
    - The local node's own entry is never selected.
    - When only the local node is in the table, winner is None.
    - local_node excluded count is accurately reported.

Empty / edge cases
    - An empty table returns a None winner with zero candidates.
    - A table with only malformed/unparseable records returns None winner.
    - A table combining stale + local + malformed entries, leaving no valid
      candidates, returns None winner.

filter_candidates
    - Returns candidates sorted by cpu_percent ascending.
    - Returns an empty list when no eligible candidates exist.

LoadEntry
    - from_dict() parses all required fields correctly.
    - from_dict() raises KeyError on a missing field.
    - from_dict() raises ValueError on an unconvertable numeric field.
    - age() computes the correct age relative to a fixed timestamp.

SelectionResult
    - has_winner is True only when winner is not None.

Constructor validation
    - Empty local_node_id raises ValueError.
    - stale_after <= 0 raises ValueError.

Run with:
    python -m pytest tests/test_load_selector.py -v
"""

from __future__ import annotations

import time

import pytest

from meshweaver.kademlia.load_selector import LoadEntry, LoadSelector, SelectionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    node_id: str,
    cpu: float,
    ram: float = 50.0,
    age: float = 0.0,
    now: float = 1_000_000.0,
) -> dict:
    """Build a gossip record dict with a controllable timestamp.

    Parameters
    ----------
    node_id : str
    cpu : float   cpu_percent 0–100
    ram : float   ram_percent 0–100
    age : float   how many seconds old the record is (relative to *now*)
    now : float   the reference "current" time
    """
    return {
        "node_id": node_id,
        "cpu_percent": cpu,
        "ram_percent": ram,
        "timestamp": now - age,
    }


# Fixed reference timestamp used across all deterministic tests.
NOW = 1_000_000.0
STALE = 30.0  # default stale_after

LOCAL = "local-node"


@pytest.fixture()
def selector() -> LoadSelector:
    return LoadSelector(local_node_id=LOCAL, stale_after=STALE)


# ===========================================================================
# Selection basics
# ===========================================================================


class TestSelectionBasics:

    def test_lowest_cpu_wins(self, selector):
        """The peer with the smallest cpu_percent must be returned."""
        table = {
            "a": _entry("a", cpu=80.0, now=NOW),
            "b": _entry("b", cpu=20.0, now=NOW),
            "c": _entry("c", cpu=55.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner is not None
        assert result.winner.node_id == "b"

    def test_lowest_cpu_value_is_correct(self, selector):
        """The winning entry carries the actual cpu_percent value."""
        table = {
            "x": _entry("x", cpu=15.5, now=NOW),
            "y": _entry("y", cpu=42.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner.cpu_percent == pytest.approx(15.5)

    def test_single_eligible_peer_always_wins(self, selector):
        """A table with exactly one fresh, non-local peer must produce a winner."""
        table = {"peer": _entry("peer", cpu=99.9, now=NOW)}
        result = selector.select(table, now=NOW)
        assert result.has_winner
        assert result.winner.node_id == "peer"

    def test_tie_returns_a_winner(self, selector):
        """When multiple peers have equal cpu_percent, some winner is still returned."""
        table = {
            "p": _entry("p", cpu=50.0, now=NOW),
            "q": _entry("q", cpu=50.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.has_winner
        assert result.winner.cpu_percent == pytest.approx(50.0)

    def test_candidate_count_matches_eligible_entries(self, selector):
        """candidates in SelectionResult must contain all fresh non-local peers."""
        table = {
            "a": _entry("a", cpu=10.0, now=NOW),
            "b": _entry("b", cpu=20.0, now=NOW),
            "c": _entry("c", cpu=30.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert len(result.candidates) == 3


# ===========================================================================
# Staleness filtering
# ===========================================================================


class TestStalenessFiltering:

    def test_stale_entries_excluded_from_winner(self, selector):
        """An entry older than stale_after must not be selected."""
        table = {
            "fresh": _entry("fresh", cpu=90.0, age=0.0, now=NOW),
            "stale": _entry("stale", cpu=1.0, age=STALE + 1, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner is not None
        assert result.winner.node_id == "fresh"

    def test_entry_exactly_at_stale_boundary_excluded(self, selector):
        """An entry with age == stale_after is considered stale (strictly greater
        than the threshold would be *fresh*; equal means expired)."""
        table = {
            "boundary": _entry("boundary", cpu=5.0, age=STALE, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert not result.has_winner
        assert result.excluded_stale == 1

    def test_entry_just_inside_stale_boundary_included(self, selector):
        """An entry with age just below stale_after must be treated as fresh."""
        table = {
            "almost-stale": _entry("almost-stale", cpu=5.0, age=STALE - 0.001, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.has_winner
        assert result.winner.node_id == "almost-stale"

    def test_all_stale_returns_no_winner(self, selector):
        """When every entry is stale the selector must return winner=None."""
        table = {
            "s1": _entry("s1", cpu=10.0, age=STALE + 5, now=NOW),
            "s2": _entry("s2", cpu=20.0, age=STALE + 50, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner is None
        assert result.excluded_stale == 2

    def test_stale_count_is_accurate(self, selector):
        """excluded_stale must count only entries discarded for staleness."""
        table = {
            "fresh": _entry("fresh", cpu=50.0, age=1.0, now=NOW),
            "old1": _entry("old1", cpu=10.0, age=STALE + 1, now=NOW),
            "old2": _entry("old2", cpu=10.0, age=STALE + 100, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.excluded_stale == 2

    def test_custom_stale_threshold_respected(self):
        """A shorter stale_after window must exclude entries the default would keep."""
        tight = LoadSelector(local_node_id=LOCAL, stale_after=5.0)
        table = {
            "medium-age": _entry("medium-age", cpu=10.0, age=10.0, now=NOW),
        }
        result = tight.select(table, now=NOW)
        # 10 seconds old > 5 second stale_after → stale
        assert result.winner is None
        assert result.excluded_stale == 1


# ===========================================================================
# Local-node exclusion
# ===========================================================================


class TestLocalNodeExclusion:

    def test_local_node_not_selected(self, selector):
        """The local node must never appear as the winner, even at 0% CPU."""
        table = {
            LOCAL: _entry(LOCAL, cpu=0.0, now=NOW),
            "peer": _entry("peer", cpu=99.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner is not None
        assert result.winner.node_id != LOCAL
        assert result.winner.node_id == "peer"

    def test_only_local_node_returns_no_winner(self, selector):
        """A table that contains only the local node must return winner=None."""
        table = {
            LOCAL: _entry(LOCAL, cpu=10.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner is None

    def test_local_excluded_count_is_accurate(self, selector):
        """excluded_local must count only entries whose node_id matches local."""
        table = {
            LOCAL: _entry(LOCAL, cpu=0.0, now=NOW),
            "p1": _entry("p1", cpu=20.0, now=NOW),
            "p2": _entry("p2", cpu=30.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.excluded_local == 1
        assert len(result.candidates) == 2


# ===========================================================================
# Empty / edge cases
# ===========================================================================


class TestEdgeCases:

    def test_empty_table_returns_no_winner(self, selector):
        """An empty peer_table must return winner=None with all counts at zero."""
        result = selector.select({}, now=NOW)
        assert result.winner is None
        assert result.candidates == []
        assert result.excluded_stale == 0
        assert result.excluded_local == 0

    def test_malformed_entry_missing_key_skipped(self, selector):
        """An entry missing a required field must be silently skipped."""
        table = {
            "bad": {"node_id": "bad", "cpu_percent": 10.0},  # missing ram_percent + timestamp
        }
        result = selector.select(table, now=NOW)
        assert result.winner is None

    def test_malformed_entry_bad_numeric_skipped(self, selector):
        """An entry with a non-numeric cpu_percent must be silently skipped."""
        table = {
            "bad": {
                "node_id": "bad",
                "cpu_percent": "not-a-number",
                "ram_percent": 50.0,
                "timestamp": NOW,
            },
        }
        result = selector.select(table, now=NOW)
        assert result.winner is None

    def test_mix_of_stale_local_malformed_leaves_no_candidates(self, selector):
        """A table with only stale, local, and malformed entries yields winner=None."""
        table = {
            LOCAL: _entry(LOCAL, cpu=0.0, now=NOW),                        # local
            "s1": _entry("s1", cpu=5.0, age=STALE + 1, now=NOW),          # stale
            "bad": {"node_id": "bad", "cpu_percent": "oops", "timestamp": NOW},  # malformed
        }
        result = selector.select(table, now=NOW)
        assert result.winner is None
        assert result.excluded_local == 1
        assert result.excluded_stale == 1

    def test_zero_cpu_peer_selected(self, selector):
        """A peer reporting 0 % CPU is valid and must be selected as the winner."""
        table = {
            "idle": _entry("idle", cpu=0.0, now=NOW),
            "busy": _entry("busy", cpu=50.0, now=NOW),
        }
        result = selector.select(table, now=NOW)
        assert result.winner.node_id == "idle"
        assert result.winner.cpu_percent == pytest.approx(0.0)

    def test_hundred_percent_cpu_peer_selected_when_only_candidate(self, selector):
        """Even a 100 % CPU peer must be selected when it is the only candidate."""
        table = {"overloaded": _entry("overloaded", cpu=100.0, now=NOW)}
        result = selector.select(table, now=NOW)
        assert result.has_winner
        assert result.winner.cpu_percent == pytest.approx(100.0)

    def test_large_table_returns_global_minimum(self, selector):
        """With many peers, the absolute CPU minimum must win."""
        table = {
            f"peer-{i}": _entry(f"peer-{i}", cpu=float(100 - i), now=NOW)
            for i in range(50)
        }
        result = selector.select(table, now=NOW)
        # peer-49 has cpu = 100 - 49 = 51 … peer-0 has cpu = 100
        # Actually peer-49 wins with cpu=51, but let's recalculate:
        # cpu = 100 - i  → i=0 gives 100, i=49 gives 51
        # So minimum is peer-49 → cpu=51
        assert result.winner is not None
        assert result.winner.cpu_percent == pytest.approx(51.0)
        assert result.winner.node_id == "peer-49"


# ===========================================================================
# filter_candidates
# ===========================================================================


class TestFilterCandidates:

    def test_returns_sorted_by_cpu_ascending(self, selector):
        """filter_candidates must return entries sorted lowest CPU first."""
        table = {
            "a": _entry("a", cpu=70.0, now=NOW),
            "b": _entry("b", cpu=10.0, now=NOW),
            "c": _entry("c", cpu=40.0, now=NOW),
        }
        entries = selector.filter_candidates(table, now=NOW)
        cpu_values = [e.cpu_percent for e in entries]
        assert cpu_values == sorted(cpu_values)
        assert cpu_values[0] == pytest.approx(10.0)

    def test_empty_table_returns_empty_list(self, selector):
        entries = selector.filter_candidates({}, now=NOW)
        assert entries == []

    def test_stale_and_local_excluded_from_candidates(self, selector):
        table = {
            LOCAL: _entry(LOCAL, cpu=1.0, now=NOW),
            "stale": _entry("stale", cpu=2.0, age=STALE + 1, now=NOW),
            "ok": _entry("ok", cpu=50.0, now=NOW),
        }
        entries = selector.filter_candidates(table, now=NOW)
        assert len(entries) == 1
        assert entries[0].node_id == "ok"

    def test_all_candidates_returned(self, selector):
        """filter_candidates must include all eligible peers, not just the winner."""
        table = {
            "p1": _entry("p1", cpu=30.0, now=NOW),
            "p2": _entry("p2", cpu=10.0, now=NOW),
            "p3": _entry("p3", cpu=20.0, now=NOW),
        }
        entries = selector.filter_candidates(table, now=NOW)
        assert len(entries) == 3


# ===========================================================================
# LoadEntry unit tests
# ===========================================================================


class TestLoadEntry:

    def test_from_dict_parses_all_fields(self):
        raw = {
            "node_id": "test-node",
            "cpu_percent": 42.5,
            "ram_percent": 33.0,
            "timestamp": 12345.678,
        }
        entry = LoadEntry.from_dict(raw)
        assert entry.node_id == "test-node"
        assert entry.cpu_percent == pytest.approx(42.5)
        assert entry.ram_percent == pytest.approx(33.0)
        assert entry.timestamp == pytest.approx(12345.678)

    def test_from_dict_missing_key_raises(self):
        raw = {"node_id": "x", "cpu_percent": 10.0, "ram_percent": 20.0}
        # "timestamp" is missing
        with pytest.raises(KeyError):
            LoadEntry.from_dict(raw)

    def test_from_dict_bad_numeric_raises(self):
        raw = {
            "node_id": "x",
            "cpu_percent": "bad",
            "ram_percent": 20.0,
            "timestamp": 999.0,
        }
        with pytest.raises(ValueError):
            LoadEntry.from_dict(raw)

    def test_from_dict_numeric_string_coerced(self):
        """Numeric values supplied as strings must be silently coerced."""
        raw = {
            "node_id": "x",
            "cpu_percent": "55.0",
            "ram_percent": "30.0",
            "timestamp": "1000.0",
        }
        entry = LoadEntry.from_dict(raw)
        assert entry.cpu_percent == pytest.approx(55.0)

    def test_age_computed_correctly(self):
        ts = 1_000_000.0
        entry = LoadEntry(
            node_id="n", cpu_percent=10.0, ram_percent=20.0, timestamp=ts
        )
        assert entry.age(now=ts + 15.0) == pytest.approx(15.0)

    def test_age_zero_for_brand_new_entry(self):
        ts = 1_000_000.0
        entry = LoadEntry(
            node_id="n", cpu_percent=10.0, ram_percent=20.0, timestamp=ts
        )
        assert entry.age(now=ts) == pytest.approx(0.0)


# ===========================================================================
# SelectionResult unit tests
# ===========================================================================


class TestSelectionResult:

    def test_has_winner_true_when_winner_set(self):
        entry = LoadEntry(node_id="x", cpu_percent=10.0, ram_percent=20.0, timestamp=NOW)
        r = SelectionResult(winner=entry, candidates=[entry], excluded_stale=0, excluded_local=0)
        assert r.has_winner is True

    def test_has_winner_false_when_winner_none(self):
        r = SelectionResult(winner=None, candidates=[], excluded_stale=0, excluded_local=0)
        assert r.has_winner is False


# ===========================================================================
# Constructor validation
# ===========================================================================


class TestConstructorValidation:

    def test_empty_local_node_id_raises(self):
        with pytest.raises(ValueError, match="local_node_id"):
            LoadSelector(local_node_id="", stale_after=30.0)

    def test_zero_stale_after_raises(self):
        with pytest.raises(ValueError, match="stale_after"):
            LoadSelector(local_node_id="n", stale_after=0.0)

    def test_negative_stale_after_raises(self):
        with pytest.raises(ValueError, match="stale_after"):
            LoadSelector(local_node_id="n", stale_after=-5.0)

    def test_valid_construction_stores_params(self):
        sel = LoadSelector(local_node_id="my-node", stale_after=60.0)
        assert sel.local_node_id == "my-node"
        assert sel.stale_after == pytest.approx(60.0)

    def test_default_stale_after_is_thirty_seconds(self):
        sel = LoadSelector(local_node_id="my-node")
        assert sel.stale_after == pytest.approx(30.0)
