"""Page 7 - Data quality & method: coverage, collector health, method agreement, limitations."""

import plotly.graph_objects as go
import streamlit as st

from lib.common import (
    MODE_COLORS,
    MODE_LABELS,
    daily_axis,
    fmt_delay,
    fmt_pct,
    footer,
    load,
    manifest,
    page_header,
    style_fig,
)

cov = load("coverage_daily")
agree = load("inference_agreement")
page_header(
    "Data quality & method",
    "Every OTP figure on this site is paired with how much of "
    "the timetable we actually observed. This page shows the gaps.",
)

if not cov.empty:
    st.subheader("Coverage per service day")
    fig = go.Figure()
    for mode in cov["mode"].unique():
        d = cov[cov["mode"] == mode]
        fig.add_trace(
            go.Bar(
                x=d["service_date"],
                y=d["coverage_pct"],
                name=MODE_LABELS[mode],
                marker_color=MODE_COLORS[mode],
                customdata=d[
                    ["n_observed_in_scope", "n_in_scope_events", "n_collection_gap_events"]
                ].values,
                hovertemplate="%{x|%a %d %b}: %{y:.1f}%<br>%{customdata[0]:,} of "
                "%{customdata[1]:,} observed<br>%{customdata[2]:,} in "
                "collector gaps<extra></extra>",
            )
        )
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(title="Coverage (%)", range=[0, 100])
    daily_axis(fig)
    st.plotly_chart(style_fig(fig, 300), use_container_width=True)
    st.dataframe(
        cov[
            [
                "service_date",
                "mode",
                "coverage_pct",
                "n_in_scope_events",
                "n_observed_in_scope",
                "n_collection_gap_events",
                "n_unobserved_events",
                "n_cancelled_events",
                "trip_match_rate",
                "poll_success_pct",
                "collector_hours",
                "n_method_last_prediction",
                "n_method_vehicle_position",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

st.subheader("Observed-arrival method: self-check")
st.markdown(
    "The feeds publish **predictions**, not arrivals. An arrival is inferred from the last "
    "prediction captured within 2 minutes of the vehicle reaching the stop (primary), or from "
    "vehicle positions showing the vehicle stopped at the stop (fallback). Where both exist, "
    "they should agree:"
)
if not agree.empty:
    cols = st.columns(len(agree))
    for col, r in zip(cols, agree.itertuples(), strict=True):
        col.metric(
            f"{MODE_LABELS[r.mode]}: median gap between methods", fmt_delay(r.median_abs_diff_s)
        )
        col.caption(
            f"{fmt_pct(r.pct_within_60s)} within 60 s · on-time verdict flips for "
            f"{fmt_pct(r.pct_otp_verdict_flips)} · n = {r.n_both_methods:,}"
        )

st.subheader("Validation against official figures")
st.markdown(
    "Official monthly and daily punctuality is published by the Victorian Government. The "
    "official measure uses specific monitoring points (trams: 3 of 5 points per route), while "
    "MoveMelbourne measures at every observed stop and cannot see replacement buses, so a gap "
    "is expected. The comparison lives in `docs/validation.md` once the study period's official "
    "figures are published."
)

st.subheader("Known limitations")
st.markdown("""
- **Proxy metric.** Not the official punctuality measure; label every figure "proxy OTP".
- **Feed exclusions.** The metro trip-updates feed omits replacement buses, service deviations
  (skipped stops, diversions) and platform changes (DTP OpenAPI spec).
- **Inference uncertainty.** Arrivals are inferred from predictions sampled every 60 s; see the
  method agreement above.
- **Coverage gaps.** Collector restarts, GitHub Actions scheduling jitter and API outages leave
  gaps; those events count against coverage, never towards OTP.
- **Cancellations.** "No data" (a trip never appeared while we were polling) is reported
  separately from confirmed cancellations.
""")
m = manifest()
st.caption(f"Thresholds: {m.get('thresholds')} · study config: {m.get('study_window')}")
footer()
