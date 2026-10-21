"""Page 8 - Live now: current vehicle positions (optional; needs TVOD_API_KEY in st.secrets).

Responses are cached for 60 s for all viewers, so traffic to DTP stays at most 1 call per mode
per minute no matter how many people open the page (well inside the published rate limit).
"""

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

from lib.common import MODE_COLORS, MODE_LABELS, footer

BASE = "https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1"
HEADERS = ("Ocp-Apim-Subscription-Key", "KeyID")

st.title("Live now")
st.caption(
    "Current vehicle positions from the GTFS-Realtime feed, refreshed at most once a "
    "minute. Not stored; the rest of the site shows the fixed study window."
)


def api_key() -> str | None:
    try:
        return st.secrets.get("TVOD_API_KEY")
    except Exception:  # noqa: BLE001 - no secrets file configured
        return None


@st.cache_data(ttl=60, show_spinner="Fetching live positions…")
def fetch(mode: str, key: str) -> pd.DataFrame:
    from google.transit import gtfs_realtime_pb2 as rt

    for header in HEADERS:
        r = requests.get(f"{BASE}/{mode}/vehicle-positions", headers={header: key}, timeout=20)
        if r.status_code not in (401, 403):
            break
    r.raise_for_status()
    feed = rt.FeedMessage()
    feed.ParseFromString(r.content)
    rows = [
        {
            "mode": mode,
            "vehicle": e.vehicle.vehicle.label or e.vehicle.vehicle.id,
            "route_id": e.vehicle.trip.route_id,
            "lat": e.vehicle.position.latitude,
            "lon": e.vehicle.position.longitude,
            "ts": e.vehicle.timestamp,
        }
        for e in feed.entity
        if e.HasField("vehicle") and e.vehicle.HasField("position")
    ]
    return pd.DataFrame(rows)


key = api_key()
if not key:
    st.info("Live mode is off: add `TVOD_API_KEY` to the app's secrets to enable it.")
    footer()
    st.stop()

frames = []
for mode in MODE_LABELS:
    try:
        frames.append(fetch(mode, key))
    except Exception as exc:  # noqa: BLE001
        st.warning(f"{MODE_LABELS[mode]}: live feed unavailable ({type(exc).__name__}).")
live = pd.concat(frames) if frames else pd.DataFrame()
if live.empty:
    st.stop()

cols = st.columns(len(MODE_LABELS))
for col, mode in zip(cols, MODE_LABELS, strict=True):
    col.metric(f"{MODE_LABELS[mode]} vehicles reporting", f"{(live['mode'] == mode).sum():,}")
live["color"] = live["mode"].map(lambda m: [int(MODE_COLORS[m][i : i + 2], 16) for i in (1, 3, 5)])
live["tip"] = live["mode"].map(MODE_LABELS) + " " + live["vehicle"] + " · " + live["route_id"]
st.pydeck_chart(
    pdk.Deck(
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                live,
                get_position=["lon", "lat"],
                get_fill_color="color",
                get_radius=80,
                radius_min_pixels=3,
                pickable=True,
            )
        ],
        initial_view_state=pdk.ViewState(latitude=-37.81, longitude=144.96, zoom=10.5),
        tooltip={"text": "{tip}"},
        map_style=None,
    ),
    height=560,
)
footer()
