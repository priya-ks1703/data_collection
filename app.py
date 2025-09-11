import io
import json
import random
from datetime import datetime
from typing import Any, Dict, List, Tuple, Union

import streamlit as st

st.set_page_config(page_title="JSON Scoring App", layout="wide")
st.title("JSON Scoring App: choose 0 / 0.5 / 1 per item")
st.write("This app loads items from a predefined JSON file (`input_texts.json`) the first time. You can also press a button to upload a saved progress file to continue.")
st.write("""Prompt:

You are a visionary researcher in quantum optics. You lead a team of scientists and want to provide ideas for them. Your team constists of theoretical quantum optics researchers who are amazing in taking your ideas and creating wonderful stand-alone proposals for experiments. The stand-alone proposals created by your team members are often published in top-journals such as Phys.Rev.Lett. (PRL). That requires that the idea is scientifically novel and concrete proposals from your ideas should be interesting for individual experts in the field or the field of quantum physics researchers as a whole.

Your team is especially exceptionally good in executing your ideas to fully detailed experimental proposals if your ideas are targeted for the following domain:

Concrete quantum networks systems (e.g., generalizations of entanglement swapping, quantum teleportation, etc) and foundational quantum optics experiments. Your ideas should be implementable with probabilistic photon-pair sources (such as SPDC), or probabilistic and deterministic single-photon sources, and standard linear optics elements. Your team cannot design experiments that require dynamic feedback control. If your idea is in that realm, your team will figure out a great way to develop a full proposal.

Respond exactly with the following format:
         
Thought: (the reasoning behind the idea)
         
Final idea: (the actual idea if you are happy with it)
         
Do not add any other text. Do not output multiple Thoughts and Final ideas.""")
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
    """Return (ids, prefilled_scores, payload_map).
    - Supports three shapes:
      1) Progress export: {"scores": {...}, "meta": {...}, "items_payloads": {...}}
      2) Dict input: keys become ids; payload is value; if value is None, payload is key
      3) List input:
         - list of primitives: id == str(item), payload == item
         - list of complex items: id == item_{i}, payload == element
      4) Other: single id 'item_0' with str(raw) as payload
    """
    # Case 1: our own export format
    if isinstance(raw, dict) and "scores" in raw and isinstance(raw["scores"], dict):
        ids = list(raw["scores"].keys())
        prefilled = {k: float(v) for k, v in raw["scores"].items() if _is_valid_score(v)}
        payloads = {}
        if isinstance(raw.get("items_payloads"), dict):
            payloads = raw["items_payloads"]
        else:
            # Fallback: show ids as text if no payloads embedded
            payloads = {k: k for k in ids}
        return ids, prefilled, payloads

    # Case 2: dict input -> ids are keys; payloads are values (or key itself if value is None)
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
    """Display the payload without altering its internal order/content."""
    if isinstance(payload, (str, int, float, bool)):
        st.write(str(payload))
    elif isinstance(payload, list):
        # If it's a list of primitives, show joined; otherwise pretty-print JSON
        if all(isinstance(x, (str, int, float, bool)) for x in payload):
            st.write(" ".join(str(x) for x in payload))
        else:
            st.code(json.dumps(payload, ensure_ascii=False, indent=2))
    elif isinstance(payload, dict):
        # Prefer common text fields if present
        for key in ("text", "content", "sentence", "value"):
            if key in payload and isinstance(payload[key], (str, int, float)):
                st.write(str(payload[key]))
                return
        # Otherwise pretty-print JSON (dict insertion order is preserved in Python 3.7+)
        st.code(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        st.write(str(payload))


# -----------------------------------------------------------------------------
# Load input (file by default) and optional resume via button-triggered upload
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "input_texts.json"
raw_data: Any = None

# Default: load from file
try:
    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
except FileNotFoundError:
    st.warning(f"Input file not found: {INPUT_JSON_PATH}. You can upload a progress JSON instead.")
except Exception as e:
    st.error(f"Could not parse JSON from {INPUT_JSON_PATH}: {e}")

# Button + uploader for resume
if st.button("Upload progress file to continue"):
    uploaded = st.file_uploader("Choose a progress JSON", type=["json"], key="resume_upload")
    if uploaded is not None:
        try:
            raw_data = json.load(uploaded)
            st.success("Loaded uploaded progress JSON.")
        except Exception as e:
            st.error(f"Could not parse uploaded JSON: {e}")

# -----------------------------------------------------------------------------
# Prepare items, payloads, and randomized order
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

# Establish non-repeating random order
if "order" not in st.session_state or set(st.session_state.order) != set(ids) or len(st.session_state.order) != len(ids):
    meta_order = _restore_order_from_meta(raw_data, ids)
    if meta_order is not None:
        st.session_state.order = meta_order
    else:
        st.session_state.order = random.sample(ids, k=len(ids))

# -----------------------------------------------------------------------------
# Main UI (paged over randomized ids)
# -----------------------------------------------------------------------------
options = [0.0, 0.5, 1.0]

if "scores" not in st.session_state:
    st.session_state.scores = {}

# Initialize with prefilled values
for k, v in prefilled.items():
    st.session_state.scores.setdefault(k, v)

if "page" not in st.session_state:
    st.session_state.page = 0


def next_page():
    if st.session_state.page < len(st.session_state.order) - 1:
        st.session_state.page += 1

def prev_page():
    if st.session_state.page > 0:
        st.session_state.page -= 1

current_id = st.session_state.order[st.session_state.page]
payload = payloads.get(current_id, current_id)

st.subheader(f"Item {st.session_state.page + 1}/{len(st.session_state.order)}")
_render_payload(payload)

try:
    default_idx = options.index(float(st.session_state.scores.get(current_id, 0.0)))
except Exception:
    default_idx = 0

score = st.radio(
    label="Score",
    options=options,
    index=default_idx,
    horizontal=True,
    key=f"score_{current_id}",
)
st.session_state.scores[current_id] = float(score)

nav_prev, nav_middle, nav_next = st.columns([1, 2, 1])
with nav_prev:
    st.button("Previous", on_click=prev_page, disabled=st.session_state.page == 0)
with nav_middle:
    completed = sum(1 for k in st.session_state.order if k in st.session_state.scores)
    st.write(f"Page {st.session_state.page + 1} / {len(st.session_state.order)} · Completed: {completed}/{len(st.session_state.order)}")
with nav_next:
    st.button("Next", on_click=next_page, disabled=st.session_state.page >= len(st.session_state.order) - 1)

if st.session_state.page == len(st.session_state.order) - 1:
    st.success("Reached the last item. Use Download to save your results.")

st.markdown("---")

# -----------------------------------------------------------------------------
# Export (embed payloads and randomized order so resume shows identical content)
# -----------------------------------------------------------------------------
export = {
    "scores": {k: float(v) for k, v in st.session_state.scores.items() if k in ids},
    "meta": {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(ids),
        "valid_scores": [0, 0.5, 1],
        "order": st.session_state.order,
    },
    "items_payloads": payloads,  # embed full content to render exactly on resume
}

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

st.caption("Items are shown in a randomized, non-repeating order. Upload a saved progress file to resume with the same order and content.")