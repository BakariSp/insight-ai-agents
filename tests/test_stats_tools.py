"""Tests for stats tools."""

import pytest
from tools.stats_tools import calculate_stats, compare_performance


class TestCalculateStats:
    """Tests for calculate_stats function."""

    def test_empty_data(self):
        """Should return error for empty data."""
        result = calculate_stats([])
        assert "error" in result

    def test_basic_stats(self):
        """Should calculate basic statistics."""
        data = [60, 70, 80, 90, 100]
        result = calculate_stats(data)

        assert result["count"] == 5
        assert result["mean"] == 80.0
        assert result["median"] == 80.0
        assert result["min"] == 60.0
        assert result["max"] == 100.0
        assert "stddev" in result

    def test_distribution(self):
        """Should calculate score distribution."""
        data = [35, 45, 55, 65, 75, 85, 95]
        result = calculate_stats(data)

        assert "distribution" in result
        assert "labels" in result["distribution"]
        assert "counts" in result["distribution"]
        assert len(result["distribution"]["labels"]) == 7

    def test_percentiles(self):
        """Should calculate percentiles."""
        data = list(range(1, 101))  # 1 to 100
        result = calculate_stats(data)

        assert "percentiles" in result
        assert result["percentiles"]["p25"] == pytest.approx(25.75, rel=0.1)
        assert result["percentiles"]["p50"] == pytest.approx(50.5, rel=0.1)
        assert result["percentiles"]["p75"] == pytest.approx(75.25, rel=0.1)
        assert result["percentiles"]["p90"] == pytest.approx(90.1, rel=0.1)

    def test_summary_field(self):
        """Should include summary field for kpi_grid compatibility."""
        data = [60, 70, 80, 90, 100]
        result = calculate_stats(data)

        assert "summary" in result
        assert isinstance(result["summary"], list)
        assert len(result["summary"]) == 5

        # Check summary structure
        labels = {item["label"]: item for item in result["summary"]}
        assert "平均分" in labels
        assert "最高分" in labels
        assert "最低分" in labels
        assert "标准差" in labels
        assert "样本数" in labels

        # Check values
        assert labels["平均分"]["value"] == 80.0
        assert labels["最高分"]["value"] == 100.0
        assert labels["最低分"]["value"] == 60.0
        assert labels["样本数"]["value"] == 5

    def test_specific_metrics(self):
        """Should only compute requested metrics."""
        data = [60, 70, 80]
        result = calculate_stats(data, metrics=["mean", "count"])

        assert "mean" in result
        assert "count" in result
        # When mean is requested, summary should also be included
        assert "summary" in result
        # Other metrics should still be absent
        assert "percentiles" not in result
        assert "distribution" not in result


class TestComparePerformance:
    """Tests for compare_performance function."""

    def test_empty_groups(self):
        """Should return error for empty groups."""
        result = compare_performance([], [1, 2, 3])
        assert "error" in result

        result = compare_performance([1, 2, 3], [])
        assert "error" in result

    def test_comparison(self):
        """Should compare two groups."""
        group_a = [80, 85, 90]
        group_b = [70, 75, 80]

        result = compare_performance(group_a, group_b)

        assert "group_a" in result
        assert "group_b" in result
        assert "difference" in result
        assert "summary" in result

        # Group A should have higher mean
        assert result["difference"]["mean"] > 0
