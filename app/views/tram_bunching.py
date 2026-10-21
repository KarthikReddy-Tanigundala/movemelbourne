"""Page 5 - Tram bunching and headway regularity."""

import plotly.graph_objects as go
import streamlit as st

from lib.common import MODE_COLORS, MUTED, footer, load, min_sample, page_header, style_fig

hw = load("headways")
page_header(
    "Tram bunching",
    "For frequent trams, passengers turn up without a timetable, so evenness matters more than "
    "punctuality. Bunching = the next tram arrives in under half the scheduled gap.",
)
if hw.empty:
    st.info(
        "No headway data exported yet (needs consecutive observed trams at measurement points)."
    )
    st.stop()

min_n = min_sample()
by_route = (
    hw.assign(
        b=hw["bunching_rate_pct"] * hw["n_pairs"],
        e=hw["excess_wait_s"] * hw["n_pairs"],
        cv=hw["headway_cv"] * hw["n_pairs"],
    )
    .groupby("route_display_name")[["b", "e", "cv", "n_pairs"]]
    .sum()
    .reset_index()
)
by_route["bunching_rate_pct"] = by_route["b"] / by_route["n_pairs"]
by_route["excess_wait_s"] = by_route["e"] / by_route["n_pairs"]
by_route["headway_cv"] = by_route["cv"] / by_route["n_pairs"]
by_route["ok"] = by_route["n_pairs"] >= min_n
by_route = by_route.sort_values("bunching_rate_pct")

c1, c2 = st.columns(2)
with c1:
    fig = go.Figure(
        go.Bar(
            x=by_route["bunching_rate_pct"],
            y=by_route["route_display_name"],
            orientation="h",
            marker_color=[MODE_COLORS["tram"] if ok else MUTED for ok in by_route["ok"]],
            customdata=by_route["n_pairs"],
            hovertemplate="%{y}: %{x:.1f}% of pairs bunched (n=%{customdata})<extra></extra>",
        )
    )
    fig.update_layout(title="Bunching rate")
    fig.update_xaxes(title="% of consecutive tram pairs bunched")
    st.plotly_chart(style_fig(fig, 120 + 40 * len(by_route)), use_container_width=True)
with c2:
    fig = go.Figure(
        go.Bar(
            x=by_route["excess_wait_s"] / 60,
            y=by_route["route_display_name"],
            orientation="h",
            marker_color=[MODE_COLORS["tram"] if ok else MUTED for ok in by_route["ok"]],
            hovertemplate="%{y}: %{x:.1f} min extra average wait<extra></extra>",
        )
    )
    fig.update_layout(title="Excess wait time")
    fig.update_xaxes(title="Extra average wait vs timetable (minutes)")
    st.plotly_chart(style_fig(fig, 120 + 40 * len(by_route)), use_container_width=True)

st.caption(
    f"Grey bars: fewer than {min_n} observed pairs. Excess wait = E[h²]/2E[h] of actual "
    "headways minus the same for scheduled headways: the extra time an average passenger "
    "arriving at random waits because trams are uneven or late. Measured at three proxy "
    "points per route (stops nearest 25/50/75% along the trip)."
)
with st.expander("By time band (table view)"):
    st.dataframe(
        hw[
            [
                "route_display_name",
                "direction_id",
                "time_band",
                "service_date",
                "n_pairs",
                "bunching_rate_pct",
                "headway_cv",
                "excess_wait_s",
                "mean_scheduled_headway_s",
                "mean_actual_headway_s",
            ]
        ].sort_values(["route_display_name", "service_date"]),
        hide_index=True,
        use_container_width=True,
    )
footer()
