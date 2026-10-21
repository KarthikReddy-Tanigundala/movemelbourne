"""Page 4 - When it goes wrong: share of late arrivals by day type and hour of day."""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from lib.common import (
    MODE_COLORS,
    MODE_LABELS,
    SEQ_BLUE,
    footer,
    load,
    min_sample,
    mode_filter,
    page_header,
    style_fig,
)

hour = load("hour_dow")
bands = load("time_band_otp")
page_header(
    "When it goes wrong",
    "Darker cells = a larger share of arrivals outside the on-time "
    "window. Holidays (e.g. Melbourne Cup Day) are grouped with Sundays because they run "
    "Sunday-like timetables.",
)
if hour.empty:
    st.info("No time-pattern data exported yet.")
    st.stop()

min_n = min_sample()
day_types = ["Weekday", "Saturday", "Sunday / public holiday"]
for mode in mode_filter("time_modes"):
    h = hour[hour["mode"] == mode]
    if h.empty:
        continue
    grid = (
        h.assign(w=h["otp_pct"] * h["n_observed"])
        .groupby(["day_type", "hour_of_day"])[["w", "n_observed"]]
        .sum()
    )
    grid["late_pct"] = 100 - grid["w"] / grid["n_observed"]
    late = grid["late_pct"].unstack().reindex(day_types)
    n = grid["n_observed"].unstack().reindex(day_types)
    shown = late.where(n >= min_n)
    text = n.map(lambda v: "" if np.isnan(v) else ("" if v >= min_n else f"n={int(v)}"))
    st.subheader(MODE_LABELS[mode])
    fig = go.Figure(
        go.Heatmap(
            z=shown.values,
            x=[f"{c:02d}:00" for c in shown.columns],
            y=shown.index,
            colorscale=[[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)],
            zmin=0,
            colorbar={"title": "% not on time"},
            xgap=2,
            ygap=2,
            text=text.values,
            texttemplate="%{text}",
            customdata=n.values,
            hovertemplate="%{y}, %{x}<br>%{z:.1f}% not on time<br>n = %{customdata:,}<extra></extra>",
        )
    )
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(style_fig(fig, 260), use_container_width=True)
st.caption(
    f"Blank cells: no observations or fewer than {min_n} (count shown). Hour = scheduled "
    "local hour of arrival."
)

st.subheader("Peak vs off-peak")
fig = go.Figure()
for mode in bands["mode"].unique():
    b = (
        bands[bands["mode"] == mode]
        .assign(w=lambda d: d["otp_pct"] * d["n_observed"])
        .groupby(["time_band", "time_band_sort"])[["w", "n_observed"]]
        .sum()
        .reset_index()
        .sort_values("time_band_sort")
    )
    b["otp"] = b["w"] / b["n_observed"]
    fig.add_trace(
        go.Bar(
            x=b["time_band"],
            y=b["otp"],
            name=MODE_LABELS[mode],
            marker_color=MODE_COLORS[mode],
            customdata=b["n_observed"],
            hovertemplate="%{x}: %{y:.1f}% (n=%{customdata:,})<extra></extra>",
        )
    )
fig.update_yaxes(title="Proxy OTP (%)", range=[0, 100])
fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
st.plotly_chart(style_fig(fig, 320), use_container_width=True)
footer()
