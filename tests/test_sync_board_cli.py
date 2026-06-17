"""Unit tests for sync_board_cli._filter_jobs and _split_filter_arg.

Covers Fix 1: the filter argument parser must accept both ',' and ';'
as separators so that agents following the skill's semicolon examples
and agents following the argparse help-text comma examples both work.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from career_intelligence.tools.sync_board_cli import _filter_jobs, _split_filter_arg


def _job(title: str, location: str) -> SimpleNamespace:
    return SimpleNamespace(title=title, location=location)


# ---------------------------------------------------------------------------
# _split_filter_arg
# ---------------------------------------------------------------------------


class TestSplitFilterArg:
    def test_comma_separator(self) -> None:
        assert _split_filter_arg("New York,Jersey City") == ["new york", "jersey city"]

    def test_semicolon_separator(self) -> None:
        assert _split_filter_arg("New York;Jersey City") == ["new york", "jersey city"]

    def test_mixed_separator(self) -> None:
        assert _split_filter_arg("New York;NYC,Jersey City") == [
            "new york", "nyc", "jersey city"
        ]

    def test_strips_whitespace(self) -> None:
        assert _split_filter_arg(" New York ; Jersey City ") == ["new york", "jersey city"]

    def test_empty_string_returns_empty(self) -> None:
        assert _split_filter_arg("") == []

    def test_single_value(self) -> None:
        assert _split_filter_arg("New York") == ["new york"]

    def test_lowercases(self) -> None:
        assert _split_filter_arg("New YORK") == ["new york"]


# ---------------------------------------------------------------------------
# _filter_jobs — location filter
# ---------------------------------------------------------------------------


class TestFilterJobsLocationSeparators:
    def _jobs(self) -> list:
        return [
            _job("Market Risk Analyst", "New York, NY"),
            _job("Valuation Analyst", "Jersey City, NJ"),
            _job("Software Engineer", "London"),
        ]

    def test_comma_location_filter_keeps_ny_jc(self) -> None:
        kept, stats = _filter_jobs(self._jobs(), "New York,Jersey City", "", "")
        assert len(kept) == 2
        assert stats["dropped_location"] == 1

    def test_semicolon_location_filter_keeps_ny_jc(self) -> None:
        """Semicolon separator (as emitted by agent following old skill examples)
        must behave identically to comma separator after Fix 1."""
        kept, stats = _filter_jobs(self._jobs(), "New York;Jersey City", "", "")
        assert len(kept) == 2
        assert stats["dropped_location"] == 1

    def test_mixed_location_filter(self) -> None:
        kept, stats = _filter_jobs(self._jobs(), "New York;NYC,Jersey City", "", "")
        assert len(kept) == 2

    def test_single_location_comma_form(self) -> None:
        kept, _ = _filter_jobs(self._jobs(), "New York", "", "")
        assert len(kept) == 1

    def test_no_location_filter_keeps_all(self) -> None:
        kept, _ = _filter_jobs(self._jobs(), "", "", "")
        assert len(kept) == 3


# ---------------------------------------------------------------------------
# _filter_jobs — title_keywords separator
# ---------------------------------------------------------------------------


class TestFilterJobsTitleSeparators:
    def _jobs(self) -> list:
        return [
            _job("Market Risk Analyst", "New York"),
            _job("Valuation Control Analyst", "New York"),
            _job("Product Control Analyst", "New York"),
            _job("Software Engineer", "New York"),
        ]

    def test_comma_title_keywords(self) -> None:
        kept, _ = _filter_jobs(self._jobs(), "", "market risk,valuation,product control", "")
        assert len(kept) == 3

    def test_semicolon_title_keywords(self) -> None:
        kept, _ = _filter_jobs(self._jobs(), "", "market risk;valuation;product control", "")
        assert len(kept) == 3

    def test_exclude_titles_semicolon(self) -> None:
        kept, stats = _filter_jobs(self._jobs(), "", "", "software;intern")
        assert len(kept) == 3
        assert stats["dropped_title_excluded"] == 1


# ---------------------------------------------------------------------------
# Regression: old comma-only calls still work
# ---------------------------------------------------------------------------


class TestFilterJobsBackwardCompatibility:
    def test_original_schonfeld_scenario_with_commas(self) -> None:
        """The original bug: semicolons caused 0 matches. With commas this was always fine;
        with fix 1 both work."""
        jobs = [
            _job("Exposure Management Analyst", "New York, NY"),
            _job("Market Risk Analyst", "Jersey City, NJ"),
            _job("Equity Risk Analyst", "Austin, TX"),
        ]
        kept_comma, _ = _filter_jobs(
            jobs,
            "New York,Jersey City",
            "exposure management,market risk,equity risk",
            "",
        )
        kept_semi, _ = _filter_jobs(
            jobs,
            "New York;Jersey City",
            "exposure management;market risk;equity risk",
            "",
        )
        assert len(kept_comma) == 2
        assert len(kept_semi) == 2
        assert kept_comma == kept_semi
