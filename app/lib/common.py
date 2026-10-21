"""Shared data loading, design tokens and page chrome for the MoveMelbourne app.

Design rules (CLAUDE.md §10.3): colour follows the entity (metro is always slot-1 blue, tram
always slot-2 orange); magnitude uses one sequential blue ramp; status colours always come with
an icon and a text label; cells below the minimum sample are greyed out with n shown, never
ranked; every page carries the study-window stamp and the DTP attribution footer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# app/data holds the committed export; MOVEMELBOURNE_APP_DATA points the app at another export
# (e.g. a local preview of the study in progress) without touching the committed files.
DATA_DIR = Path(os.getenv("MOVEMELBOURNE_APP_DATA", Path(__file__).resolve().parents[1] / "data"))

MODE_LABELS = {"metro": "Metro Train", "tram": "Yarra Trams"}
MODE_COLORS = {"metro": "#2a78d6", "tram": "#eb6834"}  # categorical slots 1-2 (validated)
MUTED = "#898781"  # insufficient-sample / reference ink
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STATUS = {
    "good": ("#0ca30c", "✔", "Meets target"),
    "warning": ("#fab219", "▲", "Within 5 pts of target"),
    "critical": ("#d03b3b", "✖", "Below target"),
}


@st.cache_data
def load(name: str) -> pd.DataFrame:
    """Read one pre-aggregated table from app/data (empty frame if absent)."""
    path = DATA_DIR / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


@st.cache_data
def manifest() -> dict:
    path = DATA_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def min_sample() -> int:
    return int(manifest().get("thresholds", {}).get("min_sample_events", 30))


def page_header(title: str, bluf: str | None = None) -> None:
    """Title, study-window stamp, synthetic-sample banner and optional bottom-line-up-front."""
    st.title(title)
    m = manifest()
    start = (m.get("collected_from_local") or "")[:16].replace("T", " ")
    end = (m.get("collected_to_local") or "")[:16].replace("T", " ")
    st.caption(
        f"Collected {start} → {end} (Melbourne time) · built {m.get('built_at_utc', '?')[:10]}"
        f" · timetable versions: {', '.join(m.get('feed_versions', [])) or 'n/a'}"
    )
    if m.get("is_synthetic_sample", True):
        st.warning(
            "**Synthetic sample.** These charts run on simulated realtime data over a real "
            "timetable slice, so the pipeline can be demonstrated before the collection study "
            "finishes. No figure on this page describes real Melbourne services.",
            icon="⚠️",
        )
    elif (hours := collected_hours(m)) < 24 * m.get("study_window", {}).get("minimum_days", 14):
        st.info(
            f"**Study in progress: {hours:.1f} collector-hours of real data so far.** Figures "
            "are early and unrepresentative (time of day, few trips); findings wait for at "
            f"least {m.get('study_window', {}).get('minimum_days', 14)} days.",
            icon="⏳",
        )
    if bluf:
        st.markdown(f"**Bottom line:** {bluf}")


def collected_hours(m: dict) -> float:
    """Hours the collector actually ran (falls back to the first-to-last span)."""
    if m.get("collector_hours") is not None:
        return float(m["collector_hours"])
    start, end = m.get("collected_from_local"), m.get("collected_to_local")
    if not (start and end):
        return 0.0
    return (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 3600


def footer() -> None:
    st.divider()
    st.caption(
        manifest().get("attribution", "Data: Department of Transport and Planning, CC BY 4.0.")
    )


def status_of(value: float | None, target: float | None) -> tuple[str, str, str]:
    """(colour, icon, label) for a value against a target; never colour alone."""
    if value is None or target is None or pd.isna(value) or pd.isna(target):
        return MUTED, "–", "No target or no data"
    if value >= target:
        return STATUS["good"]
    if value >= target - 5:
        return STATUS["warning"]
    return STATUS["critical"]


def fmt_pct(v: float | None, digits: int = 1) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:.{digits}f}%"


def fmt_delay(seconds: float | None) -> str:
    """Seconds -> '1 min 35 s' style string (or '–')."""
    if seconds is None or pd.isna(seconds):
        return "–"
    sign = "-" if seconds < 0 else ""
    s = abs(int(round(seconds)))
    return f"{sign}{s // 60} min {s % 60:02d} s" if s >= 60 else f"{sign}{s} s"


def style_fig(fig: go.Figure, height: int = 360) -> go.Figure:
    """Recessive grid, one font, tight margins, unified hover (dataviz rules)."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        font={"family": "system-ui, -apple-system, Segoe UI, sans-serif", "size": 13},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title": None},
        hoverlabel={"font_size": 12},
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridwidth=0.5)
    return fig


def daily_axis(fig: go.Figure) -> go.Figure:
    """Day-grain x axis: one tick per day, no midnight/noon clock ticks."""
    fig.update_xaxes(type="date", dtick=86_400_000, tickformat="%a %d %b")
    return fig


def ramp_rgb(values: pd.Series, vmin: float, vmax: float) -> list[list[int]]:
    """Map values onto the sequential blue ramp as [r, g, b] (for pydeck layers)."""
    span = max(vmax - vmin, 1e-9)
    out = []
    for v in values.fillna(vmin):
        t = min(max((v - vmin) / span, 0.0), 1.0) * (len(SEQ_BLUE) - 1)
        i = min(int(t), len(SEQ_BLUE) - 2)
        a, b = SEQ_BLUE[i], SEQ_BLUE[i + 1]
        frac = t - i
        out.append(
            [
                round(int(a[k : k + 2], 16) * (1 - frac) + int(b[k : k + 2], 16) * frac)
                for k in (1, 3, 5)
            ]
        )
    return out


def mode_filter(key: str, default: list[str] | None = None) -> list[str]:
    """One-row mode filter shared by pages."""
    modes = list(MODE_LABELS)
    return (
        st.pills(
            "Mode",
            modes,
            selection_mode="multi",
            default=default or modes,
            format_func=MODE_LABELS.get,
            key=key,
        )
        or modes
    )
