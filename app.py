import io
import json
import random
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Tuple, Union

import streamlit as st

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="JSON Scoring App", layout="wide")
st.title("JSON Scoring App: choose 0 / 0.5 / 1 per item")
st.write("Load from `input_texts.json` or upload a saved progress file to continue.")
st.write(
    """Prompt:
         
You are a visionary researcher in quantum optics. You lead a team of scientists and want to provide ideas for them. Your team constists of theoretical quantum optics researchers who are amazing in taking your ideas and creating wonderful stand-alone proposals for experiments. The stand-alone proposals created by your team members are often published in top-journals such as Phys.Rev.Lett. (PRL). That requires that the idea is scientifically novel and concrete proposals from your ideas should be interesting for individual experts in the field or the field of quantum physics researchers as a whole.

Your team is especially exceptionally good in executing your ideas to fully detailed experimental proposals if your ideas are targeted for the following domain:

Concrete quantum networks systems (e.g., generalizations of entanglement swapping, quantum teleportation, etc) and foundational quantum optics experiments. Your ideas should be implementable with probabilistic photon-pair sources (such as SPDC), or probabilistic and deterministic single-photon sources, and standard linear optics elements. Your team cannot design experiments that require dynamic feedback control. If your idea is in that realm, your team will figure out a great way to develop a full proposal.

Respond exactly with the following format:
         
Thought: (the reasoning behind the idea)
         
Final idea: (the actual idea if you are happy with it)
         
Do not add any other text. Do not output multiple Thoughts and Final ideas."""
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
Primitive = Union[str, int, float, bool]
Payload = Union[Primitive, List[Any], Dict[str, Any]]


def _is_valid_score(v: Any) -> bool:
    try:
        f = float(v)
        return f in {0.0, 0.5, 1.0}
    except Exception:
        return False


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")


def _normalize_raw(raw: Any) -> Tuple[List[str], Dict[str, float], Dict[str, Payload]]:
    """Return (ids, prefilled_scores, payload_map)."""
    # Case 1: our own export format
    if isinstance(raw, dict) and "scores" in raw and isinstance(raw["scores"], dict):
        prefilled = {k: float(v) for k, v in raw["scores"].items() if _is_valid_score(v)}
        items_payloads = raw.get("items_payloads")
        if isinstance(items_payloads, dict) and len(items_payloads) > 0:
            ids = list(items_payloads.keys())
            payloads = items_payloads
        else:
            ids = list(prefilled.keys())
            payloads = {k: k for k in ids}
        return ids, prefilled, payloads

    # Case 2: dict input
    if isinstance(raw, dict):
        ids = list(raw.keys())
        payloads = {k: (raw[k] if raw[k] is not None else k) for k in ids}
        return ids, {}, payloads

    # Case 3: list input
    if isinstance(raw, list):
        if all(isinstance(x, (str, int, float, bool)) for x in raw):
            ids = [str(x) for x in raw]
            payloads = {str(x): x for x in raw}
            return ids, {}, payloads
        else:
            ids = [f"item_{i}" for i, _ in enumerate(raw)]
            payloads = {f"item_{i}": raw[i] for i in range(len(raw))}
            return ids, {}, payloads

    # Case 4: fallback single item
    return ["item_0"], {}, {"item_0": raw}


def _restore_order_from_meta(raw: Any, ids: List[str]) -> List[str] | None:
    try:
        if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
            order = raw["meta"].get("order")
            if isinstance(order, list) and set(order) == set(ids) and len(order) == len(ids):
                return order
    except Exception:
        pass
    return None


def _render_payload(payload: Payload) -> None:
    if isinstance(payload, (str, int, float, bool)):
        st.write(str(payload))
    elif isinstance(payload, list):
        if all(isinstance(x, (str, int, float, bool)) for x in payload):
            st.write(" ".join(str(x) for x in payload))
        else:
            st.code(json.dumps(payload, ensure_ascii=False, indent=2))
    elif isinstance(payload, dict):
        for key in ("text", "content", "sentence", "value"):
            if key in payload and isinstance(payload[key], (str, int, float)):
                st.write(str(payload[key]))
                return
        st.code(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        st.write(str(payload))


def _first_unscored(order: List[str], scores: Dict[str, float]) -> int:
    for i, k in enumerate(order):
        if k not in scores:
            return i
    return 0


# -----------------------------------------------------------------------------
# Load input (file by default) and allow resume via uploader; persist in session
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "input_texts.json"

# Load from session first
raw_data: Any = st.session_state.get("raw_data", None)

# Default file (only if nothing in session)
if raw_data is None:
    try:
        with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        st.info(f"Loaded input from: {INPUT_JSON_PATH}")
        st.session_state["raw_data"] = raw_data
        st.session_state["source"] = INPUT_JSON_PATH
    except FileNotFoundError:
        st.warning(f"Input file not found: {INPUT_JSON_PATH}. You can upload a progress JSON instead.")
    except Exception as e:
        st.error(f"Could not parse JSON from {INPUT_JSON_PATH}: {e}")

# Upload handling: process only when a new file is selected
uploaded = st.file_uploader(
    "Upload a progress JSON to continue (optional)", type=["json"], key="resume_upload"
)

if uploaded is not None:
    try:
        uploaded_bytes = uploaded.getvalue()
        uploaded_hash = hashlib.md5(uploaded_bytes).hexdigest()

        if st.session_state.get("uploaded_hash") != uploaded_hash:
            raw = json.loads(uploaded_bytes.decode("utf-8"))
            st.session_state["uploaded_hash"] = uploaded_hash
            st.session_state["raw_data"] = raw
            raw_data = raw

            # Reset scores from upload; jump to next unscored once
            st.session_state["scores"] = {}
            st.session_state["resume_now"] = True
            st.session_state["source"] = "uploaded progress"
            st.success("Loaded uploaded progress JSON.")
        # same file on reruns -> do nothing
    except Exception as e:
        st.error(f"Could not parse uploaded JSON: {e}")

# -----------------------------------------------------------------------------
# Prepare items, payloads
# -----------------------------------------------------------------------------
ids: List[str] = []
prefilled: Dict[str, float] = {}
payloads: Dict[str, Payload] = {}

if raw_data is not None:
    ids, prefilled, payloads = _normalize_raw(raw_data)

if not ids:
    st.info("No items found in input JSON.")
    st.stop()

st.success(f"Loaded {len(ids)} items.")

# Keep full sets for export
ids_all = ids
payloads_all = payloads

# Scores state
if "scores" not in st.session_state:
    st.session_state.scores = {}
# Merge prefilled from file or upload
for k, v in prefilled.items():
    st.session_state.scores[k] = v

# -----------------------------------------------------------------------------
# Order (stable) and visibility helpers
# -----------------------------------------------------------------------------
def _make_base_order() -> List[str]:
    meta_order = _restore_order_from_meta(raw_data, ids_all)
    if meta_order is not None:
        return meta_order
    return random.sample(ids_all, k=len(ids_all))

if "base_order" not in st.session_state or set(st.session_state.base_order) != set(ids_all):
    st.session_state.base_order = _make_base_order()

# sticky_id keeps the currently scored item visible even if completed
if "sticky_id" not in st.session_state:
    st.session_state.sticky_id = None

if "hide_completed" not in st.session_state:
    st.session_state.hide_completed = True

def _toggle_hide_completed():
    # When toggling visibility, move to the first visible item
    st.session_state.page = 0
    st.session_state.sticky_id = None
    st.session_state["resume_now"] = True  # force jump to first visible on next block

hide_completed = st.checkbox(
    "Show only unscored items",
    value=st.session_state.hide_completed,
    key="hide_completed",
    on_change=_toggle_hide_completed,
)

# Compute completed set every run
completed_keys = {k for k in st.session_state.scores if k in ids_all and _is_valid_score(st.session_state.scores[k])}

def _is_visible(item_id: str) -> bool:
    if not st.session_state.hide_completed:
        return True
    return (item_id not in completed_keys) or (item_id == st.session_state.sticky_id)

def _next_visible_index(i: int) -> int:
    base = st.session_state.base_order
    for j in range(i + 1, len(base)):
        if _is_visible(base[j]):
            return j
    return i  # no forward visible item

def _prev_visible_index(i: int) -> int:
    base = st.session_state.base_order
    for j in range(i - 1, -1, -1):
        if _is_visible(base[j]):
            return j
    return i  # no backward visible item

def _first_visible_index() -> int:
    base = st.session_state.base_order
    for j in range(len(base)):
        if _is_visible(base[j]):
            return j
    return 0

# Page index initialization (always in base_order coordinates)
if ("page" not in st.session_state) or st.session_state.get("resume_now"):
    if st.session_state.hide_completed:
        st.session_state.page = _first_visible_index()
    else:
        st.session_state.page = _first_unscored(st.session_state.base_order, st.session_state.scores)
    st.session_state["resume_now"] = False

# If nothing visible, show completion state and export
any_visible = any(_is_visible(i) for i in st.session_state.base_order)
if not any_visible:
    st.success("All items are completed. You can download your progress below.")
    export = {
        "scores": {k: float(v) for k, v in st.session_state.scores.items() if k in ids_all},
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "count": len(ids_all),
            "valid_scores": [0, 0.5, 1],
            "order": st.session_state.base_order,
        },
        "items_payloads": payloads_all,
    }
    st.download_button(
        label="Download progress (JSON)",
        data=_json_dumps(export),
        file_name="progress.json",
        mime="application/json",
        key="download_progress_all_done",
    )
    filename = f"scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    st.download_button(
        label="Download JSON",
        data=_json_dumps(export),
        file_name=filename,
        mime="application/json",
    )
    st.stop()

