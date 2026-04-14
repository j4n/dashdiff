"""
RED tests for null-vs-absent equivalence in lenient normalization.

In JSON, ``null`` and an absent key are semantically equivalent for most
Grafana fields (e.g. ``fieldConfig.defaults.thresholds.steps[0].value``
being ``null`` is identical to the key simply not being present).

Lenient mode (``strict=False``) should strip all null-valued keys from
every object in the normalized output so that a dashboard that has
``{"value": null}`` and one that omits ``"value"`` entirely produce
identical normalized output.

Strict mode (``strict=True``) must preserve null values so that auditors
can see exactly what the stored JSON contains.
"""

from __future__ import annotations

import pytest
from dashdiff.normalize import normalize


# ---------------------------------------------------------------------------
# Lenient mode: null keys are stripped
# ---------------------------------------------------------------------------

class TestLenientNullStripping:
    def test_top_level_null_key_removed(self):
        """A top-level null value must be absent from lenient output."""
        result = normalize({"title": "x", "description": None})
        assert "description" not in result

    def test_nested_null_key_removed(self):
        """Null values inside nested objects must be stripped."""
        result = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {"defaults": {"unit": None}},
            }]
        })
        assert "unit" not in result["panels"][0]["fieldConfig"]["defaults"]

    def test_deeply_nested_null_removed(self):
        """Null values several levels deep must be stripped."""
        result = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {
                    "defaults": {
                        "thresholds": {
                            "steps": [{"color": "green", "value": None}]
                        }
                    }
                },
            }]
        })
        step = result["panels"][0]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]
        assert "value" not in step

    def test_non_null_values_preserved(self):
        """Non-null values must not be removed."""
        result = normalize({"title": "x", "refresh": "5s", "schemaVersion": 36})
        assert result["refresh"] == "5s"
        assert result["schemaVersion"] == 36

    def test_false_value_preserved(self):
        """False is not null — must be kept."""
        result = normalize({"panels": [{"title": "P", "type": "stat", "transparent": False}]})
        assert result["panels"][0]["transparent"] is False

    def test_zero_value_preserved(self):
        """0 is not null — must be kept."""
        result = normalize({"panels": [{"title": "P", "type": "stat", "repeat": 0}]})
        assert result["panels"][0]["repeat"] == 0

    def test_empty_string_preserved(self):
        """Empty string is not null — must be kept."""
        result = normalize({"panels": [{"title": "P", "type": "stat", "description": ""}]})
        assert result["panels"][0]["description"] == ""

    def test_null_in_array_preserved(self):
        """Null *elements* inside arrays are not stripped (only dict keys)."""
        result = normalize({"panels": [{"title": "P", "type": "stat",
                                        "someList": [None, 1, 2]}]})
        assert result["panels"][0]["someList"] == [None, 1, 2]

    def test_null_vs_absent_produces_identical_output(self):
        """
        A dashboard with ``{"value": null}`` and one without ``"value"``
        must produce identical normalized output in lenient mode.
        """
        with_null = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {"defaults": {"thresholds": {
                    "steps": [{"color": "green", "value": None}]
                }}},
            }]
        })
        without_key = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {"defaults": {"thresholds": {
                    "steps": [{"color": "green"}]
                }}},
            }]
        })
        assert with_null == without_key

    def test_idempotent_after_null_stripping(self):
        """Normalizing a null-stripped result again must be a no-op."""
        dashboard = {
            "title": "x",
            "panels": [{"title": "P", "type": "stat", "description": None}],
        }
        first  = normalize(dashboard)
        second = normalize(first)
        assert first == second

    def test_multiple_null_keys_all_removed(self):
        """Multiple null keys at the same level must all be stripped."""
        result = normalize({
            "title": "x",
            "description": None,
            "uid": None,
            "timezone": "browser",
        })
        assert "description" not in result
        assert "uid" not in result
        assert result["timezone"] == "browser"


# ---------------------------------------------------------------------------
# Strict mode: null values are preserved
# ---------------------------------------------------------------------------

class TestStrictNullPreservation:
    def test_top_level_null_preserved_in_strict(self):
        """Strict mode must keep null values intact."""
        result = normalize({"title": "x", "description": None}, strict=True)
        assert "description" in result
        assert result["description"] is None

    def test_nested_null_preserved_in_strict(self):
        """Strict mode must keep nested null values intact."""
        result = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {"defaults": {"unit": None}},
            }]
        }, strict=True)
        assert result["panels"][0]["fieldConfig"]["defaults"]["unit"] is None

    def test_deeply_nested_null_preserved_in_strict(self):
        """Strict mode must keep deeply nested null values intact."""
        result = normalize({
            "panels": [{
                "title": "P", "type": "stat",
                "fieldConfig": {
                    "defaults": {
                        "thresholds": {
                            "steps": [{"color": "green", "value": None}]
                        }
                    }
                },
            }]
        }, strict=True)
        step = result["panels"][0]["fieldConfig"]["defaults"]["thresholds"]["steps"][0]
        assert "value" in step
        assert step["value"] is None

    def test_strict_null_vs_absent_differ(self):
        """
        In strict mode, ``{"value": null}`` and ``{}`` must NOT be equal
        after normalization — the null is preserved.
        """
        with_null = normalize({
            "panels": [{"title": "P", "type": "stat",
                        "fieldConfig": {"defaults": {"thresholds": {
                            "steps": [{"color": "green", "value": None}]
                        }}}}]
        }, strict=True)
        without_key = normalize({
            "panels": [{"title": "P", "type": "stat",
                        "fieldConfig": {"defaults": {"thresholds": {
                            "steps": [{"color": "green"}]
                        }}}}]
        }, strict=True)
        assert with_null != without_key
