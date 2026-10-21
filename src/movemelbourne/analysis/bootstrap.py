"""Trip-clustered bootstrap confidence intervals for proxy OTP (METHODOLOGY §4).

Stop events on the same trip are not independent: a tram that is late at stop 5 is usually late
at stop 6. Treating every stop event as an independent Bernoulli trial (as a plain binomial or
Wilson interval does) makes intervals far too narrow. Resampling whole TRIPS with replacement
keeps that within-trip correlation, so the interval reflects how many independent runs we saw.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cluster_bootstrap_ci(
    trip_counts: pd.DataFrame,
    *,
    group_col: str,
    n_col: str = "n_observed",
    k_col: str = "n_on_time",
    resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> pd.DataFrame:
    """Percentile CI for sum(k)/sum(n) per group, resampling rows (trips) within each group.

    ``trip_counts`` has one row per (group, trip) with the trip's observed and on-time counts.
    Returns one row per group: point estimate, CI bounds (0-100) and the number of trips.
    """
    rng = np.random.default_rng(seed)
    out = []
    for group, g in trip_counts.groupby(group_col, sort=True):
        n = g[n_col].to_numpy(dtype=float)
        k = g[k_col].to_numpy(dtype=float)
        m = len(g)
        point = k.sum() / n.sum() if n.sum() else np.nan
        if m < 2 or not n.sum():
            low = high = np.nan
        else:
            # Multinomial weights == drawing m trips with replacement, vectorised.
            weights = rng.multinomial(m, np.full(m, 1 / m), size=resamples)
            denom = weights @ n
            ratios = np.divide(weights @ k, denom, out=np.full(resamples, np.nan), where=denom > 0)
            low, high = np.nanquantile(ratios, [alpha / 2, 1 - alpha / 2])
        out.append(
            {
                group_col: group,
                "otp_boot_pct": 100 * point,
                "otp_ci_low_pct": 100 * low,
                "otp_ci_high_pct": 100 * high,
                "n_trips": m,
            }
        )
    return pd.DataFrame(out)