# -----------------------------------------------------------------------------
# Main UI (driven by base_order + visibility)
# -----------------------------------------------------------------------------
idx = st.session_state.page
# Clamp idx to a visible item (in case data changed)
if not _is_visible(st.session_state.base_order[idx]):
    idx = _first_visible_index()
    st.session_state.page = idx

current_id = st.session_state.base_order[idx]
payload = payloads_all.get(current_id, current_id)

# Stable position info
total = len(st.session_state.base_order)
position = st.session_state.base_order.index(current_id) + 1
remaining = len([k for k in ids_all if k not in completed_keys])

st.subheader(f"Item {position}/{total}")
_render_payload(payload)

# Scoring (auto-advance to next visible when hiding completed)
def _set_score(item_id: str):
    val = st.session_state[f"score_{item_id}"]
    st.session_state.scores[item_id] = float(val)
    if st.session_state.get("hide_completed", True):
        # Do not keep completed item sticky; let it disappear
        st.session_state.sticky_id = None
        # Move to the next visible index (prevents getting stuck at last visible)
        st.session_state.page = _next_visible_index(st.session_state.page)
    else:
        # When showing all, keep it sticky to avoid jumpiness
        st.session_state.sticky_id = item_id

# default selection
options = [0.0, 0.5, 1.0]
default_value = float(st.session_state.scores.get(current_id, 0.0))
st.radio(
    label="Score",
    options=options,
    index=options.index(default_value),
    horizontal=True,
    key=f"score_{current_id}",
    on_change=_set_score,
    args=(current_id,),
)

