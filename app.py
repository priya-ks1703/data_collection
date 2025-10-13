# app.py
import io
import re
import csv
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import streamlit as st
from pathlib import Path

# =========================
# Configure your file paths
# =========================
PROMPTS_PATH = Path("data/original.csv")          # col1=index, col2=model, col3=prompt, col4=summary
COMPARISONS_PATH = Path("data/llama_outputs_summary.csv")  # TXT with "RANDOMIZED ORDER..." or CSV with a_model/a_index/b_model/b_index
PROGRESS_PATH: Optional[Path] = None             # e.g., Path("data/progress.csv") to resume; or leave None
AUTOSAVE_PATH: Optional[Path] = None             # e.g., Path("data/progress_autosave.csv")

# -------- Parsers & helpers -------- #
PAIR_PATTERN = re.compile(
    r"RANDOMIZED ORDER:\s*A:\s*(?P<a_model>[A-Za-z0-9_\-]+)\[(?P<a_idx>\d+)\]\s*,\s*B:\s*(?P<b_model>[A-Za-z0-9_\-]+)\[(?P<b_idx>\d+)\]",
    re.IGNORECASE,
)

def normalize_header(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def load_prompt_csv_from_text(text: str) -> Dict[Tuple[str, int], str]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("Prompts CSV is empty.")
    first = rows[0]
    has_header = False
    if first:
        c0 = first[0].strip()
        if not c0 or not c0.isdigit() or "index" in normalize_header(c0):
            has_header = True
    data_rows = rows[1:] if has_header else rows
    mapping: Dict[Tuple[str, int], str] = {}
    for row in data_rows:
        if len(row) < 4:  # Now we need at least 4 columns (index, model, prompt, summary)
            continue
        try:
            idx = int(row[0].strip())
        except Exception:
            continue
        model = row[1].strip()
        summary = row[3]  # Use summary column instead of prompt column
        mapping[(model, idx)] = summary
    return mapping

def parse_pairs_txt(txt: str) -> List[Dict]:
    pairs = []
    for m in PAIR_PATTERN.finditer(txt):
        pairs.append({
            "a_model": m.group("a_model"),
            "a_idx": int(m.group("a_idx")),
            "b_model": m.group("b_model"),
            "b_idx": int(m.group("b_idx")),
        })
    for i, p in enumerate(pairs):
        p["pair_id"] = i
    return pairs

def parse_model_index(item_str: str) -> Tuple[str, Optional[int]]:
    """Parse 'model[index]' format and return (model, index)"""
    import re
    match = re.match(r'([^[]+)\[(\d+)\]', item_str.strip())
    if match:
        return match.group(1), int(match.group(2))
    return "", None

def parse_pairs_csv(text: str) -> List[Dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Comparisons CSV missing header row.")
    header_map = {normalize_header(h): h for h in reader.fieldnames}
    def get(row, options):
        for k in options:
            if k in header_map:
                return (row.get(header_map[k]) or "").strip()
        return ""
    pairs: List[Dict] = []
    
    for row in reader:
        # First try the new format with Item_A and Item_B
        item_a = get(row, ["item_a", "itema"])
        item_b = get(row, ["item_b", "itemb"])
        
        if item_a and item_b:
            # Parse model[index] format
            a_model, a_idx = parse_model_index(item_a)
            b_model, b_idx = parse_model_index(item_b)
            
            # Get summaries if available
            summary_a = get(row, ["summary_a", "summarya"])
            summary_b = get(row, ["summary_b", "summaryb"])
            
            if a_model and b_model and a_idx is not None and b_idx is not None:
                pair_data = {"a_model": a_model, "a_idx": a_idx, "b_model": b_model, "b_idx": b_idx}
                if summary_a:
                    pair_data["a_summary"] = summary_a
                if summary_b:
                    pair_data["b_summary"] = summary_b
                pairs.append(pair_data)
        else:
            # Fallback to old format
            a_model = get(row, ["amodel", "a", "amodelname"])
            b_model = get(row, ["bmodel", "b", "bmodelname"])
            a_idx_s = get(row, ["aindex", "aidx", "a_index", "a_idx"])
            b_idx_s = get(row, ["bindex", "bidx", "b_index", "b_idx"])
            if not (a_model and b_model and a_idx_s and b_idx_s):
                continue
            try:
                a_idx = int(a_idx_s); b_idx = int(b_idx_s)
            except Exception:
                continue
            pairs.append({"a_model": a_model, "a_idx": a_idx, "b_model": b_model, "b_idx": b_idx})
    
    for i, p in enumerate(pairs):
        p["pair_id"] = i
    return pairs

def attach_prompts(pairs: List[Dict], prompt_map: Dict[Tuple[str, int], str]) -> List[Dict]:
    out = []
    for p in pairs:
        # Use summaries from CSV if available, otherwise look up from prompt_map
        a_prompt = p.get("a_summary") or prompt_map.get((p["a_model"], p["a_idx"]))
        b_prompt = p.get("b_summary") or prompt_map.get((p["b_model"], p["b_idx"]))
        
        out.append({
            **p,
            "a_prompt": a_prompt,
            "b_prompt": b_prompt
        })
    return out

def load_progress_csv(text: str) -> List[Dict]:
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        try:
            pid = int((row.get("pair_id") or "").strip())
        except Exception:
            pid = None
        out.append({
            "pair_id": pid,
            "a_model": (row.get("a_model") or "").strip(),
            "a_index": int((row.get("a_index") or "0").strip() or 0),
            "b_model": (row.get("b_model") or "").strip(),
            "b_index": int((row.get("b_index") or "0").strip() or 0),
            "choice": (row.get("choice") or "").strip(),
            "timestamp": (row.get("timestamp") or "").strip(),
        })
    return out

def merge_existing_choices(pairs: List[Dict], progress: List[Dict]) -> Dict[int, Dict]:
    by_pair_id, by_sig = {}, {}
    for r in progress:
        sig = (r["a_model"], r["a_index"], r["b_model"], r["b_index"])
        if r["pair_id"] is not None:
            by_pair_id[r["pair_id"]] = r
        by_sig[sig] = r
    choices = {}
    for p in pairs:
        sig = (p["a_model"], p["a_idx"], p["b_model"], p["b_idx"])
        if p["pair_id"] in by_pair_id:
            choices[p["pair_id"]] = by_pair_id[p["pair_id"]]
        elif sig in by_sig:
            choices[p["pair_id"]] = by_sig[sig]
    return choices

def export_progress_csv(pairs: List[Dict], choices: Dict[int, Dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["pair_id","a_model","a_index","b_model","b_index","choice","timestamp","a_prompt","b_prompt"])
    for p in pairs:
        ch = choices.get(p["pair_id"], {})
        w.writerow([
            p["pair_id"], p["a_model"], p["a_idx"], p["b_model"], p["b_idx"],
            ch.get("choice",""), ch.get("timestamp",""),
            (p.get("a_prompt") or ""), (p.get("b_prompt") or "")
        ])
    return buf.getvalue().encode("utf-8")

def first_unanswered_index(pairs: List[Dict], choices: Dict[int, Dict]) -> int:
    for p in pairs:
        if p["pair_id"] not in choices or not choices[p["pair_id"]].get("choice"):
            return p["pair_id"]
    return len(pairs)

def autosave_if_enabled(pairs, choices):
    if AUTOSAVE_PATH:
        AUTOSAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTOSAVE_PATH.write_bytes(export_progress_csv(pairs, choices))

# -------- UI -------- #
st.set_page_config(page_title="A/B Output Chooser", page_icon="🗂️", layout="wide")
st.title("A/B Output Chooser")

# Session state
if "pairs" not in st.session_state: st.session_state.pairs = []
if "choices" not in st.session_state: st.session_state.choices = {}
if "current" not in st.session_state: st.session_state.current = 0
if "uploaded_progress_text" not in st.session_state: st.session_state.uploaded_progress_text = None

# In-page progress upload (optional). If provided, it overrides PROGRESS_PATH.
st.markdown("#### Continue from a progress file (optional)")
prog_upload = st.file_uploader("Upload progress CSV to resume", type=["csv"], key="progress_uploader_main")
if prog_upload is not None:
    st.session_state.uploaded_progress_text = prog_upload.read().decode("utf-8", errors="replace")

# ===== Auto-load data (no button) =====
def build_or_refresh_state():
    # Must have prompts and comparisons available by default
    if not PROMPTS_PATH.exists():
        st.error(f"Prompts file not found: {PROMPTS_PATH}")
        st.stop()
    if not COMPARISONS_PATH.exists():
        st.error(f"Comparisons file not found: {COMPARISONS_PATH}")
        st.stop()

    # Load prompts
    prompt_map = load_prompt_csv_from_text(read_text(PROMPTS_PATH))

    # Load comparisons (TXT or CSV)
    comp_text = read_text(COMPARISONS_PATH)
    pairs: List[Dict] = []
    if COMPARISONS_PATH.suffix.lower() == ".csv":
        try:
            pairs = parse_pairs_csv(comp_text)
        except Exception:
            pairs = []
    if not pairs:
        pairs = parse_pairs_txt(comp_text) or parse_pairs_csv(comp_text)

    if not pairs:
        st.error("No pairs found in comparisons file.")
        st.stop()

    pairs = attach_prompts(pairs, prompt_map)

    # Merge progress:
    merged_from_file: Dict[int, Dict] = {}
    if st.session_state.uploaded_progress_text:
        try:
            existing = load_progress_csv(st.session_state.uploaded_progress_text)
            merged_from_file = merge_existing_choices(pairs, existing)
            st.success(f"Loaded prior progress (uploaded): {len([r for r in merged_from_file.values() if r.get('choice')])}")
        except Exception as e:
            st.warning(f"Could not read uploaded progress: {e}")
    elif PROGRESS_PATH and PROGRESS_PATH.exists():
        try:
            existing = load_progress_csv(read_text(PROGRESS_PATH))
            merged_from_file = merge_existing_choices(pairs, existing)
            st.success(f"Loaded prior progress (file): {len([r for r in merged_from_file.values() if r.get('choice')])}")
        except Exception as e:
            st.warning(f"Could not read progress file: {e}")

    # Keep any in-session choices (take precedence over file)
    choices = {**merged_from_file, **st.session_state.get("choices", {})}

    st.session_state.pairs = pairs
    st.session_state.choices = choices
    st.session_state.current = first_unanswered_index(pairs, choices)

# Always refresh the working set automatically (no button)
build_or_refresh_state()

pairs = st.session_state.pairs
choices = st.session_state.choices
current = st.session_state.current

# ===== Main panel =====
if current >= len(pairs):
    st.success("All pairs completed. You can still download your progress.")
else:
    p = pairs[current]
    # st.subheader(f"Pair {current + 1} of {len(pairs)}")
    # c1, c2, c3 = st.columns(3)
    # with c1: st.write(f"**A:** {p['a_model']}[{p['a_idx']}]")
    # with c2: st.write(f"**B:** {p['b_model']}[{p['b_idx']}]")
    # with c3: st.write(f"**Pair ID:** {p['pair_id']}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### A")
        if p.get("a_prompt") is None:
            st.error(f"Prompt not found for {p['a_model']}[{p['a_idx']}] in CSV.")
        else:
            st.text_area("Prompt A", value=p["a_prompt"], height=280, key=f"prompt_a_{current}", label_visibility="collapsed")
    with col_b:
        st.markdown("### B")
        if p.get("b_prompt") is None:
            st.error(f"Prompt not found for {p['b_model']}[{p['b_idx']}] in CSV.")
        else:
            st.text_area("Prompt B", value=p["b_prompt"], height=280, key=f"prompt_b_{current}", label_visibility="collapsed")

    # Only A and B buttons
    act_cols = st.columns([1, 1])
    def record_choice(choice_value: str):
        choices[p["pair_id"]] = {
            "pair_id": p["pair_id"],
            "a_model": p["a_model"],
            "a_index": p["a_idx"],
            "b_model": p["b_model"],
            "b_index": p["b_idx"],
            "choice": choice_value,  # "A" or "B"
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        st.session_state.choices = choices
        st.session_state.current = first_unanswered_index(pairs, choices)
        autosave_if_enabled(pairs, choices)

    with act_cols[0]:
        if st.button("Choose A", use_container_width=True):
            record_choice("A"); st.rerun()
    with act_cols[1]:
        if st.button("Choose B", use_container_width=True):
            record_choice("B"); st.rerun()

st.markdown("---")
st.subheader("Progress")
completed = sum(1 for pid in range(len(pairs)) if choices.get(pid, {}).get("choice"))
st.write(f"Completed: **{completed} / {len(pairs)}**")

export_bytes = export_progress_csv(pairs, choices)
st.download_button(
    "Download progress CSV",
    data=export_bytes,
    file_name="ab_progress.csv",
    mime="text/csv",
)

# if completed:
#     recent = []
#     for pid in reversed(range(len(pairs))):
#         if choices.get(pid, {}).get("choice"):
#             recent.append({"pair_id": pid, "choice": choices[pid]["choice"]})
#         if len(recent) >= 10:
#             break
#     st.caption("Recent decisions (latest 10):")
#     st.table(recent)

# with st.expander("File format notes"):
#     st.write(
#         "- **Prompts CSV:** column1=index (int), column2=model (str), column3=prompt (str)\n"
#         "- **Comparisons TXT:** lines like `RANDOMIZED ORDER: A: gpt[47], B: llama[85]`\n"
#         "- **Comparisons CSV (alternative):** headers `a_model,a_index,b_model,b_index` (or `a_idx/b_idx`)\n"
#         "- **Progress CSV:** upload above or set PROGRESS_PATH to resume"
#     )
