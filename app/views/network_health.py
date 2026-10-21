"""Page 1 - Network health: proxy OTP and reliability per mode against contract targets."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib.common import (
    MODE_COLORS,
    MODE_LABELS,
    MUTED,
    daily_axis,
    fmt_delay,
    fmt_pct,
    footer,
    load,
    min_sample,
    page_header,
    status_of,
    style_fig,
)

daily = load("network_daily")
hist = load("delay_histogram")


def p90_from_histogram(mode: str) -> float | None:
    """Approximate P90 delay from the 30-second delay histogram (labelled ≈ on screen)."""
    h = hist[hist["mode"] == mode].sort_values("delay_bin_s")
    if h.empty:
        return None
    cum = h["n"].cumsum() / h["n"].sum()
    return float(h.loc[cum >= 0.9, "delay_bin_s"].iloc[0]) + 15  # bin midpoint


summary = (
    (
        daily.groupby("mode")
        .agg(
            n_observed=("n_observed", "sum"),
            n_on_time=("n_on_time", "sum"),
            n_in_scope=("n_in_scope", "sum"),
            n_trips_eligible=("n_trips_eligible", "sum"),
            n_trips_cancelled=("n_trips_cancelled", "sum"),
            target_otp=("target_punctuality_pct", "first"),
            target_rel=("target_reliability_pct", "first"),
            days=("service_date", "nunique"),
        )
        .reset_index()
    )
    if not daily.empty
    else pd.DataFrame()
)
if not summary.empty:
    summary["otp_pct"] = 100 * summary["n_on_time"] / summary["n_observed"]
    summary["coverage_pct"] = 100 * summary["n_observed"] / summary["n_in_scope"]
    summary["reliability_pct"] = np.where(
        summary["n_trips_eligible"] > 0,
        100 * (1 - summary["n_trips_cancelled"] / summary["n_trips_eligible"].clip(lower=1)),
        np.nan,
    )

bluf = None
if not summary.empty:
    parts = [
        f"{MODE_LABELS[r.mode]} proxy OTP {fmt_pct(r.otp_pct)} vs {r.target_otp:.0f}% target "
        f"({fmt_pct(r.coverage_pct, 0)} of collectable stop events observed)"
        for r in summary.itertuples()
    ]
    bluf = "; ".join(parts) + "."
page_header("Network health", bluf)

if summary.empty:
    st.info("No data exported yet. Run `scripts/run_pipeline.py` then `scripts/export_gold.py`.")
    st.stop()

for r in summary.itertuples():
    st.subheader(MODE_LABELS[r.mode])
    c1, c2, c3, c4 = st.columns(4)
    colour, icon, label = status_of(r.otp_pct, r.target_otp)
    c1.metric(
        "Proxy OTP",
        fmt_pct(r.otp_pct),
        delta=f"{r.otp_pct - r.target_otp:+.1f} pts vs {r.target_otp:.0f}% target",
        delta_color="normal",
    )
    c1.markdown(f"<span style='color:{colour}'>{icon}</span> {label}", unsafe_allow_html=True)
    rel_colour, rel_icon, rel_label = status_of(r.reliability_pct, r.target_rel)
    c2.metric(
        "Reliability (trips run)",
        fmt_pct(r.reliability_pct),
        help="1 − confirmed cancelled ÷ scheduled trips fully inside collected time.",
    )
    c2.markdown(
        f"<span style='color:{rel_colour}'>{rel_icon}</span> {rel_label} "
        f"({int(r.n_trips_eligible):,} trips)",
        unsafe_allow_html=True,
    )
    c3.metric(
        "Coverage",
        fmt_pct(r.coverage_pct),
        help="Observed ÷ collectable scheduled stop events. Every OTP figure is paired "
        "with this so a high OTP on thin data is visible as such.",
    )
    c3.caption(f"{int(r.n_observed):,} observed stop events over {r.days} day(s)")
    c4.metric(
        "P90 delay (≈)",
        fmt_delay(p90_from_histogram(r.mode)),
        help="90% of observed arrivals were no later than this (from 30 s bins).",
    )

st.subheader("Daily proxy OTP against target")
st.caption(
    f"Hollow grey markers: fewer than {min_sample()} observed stop events that day "
    "(shown, not trusted). Dashed line: operator contract target."
)
cols = st.columns(len(summary))
for col, r in zip(cols, summary.itertuples(), strict=True):
    d = daily[daily["mode"] == r.mode].sort_values("service_date")
    ok = d["is_sample_sufficient"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=d["service_date"],
            y=d["otp_pct"],
            mode="lines+markers",
            name=MODE_LABELS[r.mode],
            line={"color": MODE_COLORS[r.mode], "width": 2},
            marker={
                "size": 8,
                "color": np.where(ok, MODE_COLORS[r.mode], "rgba(0,0,0,0)"),
                "line": {"color": np.where(ok, MODE_COLORS[r.mode], MUTED), "width": 2},
            },
            customdata=np.stack([d["n_observed"], d["coverage_pct"], d["day_type"]], axis=-1),
            hovertemplate="%{x|%a %d %b}<br>OTP %{y:.1f}%<br>n = %{customdata[0]:,}"
            "<br>coverage %{customdata[1]:.0f}%<br>%{customdata[2]}<extra></extra>",
        )
    )
    fig.add_hline(
        y=r.target_otp,
        line_dash="dash",
        line_color=MUTED,
        annotation_text=f"Target {r.target_otp:.0f}%",
        annotation_position="bottom right",
    )
    fig.update_yaxes(title="Proxy OTP (%)", range=[max(0, d["otp_pct"].min() - 10), 100.5])
    fig.update_layout(title=MODE_LABELS[r.mode], showlegend=False)
    daily_axis(fig)
    col.plotly_chart(style_fig(fig, 320), use_container_width=True)

st.subheader("Delay distribution")
fig = go.Figure()
for mode in summary["mode"]:
    h = hist[hist["mode"] == mode]
    fig.add_trace(
        go.Bar(
            x=h["delay_bin_s"] / 60,
            y=100 * h["n"] / h["n"].sum(),
            name=MODE_LABELS[mode],
            marker_color=MODE_COLORS[mode],
            opacity=0.85,
            hovertemplate="%{x:.1f} min: %{y:.1f}% of arrivals<extra>"
            + MODE_LABELS[mode]
            + "</extra>",
        )
    )
fig.add_vline(
    x=299 / 60,
    line_dash="dot",
    line_color=MUTED,
    annotation_text="4 min 59 s late",
    annotation_position="top",
)
fig.update_layout(barmode="group", bargap=0.15)
fig.update_xaxes(title="Delay at stop (minutes, 30 s bins; capped at −5 and +30)")
fig.update_yaxes(title="Share of observed arrivals (%)")
st.plotly_chart(style_fig(fig, 340), use_container_width=True)
st.caption(
    "Mean delay is deliberately not shown on its own: delay distributions are long-tailed, "
    "so the median and P90 describe the passenger experience better."
)

with st.expander("Table view"):
    st.dataframe(
        daily[
            [
                "service_date",
                "mode",
                "day_type",
                "otp_pct",
                "otp_wilson_low_pct",
                "coverage_pct",
                "p50_delay_s",
                "p90_delay_s",
                "reliability_pct",
                "n_observed",
                "is_sample_sufficient",
            ]
        ],
        hide_index=True,
    )
footer()
