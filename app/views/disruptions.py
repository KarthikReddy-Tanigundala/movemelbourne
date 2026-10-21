"""Page 6 - Disruptions: service alerts and proxy OTP inside vs outside their windows."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib.common import MODE_COLORS, MODE_LABELS, MUTED, footer, load, page_header, style_fig

alerts = load("alerts")
impact = load("disruption_otp")
page_header(
    "Disruptions",
    "Service alerts from the realtime feed, and how punctuality on the "
    "affected route compared inside vs outside the alert window.",
)
if alerts.empty:
    st.info("No service alerts captured.")
    st.stop()

a = alerts.dropna(subset=["active_start_local"]).copy()
a["active_end_local"] = a["active_end_local"].fillna(
    pd.to_datetime(a["last_seen_feed_ts"], unit="s", utc=True)
    .dt.tz_convert("Australia/Melbourne")
    .dt.tz_localize(None)
)
a["label"] = a["route_display_name"].fillna("Network / stop") + " · " + a["effect"].fillna("")
a = a.drop_duplicates(["alert_id", "label", "active_start_local", "active_end_local"])
fig = px.timeline(
    a,
    x_start="active_start_local",
    x_end="active_end_local",
    y="label",
    color="mode",
    color_discrete_map=MODE_COLORS,
    hover_name="header_text",
    hover_data={"cause": True, "effect": True, "mode": False, "label": False},
)
fig.update_traces(marker_line_width=0)
fig.for_each_trace(lambda t: t.update(name=MODE_LABELS.get(t.name, t.name)))
fig.update_yaxes(title=None, autorange="reversed")
st.plotly_chart(style_fig(fig, 160 + 36 * a["label"].nunique()), use_container_width=True)

if not impact.empty:
    st.subheader("Proxy OTP during vs outside alert windows")
    fig = go.Figure()
    for during, name, colour in (
        (False, "Outside alert window", MUTED),
        (True, "During alert window", None),
    ):
        d = impact[impact["during_disruption"] == during]
        fig.add_trace(
            go.Bar(
                x=d["route_display_name"],
                y=d["otp_pct"],
                name=name,
                marker_color=colour or [MODE_COLORS[m] for m in d["mode"]],
                customdata=d["n_observed"],
                hovertemplate="%{x}: %{y:.1f}% (n=%{customdata:,})<extra>" + name + "</extra>",
            )
        )
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(title="Proxy OTP (%)", range=[0, 100])
    st.plotly_chart(style_fig(fig, 320), use_container_width=True)
    st.caption(
        "Association, not causation: an alert is often published because services are "
        "already late. Planned-works alerts for future dates show no 'during' bar."
    )

with st.expander("Alert text (table view)"):
    st.dataframe(
        alerts[
            [
                "mode",
                "route_display_name",
                "active_start_local",
                "active_end_local",
                "cause",
                "effect",
                "header_text",
                "description_text",
                "n_snapshots",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )
footer()
