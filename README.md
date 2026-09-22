# Zootopia naming annotation platform v2.1 Web Alignment Fix

Streamlit annotation interface aligned with `Zootopia Codebook v2.1 Revised`.

## Alignment fixes

- One `Naming Event` now anchors one independently locatable naming-expression occurrence.
- Uses `event_id`, `source_candidate_id`, and optional `correspondence_group_id` instead of the old event-family model.
- Adds ST/TT Naming Head fields and applies the revised Naming Expression boundary rule.
- Treats Characterizing Co-text as Host Utterance with the current expression span replaced by `[…]`.
- Removes L2. Participants and Shared AV Window now sit in L0; L3–L6 numbering remains stable.
- Enforces the Codebook workflow: L0 gate → locked ST L1/L3 → locked TT L1/L3 → locked ST L4 → locked TT L4 → Researcher L5/L6.
- Hides downstream fields for `Excluded` and `Pending Review`; applies the `No Overt Naming Expression` branches separately to ST and TT.
- Adds controlled structured-record editors and record-level validation for Visual, Vocal, Intermodal, Synchrony, L5, and L6 records.
- Shows Coder evidence to the Researcher and generates reviewable suggestions for L3.5, L5.1, and L5.2.
- Uses the Codebook's `Revision Targets` in the Reviewer workflow.
- Reports nominal agreement, multi-label Jaccard/set F1, and temporal span IoU by field type.
- Keeps video, video URL, and Praat-image panels out of the app. Media are checked externally from the Shared AV Window.
- Keeps the XLSX fallback reader for deployments where `openpyxl` is temporarily unavailable.

## Input workbook

Upload the provided `Zootopia_元数据语料_v2.1_revised_pilot.xlsx` and select `Annotation_Items`.

Minimum recommended columns:

- `event_id`
- `source_candidate_id`
- `candidate_version_origin`
- `shared_av_window_start`
- `shared_av_window_end`
- `speaker`, `target`, `addressee`, `target_cardinality`
- `st_host_utterance`, `tt_host_utterance`
- `st_naming_head`, `tt_naming_head`
- `st_naming_expression`, `tt_naming_expression`
- `st_characterizing_cotext`, `tt_characterizing_cotext`

The app preserves additional columns. Do not upload videos or Praat screenshots.

## Local run

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

## Streamlit Community Cloud

1. Upload the contents of this ZIP to the repository root.
2. Set `app.py` as the entry point.
3. Set Python to 3.11. The included `runtime.txt` already requests `python-3.11`.
4. Reboot the app after replacing repository files.

## Persistence

Items, annotations, reviews, stage locks, and Researcher corrections live only in the active Streamlit session. Download CSV outputs before closing the browser tab or rebooting the app. `Coder`, `Reviewer`, and `Researcher` are workflow views, not authentication roles. A persistent multi-user deployment still requires an authenticated database-backed version.
