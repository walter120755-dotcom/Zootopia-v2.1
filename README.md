# Zootopia naming annotation platform v2.1 revised pilot

Streamlit annotation interface aligned with `Zootopia Codebook v2.1 Revised Pre-pilot`.

## Main changes

- One `Naming Event` now anchors one independently locatable naming-expression occurrence.
- Uses `event_id`, `source_candidate_id`, and optional `correspondence_group_id` instead of the old event-family model.
- Adds ST/TT Naming Head fields and applies the revised Naming Expression boundary rule.
- Treats Characterizing Co-text as Host Utterance with the current expression span replaced by `[…]`.
- Removes L2. Participants and Shared AV Window now sit in L0; L3–L6 numbering remains stable.
- Adds structured row editors for Visual, Vocal, Intermodal, Synchrony, and L5 records.
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

Items, annotations, and reviews live only in the active Streamlit session. Download CSV outputs before closing the browser tab or rebooting the app. `Coder`, `Reviewer`, and `Researcher` are workflow views, not authentication roles.
