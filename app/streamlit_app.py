"""MoveMelbourne dashboard: how reliable are Melbourne's trains and trams?

    uv run streamlit run app/streamlit_app.py

Reads only the small pre-aggregated files in app/data (scripts/export_gold.py).
"""

import streamlit as st

st.set_page_config(page_title="MoveMelbourne", page_icon="🚊", layout="wide")

pages = [
    st.Page(
        "views/network_health.py",
        title="Network health",
        icon=":material/monitor_heart:",
        default=True,
    ),
    st.Page("views/route_ranking.py", title="Route reliability", icon=":material/leaderboard:"),
    st.Page("views/delay_map.py", title="Delay map", icon=":material/map:"),
    st.Page("views/time_patterns.py", title="When it goes wrong", icon=":material/schedule:"),
    st.Page("views/tram_bunching.py", title="Tram bunching", icon=":material/tram:"),
    st.Page("views/disruptions.py", title="Disruptions", icon=":material/warning:"),
    st.Page("views/data_quality.py", title="Data quality & method", icon=":material/fact_check:"),
    st.Page("views/live_now.py", title="Live now", icon=":material/sensors:"),
]
st.navigation(pages).run()
