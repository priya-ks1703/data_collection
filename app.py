import io
import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import streamlit as st

st.set_page_config(page_title="JSON Scoring App", layout="wide")
st.title("JSON Scoring App: choose 0 / 0.5 / 1 per item")

# --- Helpers -----------------------------------------------------------------

def _normalize_items(data: Any) -> Tuple[List[str], Dict[str, float]]:
    """
    Return (items, prefilled_scores).
    - If data looks like a prior export (has key 'scores'), use that mapping.
    - If data is a dict, use keys as items.
    - If data is a list of primitives, use their string forms as items.
    - Otherwise, index items as item_0, item_1, ...
    """
    if isinstance(data, dict) and "scores" in data and isinstance(data["scores"], dict):
        items = list(data["scores"].keys())
        prefilled = {k: float(v) for k, v in data["scores"].items() if _is_valid_score(v)}
        return items, prefilled

    if isinstance(data, dict):
        return list(data.keys()), {}

    if isinstance(data, list):
        if all(isinstance(x, (str, int, float, bool)) for x in data):
            return [str(x) for x in data], {}
        # Fallback for complex lists (e.g., list of dicts)
        return [f"item_{i}" for i, _ in enumerate(data)], {}

    # Last resort: single value -> one item
    return [str(data)], {}


def _is_valid_score(v: Any) -> bool:
    try:
        f = float(v)
        return f in {0.0, 0.5, 1.0}
    except Exception:
        return False


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")


# --- Sidebar: Upload / Example ----------------------------------------------
with st.sidebar:
    st.header("Input JSON")
    uploaded = st.file_uploader("Upload a JSON file", type=["json"])    
    use_example = st.checkbox("Use example data", value=not bool(uploaded))

    if use_example and not uploaded:
        example_data = {
            "habits": ["Workout", "Read", "Meditate", "Sleep 8h"],
            "note": "Scores: 0 = no, 0.5 = partial, 1 = yes"
        }
        raw_data = example_data["habits"]
    else:
        raw_data = None
        if uploaded is not None:
            try:
                raw_data = json.load(uploaded)
            except Exception as e:
                st.error(f"Could not parse JSON: {e}")

# --- Prepare items -----------------------------------------------------------
items: List[str] = []
prefilled: Dict[str, float] = {}

if raw_data is not None:
    items, prefilled = _normalize_items(raw_data)

if not items:
    st.info("Upload a JSON file in the sidebar or enable example data to begin.")
    st.stop()

st.success(f"Loaded {len(items)} items.")

# --- Main UI -----------------------------------------------------------------
options = [0.0, 0.5, 1.0]

# Keep scores in session state
if "scores" not in st.session_state:
    st.session_state.scores = {}

# Initialize with prefilled values (only once per item)
for k, v in prefilled.items():
    st.session_state.scores.setdefault(k, v)

# Table-like layout
cols = st.columns([3, 2])
with cols[0]:
    st.subheader("Item")
with cols[1]:
    st.subheader("Score")

for name in items:
    c1, c2 = st.columns([3, 2])
    with c1:
        st.write(name)
    with c2:
        default_idx = 0
        if name in st.session_state.scores:
            try:
                default_idx = options.index(float(st.session_state.scores[name]))
            except Exception:
                default_idx = 0
        score = st.radio(
            key=f"score_{name}",
            label=" ",
            options=options,
            index=default_idx,
            horizontal=True,
        )
        st.session_state.scores[name] = float(score)

st.markdown("---")

# --- Actions -----------------------------------------------------------------
left, right = st.columns([1, 1])
with left:
    if st.button("Reset all to 0"):
        for k in items:
            st.session_state.scores[k] = 0.0
        st.toast("All scores reset to 0.")

with right:
    if st.button("Set all to 1"):
        for k in items:
            st.session_state.scores[k] = 1.0
        st.toast("All scores set to 1.")

# --- Export ------------------------------------------------------------------
export = {
    "scores": {k: float(v) for k, v in st.session_state.scores.items() if k in items},
    "meta": {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(items),
        "valid_scores": [0, 0.5, 1],
    },
}

filename = f"scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
st.download_button(
    label="Download JSON",
    data=_json_dumps(export),
    file_name=filename,
    mime="application/json",
)

st.caption("Tip: You can re-upload the downloaded file later to continue editing.")