# Ensure dict has value on first render too
if current_id not in st.session_state.scores:
    st.session_state.scores[current_id] = default_value

# Navigation: move across visible items while indexing base_order
def _next_page():
    st.session_state.sticky_id = None
    st.session_state.page = _next_visible_index(st.session_state.page)

def _prev_page():
    st.session_state.sticky_id = None
    st.session_state.page = _prev_visible_index(st.session_state.page)

next_disabled = _next_visible_index(st.session_state.page) == st.session_state.page
prev_disabled = _prev_visible_index(st.session_state.page) == st.session_state.page

nav_prev, nav_middle, nav_next = st.columns([1, 2, 1])
with nav_prev:
    st.button("Previous", on_click=_prev_page, disabled=prev_disabled)
with nav_middle:
    completed_total = len(completed_keys)
    st.write(
        f"Position {position} / {total} · Completed: {completed_total}/{len(ids_all)} · Remaining: {remaining}"
    )
with nav_next:
    st.button("Next", on_click=_next_page, disabled=next_disabled)

st.markdown("---")

# -----------------------------------------------------------------------------
# Export (embed payloads and base order so resume shows identical content)
# -----------------------------------------------------------------------------
export = {
    "scores": {k: float(v) for k, v in st.session_state.scores.items() if k in ids_all},
    "meta": {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(ids_all),
        "valid_scores": [0, 0.5, 1],
        "order": st.session_state.base_order,
    },
    "items_payloads": payloads_all,
}

st.caption("Progress is saved until the item you currently see. So if you do not rate the current item, it is saved as 0.")
st.download_button(
    label="Download progress (JSON)",
    data=_json_dumps(export),
    file_name="progress.json",
    mime="application/json",
    key="download_progress",
)

filename = f"scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
st.download_button(
    label="Download JSON",
    data=_json_dumps(export),
    file_name=filename,
    mime="application/json",
)

source = st.session_state.get("source", "unknown")
