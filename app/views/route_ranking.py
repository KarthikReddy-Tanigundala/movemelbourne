"""Page 2 - Route reliability ranking by the lower bound of a trip-clustered bootstrap CI."""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from lib.common import (
    MODE_COLORS,
    MODE_LABELS,
    MUTED,
    fmt_delay,
    fmt_pct,
    footer,
    load,
    min_sample,
    mode_filter,
    page_header,
    style_fig,
)

routes = load("route_summary")
page_header(
    "Route reliability",
    "Routes are ranked by the LOWER end of their 95% confidence interval, so a route only ranks "
    "high if we are confident it is punctual, not because a few lucky trips were observed.",
)
if routes.empty:
    st.info("No route data exported yet.")
    st.stop()

modes = mode_filter("rank_modes")
for mode in modes:
    r = routes[routes["mode"] == mode].copy()
    if r.empty:
        continue
    r["label"] = r["route_display_name"]
    r = r.sort_values(["is_sample_sufficient", "otp_ci_low_pct", "otp_pct"], ascending=True)
    ok = r["is_sample_sufficient"].to_numpy()
    colour = MODE_COLORS[mode]
    st.subheader(MODE_LABELS[mode])
    fig = go.Figure(
        go.Scatter(
            x=r["otp_pct"],
            y=r["label"],
            mode="markers",
            marker={
                "size": 10,
                "color": np.where(ok, colour, "rgba(0,0,0,0)"),
                "line": {"color": np.where(ok, colour, MUTED), "width": 2},
            },
            error_x={
                "type": "data",
                "symmetric": False,
                "thickness": 2,
                "width": 0,
                "array": (r["otp_ci_high_pct"] - r["otp_pct"]).fillna(0),
                "arrayminus": (r["otp_pct"] - r["otp_ci_low_pct"]).fillna(0),
                "color": colour,
            },
            customdata=np.stack(
                [
                    r["n_observed"],
                    r["n_trips"],
                    r["otp_ci_low_pct"],
                    r["otp_ci_high_pct"],
                    r["coverage_pct"],
                ],
                axis=-1,
            ),
            hovertemplate="<b>%{y}</b><br>Proxy OTP %{x:.1f}% (95% CI %{customdata[2]:.1f}–"
            "%{customdata[3]:.1f})<br>%{customdata[0]:,} stop events on "
            "%{customdata[1]:,} trips<br>coverage %{customdata[4]:.0f}%<extra></extra>",
        )
    )
    fig.update_xaxes(title="Proxy OTP (%) with trip-clustered bootstrap 95% CI", range=[0, 101])
    fig.update_yaxes(title=None)
    st.plotly_chart(style_fig(fig, 120 + 34 * len(r)), use_container_width=True)
    table = r.sort_values("rank_by_ci_low")[
        [
            "rank_by_ci_low",
            "route_display_name",
            "otp_pct",
            "otp_ci_low_pct",
            "otp_ci_high_pct",
            "p90_delay_s",
            "major_late_pct",
            "reliability_pct",
            "n_trips_cancelled",
            "coverage_pct",
            "n_observed",
            "n_trips",
        ]
    ].copy()
    table["p90_delay"] = table.pop("p90_delay_s").map(fmt_delay)
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "rank_by_ci_low": st.column_config.NumberColumn("Rank", format="%d"),
            "route_display_name": "Route",
            "otp_pct": st.column_config.NumberColumn("Proxy OTP %", format="%.1f"),
            "otp_ci_low_pct": st.column_config.NumberColumn("CI low", format="%.1f"),
            "otp_ci_high_pct": st.column_config.NumberColumn("CI high", format="%.1f"),
            "major_late_pct": st.column_config.NumberColumn(">15 min late %", format="%.1f"),
            "reliability_pct": st.column_config.NumberColumn("Reliability %", format="%.1f"),
            "n_trips_cancelled": "Cancelled trips",
            "coverage_pct": st.column_config.NumberColumn("Coverage %", format="%.0f"),
            "n_observed": "Stop events",
            "n_trips": "Trips",
            "p90_delay": "P90 delay",
        },
    )

st.caption(
    f"Hollow grey markers and blank ranks: fewer than {min_sample()} observed stop events. "
    "The CI resamples whole trips, because stop events on one trip share their delay; a "
    "per-stop binomial interval would be falsely narrow. Lowest-ranked: "
    + ", ".join(
        f"{MODE_LABELS[m]} {fmt_pct(v)}"
        for m, v in routes.groupby("mode")["otp_ci_low_pct"].min().items()
    )
    + " (CI low)."
)
footer()
