# app.py
# Streamlit UI for sentence-level annotation with freeform feedback.
# Usage:
#   1) Put your texts in input_texts.json (see example below).
#   2) streamlit run app.py

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import os

import streamlit as st

# ---------- Configuration ----------
INPUT_JSON = st.secrets.get("INPUT_JSON", "input_texts.json")   # list[str] or list[{"id":..., "text":...}]
OUTPUT_JSON = st.secrets.get("OUTPUT_JSON", "annotations.json") # cumulative output file
CATEGORIES = json.loads(os.getenv(
    "CATEGORIES",
    '["Factual claim","Opinion","Emotion","Actionable instruction","Other"]'
))
ALLOW_MULTI_CATEGORY = True  # set False to allow only one category per sentence

# ---------- Utilities ----------
_SENT_SPLIT_REGEX = re.compile(
    r"""          # very lightweight, rule-based sentence splitter
    (?<!\b[A-Z])  # avoid splitting after single-letter initials
    (?<=[\.\?\!]) # end punctuation
    \s+           # whitespace after end punctuation
    """,
    re.VERBOSE
)

def split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    # Keep punctuation with the sentence by splitting on the following whitespace
    parts = _SENT_SPLIT_REGEX.split(text)
    # Clean and drop empties
    return [s.strip() for s in parts if s.strip()]

def load_texts(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items: List[Dict[str, Any]] = []
    if isinstance(data, list):
        for i, entry in enumerate(data):
            if isinstance(entry, dict) and "text" in entry:
                items.append({"id": entry.get("id", str(i)), "text": entry["text"]})
            elif isinstance(entry, str):
                items.append({"id": str(i), "text": entry})
    return items

def append_annotation(path: str, record: Dict[str, Any]) -> None:
    p = Path(path)
    # Persist as a JSON array (append-in-place)
    if p.exists():
        try:
            arr = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(arr, list):
                arr = []
        except Exception:
            arr = []
    else:
        arr = []
    arr.append(record)
    p.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- App State ----------
st.set_page_config(page_title="Sentence Annotation UI", page_icon="✍️", layout="centered")

if "texts" not in st.session_state:
    st.session_state.texts = load_texts(INPUT_JSON)
if "idx" not in st.session_state:
    st.session_state.idx = 0
if "history" not in st.session_state:
    st.session_state.history = []  # keep simple session history

texts = st.session_state.texts
idx = st.session_state.idx

# ---------- Header ----------
st.title("Sentence Annotation")
st.caption(f"Input: {INPUT_JSON} • Output: {OUTPUT_JSON}")

if not texts:
    st.warning("No texts found. Create input_texts.json with a list of texts or objects containing a 'text' field.")
    st.code(
        '[\n  "First text to annotate.",\n  {"id": "custom-1", "text": "Second text to annotate."}\n]',
        language="json",
    )
    st.stop()

# ---------- Current Text ----------
current = texts[idx]
sentences = split_sentences(current["text"])

st.subheader(f"Text {idx + 1} of {len(texts)}")
st.write(current["text"])

# ---------- Annotation Form ----------
with st.form(key=f"form-{idx}"):
    st.markdown("### Sentence Annotations")

    selections: Dict[int, Any] = {}
    for i, sent in enumerate(sentences):
        with st.expander(f"Sentence {i+1}: {sent}", expanded=False):
            ratings = {}
            ratings["novelty"] = st.slider(
                f"Novelty (1–5) for sentence {i+1}", 1, 5, 3, key=f"novelty-{i}"
            )
            ratings["feasibility"] = st.slider(
                f"Feasibility (1–5) for sentence {i+1}", 1, 5, 3, key=f"feasibility-{i}"
            )
            ratings["relevance"] = st.slider(
                f"Relevance (1–5) for sentence {i+1}", 1, 5, 3, key=f"relevance-{i}"
            )
            ratings["interest"] = st.slider(
                f"Interest (1–5) for sentence {i+1}", 1, 5, 3, key=f"interest-{i}"
            )
            selections[i] = ratings

    st.markdown("### Freeform Feedback")
    feedback = st.text_area(
        "Enter any feedback about this text",
        key=f"feedback-{idx}",
        height=140,
        placeholder="Write your observations, edge cases, or quality notes here..."
    )

    col1, col2 = st.columns([1, 1])
    save_btn = col1.form_submit_button("Save and Next ➜")
    skip_btn = col2.form_submit_button("Skip ➜")

# ---------- Actions ----------
def go_next():
    st.session_state.idx = min(st.session_state.idx + 1, len(texts) - 1)

if save_btn:
    record = {
        "text_id": current["id"],
        "text": current["text"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sentences": [
            {
                "index": i,
                "text": s,
                "labels": selections.get(i, []) or []
            } for i, s in enumerate(sentences)
        ],
        "feedback": feedback.strip(),
        "categories_available": CATEGORIES,
        "allow_multi_category": ALLOW_MULTI_CATEGORY,
    }
    try:
        append_annotation(OUTPUT_JSON, record)
        st.session_state.history.append(current["id"])
        st.success("Saved.")
        if st.session_state.idx < len(texts) - 1:
            go_next()
        else:
            st.info("All texts processed.")
    except Exception as e:
        st.error(f"Failed to save: {e}")

elif skip_btn:
    st.info("Skipped.")
    if st.session_state.idx < len(texts) - 1:
        go_next()
    else:
        st.info("No more texts to display.")

# ---------- Footer ----------
with st.sidebar:
    st.header("Settings")
    st.toggle("Allow multiple categories per sentence", value=ALLOW_MULTI_CATEGORY, key="cfg_multi")
    if st.session_state.cfg_multi != ALLOW_MULTI_CATEGORY:
        st.warning("Restart the app to apply the category multiplicity change.")
    st.write("Categories:")
    st.write(", ".join(CATEGORIES))
    st.divider()
    st.markdown("**Progress**")
    st.progress((idx + 1) / max(1, len(texts)))
    if st.button("Restart from first text"):
        st.session_state.idx = 0
        st.toast("Reset to first text.")
