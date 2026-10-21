"""Trip-clustered bootstrap: correct point estimate, honest (wider) intervals, determinism."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from movemelbourne.analysis.bootstrap import cluster_bootstrap_ci


def _trips(on_time_trips: int, late_trips: int, stops: int = 20) -> pd.DataFrame:
    rows = [{"route": "r", "n_observed": stops, "n_on_time": stops}] * on_time_trips
    rows += [{"route": "r", "n_observed": stops, "n_on_time": 0}] * late_trips
    return pd.DataFrame(rows)


def test_point_estimate_is_pooled_ratio():
    out = cluster_bootstrap_ci(_trips(8, 2), group_col="route", resamples=500)
    assert out.loc[0, "otp_boot_pct"] == pytest.approx(80.0)
    assert out.loc[0, "otp_ci_low_pct"] < 80 < out.loc[0, "otp_ci_high_pct"]


def test_clustered_interval_wider_than_naive_binomial():
    # 10 trips x 20 stops, whole trips on time or late: effective n is 10, not 200.
    out = cluster_bootstrap_ci(_trips(8, 2), group_col="route", resamples=2000)
    width = out.loc[0, "otp_ci_high_pct"] - out.loc[0, "otp_ci_low_pct"]
    naive = 2 * 1.96 * np.sqrt(0.8 * 0.2 / 200) * 100
    assert width > 2 * naive


def test_deterministic_with_seed_and_single_trip_has_no_interval():
    a = cluster_bootstrap_ci(_trips(5, 5), group_col="route", seed=7)
    b = cluster_bootstrap_ci(_trips(5, 5), group_col="route", seed=7)
    pd.testing.assert_frame_equal(a, b)
    one = cluster_bootstrap_ci(_trips(1, 0), group_col="route")
    assert np.isnan(one.loc[0, "otp_ci_low_pct"])
