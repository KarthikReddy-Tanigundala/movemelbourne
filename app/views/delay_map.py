"""Page 3 - Delay map: stop-level P90 delay and where delay is added along each route."""

import json

import pandas as pd
import pydeck as pdk
import streamlit as st

from lib.common import (
    SEQ_BLUE,
    fmt_delay,
    footer,
    load,
    min_sample,
    mode_filter,
    page_header,
    ramp_rgb,
)

stops = load("stops")
segments = load("segments")
shapes = load("route_shapes")
page_header(
    "Delay map",
    "Darker = worse. Segments show where trips LOSE time between stops; "
    "stops show how late arrivals typically are.",
)
if stops.empty:
    st.info("No stop data exported yet.")
    st.stop()

c1, c2 = st.columns([2, 3])
with c1:
    modes = mode_filter("map_modes")
with c2:
    layer_choice = st.radio(
        "Show", ["Delay added per segment", "P90 delay at stops"], horizontal=True
    )

min_n = min_sample()
s = stops[stops["mode"].isin(modes)].copy()
seg = segments[segments["mode"].isin(modes)].copy()
shp = shapes[shapes["mode"].isin(modes)].copy()

layers = []
if not shp.empty:
    shp["path"] = shp["path_json"].map(json.loads)
    layers.append(
        pdk.Layer(
            "PathLayer",
            shp,
            get_path="path",
            get_color=[137, 135, 129, 90],
            width_min_pixels=2,
            pickable=False,
        )
    )

if layer_choice == "Delay added per segment":
    seg["path"] = seg.apply(lambda r: [[r.from_lon, r.from_lat], [r.to_lon, r.to_lat]], axis=1)
    ok = seg["is_sample_sufficient"]
    vmax = max(float(seg.loc[ok, "median_added_delay_s"].quantile(0.95)) if ok.any() else 60, 30)
    seg["color"] = [
        c if good else [195, 194, 183]
        for c, good in zip(
            ramp_rgb(seg["median_added_delay_s"].clip(lower=0), 0, vmax), ok, strict=True
        )
    ]
    seg["tip"] = seg.apply(
        lambda r: (
            f"{r.route_display_name}: {r.from_stop_name} → "
            f"{r.to_stop_name}<br>median added {fmt_delay(r.median_added_delay_s)}, "
            f"P90 {fmt_delay(r.p90_added_delay_s)} (n={r.n_pairs})"
            + ("" if r.is_sample_sufficient else " - sample too small")
        ),
        axis=1,
    )
    layers.append(
        pdk.Layer(
            "PathLayer",
            seg,
            get_path="path",
            get_color="color",
            width_min_pixels=5,
            pickable=True,
            cap_rounded=True,
        )
    )
    legend = (
        f"Median delay added over the segment: 0 s (light) → {vmax:.0f} s+ (dark); "
        f"grey = n < {min_n}"
    )
else:
    s["sufficient"] = s["n_observed"] >= min_n
    vmax = max(
        float(s.loc[s["sufficient"], "p90_delay_s"].quantile(0.95))
        if s["sufficient"].any()
        else 300,
        60,
    )
    s["color"] = [
        c if ok else [195, 194, 183]
        for c, ok in zip(
            ramp_rgb(s["p90_delay_s"].clip(lower=0), 0, vmax), s["sufficient"], strict=True
        )
    ]
    s["tip"] = s.apply(
        lambda r: (
            f"{r.stop_name}<br>P90 delay {fmt_delay(r.p90_delay_s)}, "
            f"OTP {r.otp_pct:.0f}% (n={int(r.n_observed)})"
            + ("" if r.sufficient else " - sample too small")
        ),
        axis=1,
    )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            s,
            get_position=["stop_lon", "stop_lat"],
            get_fill_color="color",
            get_radius=60,
            radius_min_pixels=4,
            radius_max_pixels=10,
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=1,
            pickable=True,
        )
    )
    legend = f"P90 delay at stop: 0 s (light) → {vmax:.0f} s+ (dark); grey = n < {min_n}"

centre = (
    s[["stop_lat", "stop_lon"]].mean()
    if len(s)
    else pd.Series({"stop_lat": -37.81, "stop_lon": 144.96})
)
st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=float(centre["stop_lat"]), longitude=float(centre["stop_lon"]), zoom=11.2
        ),
        tooltip={"html": "{tip}"},
        map_style=None,
    ),
    height=560,
)
st.markdown(
    "<div style='display:flex;gap:2px;align-items:center'>"
    + "".join(
        f"<span style='width:28px;height:10px;background:{c};display:inline-block'></span>"
        for c in SEQ_BLUE
    )
    + f"<span style='margin-left:8px;font-size:0.85em'>{legend}</span></div>",
    unsafe_allow_html=True,
)

with st.expander("Worst segments (table view)"):
    cols = [
        "route_display_name",
        "from_stop_name",
        "to_stop_name",
        "median_added_delay_s",
        "p90_added_delay_s",
        "n_pairs",
    ]
    st.dataframe(
        segments[segments["mode"].isin(modes) & segments["is_sample_sufficient"]]
        .sort_values("median_added_delay_s", ascending=False)[cols]
        .head(25),
        hide_index=True,
        use_container_width=True,
    )
footer()
