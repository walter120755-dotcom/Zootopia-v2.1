from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from utils.core import (
    annotations_frame,
    csv_bytes,
    derive_clip_duration,
    derive_intermodal_change_records,
    derive_temporal_values,
    derive_verbal_values,
    field_map,
    is_blank,
    record_constraint_errors,
)
from utils.ui import SOURCE_COLUMNS, field_widget, first_value, source_card


st.title("逐条标注")
items = st.session_state["items"]
if items.empty:
    st.warning("请先在“数据”页载入语料。")
    st.stop()

role = st.session_state["role"]
actor = st.session_state["actor_id"]
if role == "Reviewer":
    st.info("Reviewer请转到“审核”页。")
    st.stop()

count = len(items)
st.session_state["current_item"] = min(max(int(st.session_state["current_item"]), 0), count - 1)
with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="bottom"):
    if st.button("上一条", disabled=st.session_state["current_item"] == 0, icon=":material/arrow_back:"):
        st.session_state["current_item"] -= 1
        st.rerun()
    selected = st.selectbox(
        "选择条目",
        range(count),
        index=st.session_state["current_item"],
        format_func=lambda index: f"{index + 1}/{count} · {items.iloc[index]['event_id']}",
        key="coding_item_selector",
    )
    st.session_state["current_item"] = selected
    if st.button("下一条", disabled=st.session_state["current_item"] == count - 1, icon=":material/arrow_forward:"):
        st.session_state["current_item"] += 1
        st.rerun()

row = items.iloc[st.session_state["current_item"]]
event_id = str(row["event_id"])
source_card(row)
st.info(
    "网页不加载视频或Praat截图。请根据Shared AV Window，在项目授权的ST原片与TT普通话配音文件中核验音画。",
    icon=":material/movie_info:",
)

schema = st.session_state["schema"]
fmap = field_map(schema)
source_defaults = {
    field["id"]: str(row.get(field["id"], "")).strip()
    for field in schema["fields"]
    if field["id"] in row.index
}
legacy_defaults = {
    "speaker": first_value(row, SOURCE_COLUMNS["说话者"]),
    "addressee": first_value(row, SOURCE_COLUMNS["受话者"]),
    "target": first_value(row, SOURCE_COLUMNS["指称对象"]),
    "st_host_utterance": first_value(row, SOURCE_COLUMNS["ST host utterance"]),
    "tt_host_utterance": first_value(row, SOURCE_COLUMNS["TT host utterance"]),
    "st_naming_expression": first_value(row, SOURCE_COLUMNS["ST naming expression"]),
    "tt_naming_expression": first_value(row, SOURCE_COLUMNS["TT naming expression"]),
}
for field_id, value in legacy_defaults.items():
    if field_id not in source_defaults and value != "—":
        source_defaults[field_id] = value
event_overrides = st.session_state["event_overrides"].get(event_id, {})


def annotation_key_for(person: str) -> str:
    return f"{person}::{event_id}"


def current_annotation(person: str = actor) -> dict:
    return st.session_state["annotations"].get(annotation_key_for(person), {})


def assign_record_ids(values: dict) -> dict:
    prefixes = {
        "shared_visual_evidence_records": "VIS",
        "st_vocal_evidence_records": "ST-VOC",
        "tt_vocal_evidence_records": "TT-VOC",
        "st_intermodal_relation_records": "ST-IM",
        "tt_intermodal_relation_records": "TT-IM",
        "tt_synchrony_mismatch_records": "TT-SYNC",
        "intermodal_relation_change_records": "IMPAIR",
        "characterizing_outcome_records": "OUT",
    }
    normalized = dict(values)
    for field_id, prefix in prefixes.items():
        records = normalized.get(field_id)
        if not isinstance(records, list):
            continue
        columns = fmap.get(field_id, {}).get("record_fields", [])
        id_column = next(
            (name for name in ("record_id", "visual_record_id", "outcome_record_id", "intermodal_pair_id") if name in columns),
            None,
        )
        if not id_column:
            continue
        for index, record in enumerate(records, start=1):
            if not str(record.get(id_column, "")).strip():
                record[id_column] = f"{event_id}-{prefix}-{index:02d}"
    return normalized


def save_annotation(values: dict, *, person: str = actor, annotation_role: str = role) -> None:
    values = assign_record_ids(values)
    key = annotation_key_for(person)
    previous = st.session_state["annotations"].get(key, {})
    merged = {**source_defaults, **event_overrides, **previous, **values}
    duration = derive_clip_duration(merged)
    if duration is not None:
        merged["clip_duration"] = duration
    temporal = derive_temporal_values(merged)
    st.session_state["annotations"][key] = {
        **previous,
        "event_id": event_id,
        "coder_id": person,
        "role": annotation_role,
        "codebook_version": schema["schema_version"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **values,
        **({"clip_duration": duration} if duration is not None else {}),
        **temporal,
    }


def blank_fields(field_ids: list[str], values: dict) -> list[str]:
    return [fmap[field_id]["display_name"] for field_id in field_ids if is_blank(values.get(field_id))]


def render_fields(field_ids: list[str], existing: dict, prefix: str) -> dict:
    values: dict = {}
    if not field_ids:
        return values
    columns = st.columns(2)
    for index, field_id in enumerate(field_ids):
        with columns[index % 2]:
            values[field_id] = field_widget(fmap[field_id], existing, prefix)
    return values


def show_evidence(record: dict, field_ids: list[str]) -> None:
    for field_id in field_ids:
        value = record.get(field_id)
        if not is_blank(value):
            st.markdown(f"**{fmap[field_id]['display_name']}**")
            if isinstance(value, list):
                st.dataframe(pd.DataFrame(value), hide_index=True, width="stretch")
            else:
                st.write(value)


def download_my_annotations() -> None:
    all_annotations = annotations_frame(st.session_state["annotations"])
    if all_annotations.empty:
        return
    mine = all_annotations[all_annotations["coder_id"].astype(str) == actor]
    if not mine.empty:
        st.download_button(
            "下载我的标注CSV",
            csv_bytes(mine),
            f"{actor}_annotations.csv",
            "text/csv",
            icon=":material/download:",
        )


if role == "Coder":
    existing = {**source_defaults, **event_overrides, **current_annotation()}
    lock_key = annotation_key_for(actor)
    for flag, state_key in (
        ("_st_phase_locked", "st_phase_locks"),
        ("_tt_phase_locked", "tt_phase_locks"),
        ("_st_l4_locked", "st_l4_locks"),
        ("_tt_l4_locked", "tt_l4_locks"),
    ):
        if str(existing.get(flag, "")).lower() == "true":
            st.session_state[state_key].add(lock_key)

    st.subheader("L0 候选语料核验")
    inclusion_status = field_widget(fmap["inclusion_status"], existing, f"l0gate__{actor}__{event_id}")
    always_l0 = ["candidate_version_origin", "source_alignment_status", "source_verification_status"]
    conditional_l0: list[str] = []
    if inclusion_status == "Included":
        conditional_l0 = [
            "speaker", "target", "addressee", "target_cardinality",
            "shared_av_window_start", "shared_av_window_end", "av_window_verification",
        ]
    elif inclusion_status == "Excluded":
        conditional_l0 = ["exclusion_reason", "exclusion_note"]
    with st.form(f"l0_form__{actor}__{event_id}"):
        l0_values = render_fields(always_l0 + conditional_l0, existing, f"l0__{actor}__{event_id}")
        l0_saved = st.form_submit_button("保存L0决定", type="primary", icon=":material/save:")
    if l0_saved:
        values = {"inclusion_status": inclusion_status, **l0_values}
        errors = blank_fields(["candidate_version_origin", "source_alignment_status", "source_verification_status"], values)
        if inclusion_status == "Included":
            errors.extend(blank_fields([
                "speaker", "target", "target_cardinality", "shared_av_window_start",
                "shared_av_window_end", "av_window_verification",
            ], values))
        elif inclusion_status == "Excluded":
            errors.extend(blank_fields(["exclusion_reason"], values))
            if values.get("exclusion_reason") in {"Duplicate", "Other"} and is_blank(values.get("exclusion_note")):
                errors.append("L0.4 Exclusion Note")
        elif inclusion_status != "Pending Review":
            errors.append("L0.3 Inclusion Decision")
        if errors:
            st.error("以下字段尚未完成：" + "、".join(errors))
        else:
            save_annotation(values)
            st.success("L0决定已保存。")
            st.rerun()

    saved_status = str(current_annotation().get("inclusion_status", source_defaults.get("inclusion_status", "")))
    if saved_status == "Excluded":
        st.success("该Event已标记为Excluded；L1、L3和L4不会开放。")
        download_my_annotations()
        st.stop()
    if saved_status != "Included":
        st.warning("该Event尚未保存为Included。Pending Review项目不会进入L1、L3和L4。")
        download_my_annotations()
        st.stop()

    st.divider()
    st.subheader("ST阶段 · L1与L3")
    st_locked = lock_key in st.session_state["st_phase_locks"]
    if not st_locked:
        st_presence = field_widget(fmap["st_naming_presence"], existing, f"stgate__{actor}__{event_id}")
        visual_status = field_widget(fmap["shared_visual_evidence_status"], existing, f"visgate__{actor}__{event_id}")
        if st_presence == "Overt":
            st_vocal_status = field_widget(fmap["st_vocal_evidence_status"], existing, f"stvocgate__{actor}__{event_id}")
            st_intermodal_status = field_widget(fmap["st_intermodal_status"], existing, f"stimgate__{actor}__{event_id}")
        else:
            st_vocal_status = "Not Applicable No Overt"
            st_intermodal_status = "Not Applicable"
            st.caption("ST为No Overt时，ST Vocal与ST Intermodal自动设为Not Applicable；Head、Expression、Span、Basis和Treatment不显示。")

        st_ids = ["st_host_utterance", "st_characterizing_cotext"]
        if st_presence == "Overt":
            st_ids += [
                "st_naming_head", "st_naming_expression", "st_text_span", "st_naming_onset", "st_naming_offset",
                "st_realization_environment", "st_naming_bases", "st_interactional_treatment", "treatment_note",
            ]
        if visual_status == "One or More Material Visual Cues":
            st_ids.append("shared_visual_evidence_records")
        if st_vocal_status == "One or More Salient Vocal Cues":
            st_ids.append("st_vocal_evidence_records")
        if st_intermodal_status == "One or More Material Relations":
            st_ids.append("st_intermodal_relation_records")
        with st.form(f"st_phase_form__{actor}__{event_id}"):
            st_values = render_fields(st_ids, existing, f"stphase__{actor}__{event_id}")
            st_submitted = st.form_submit_button("保存并锁定ST L1／L3", type="primary", icon=":material/lock:")
        if st_submitted:
            values = {
                "st_naming_presence": st_presence,
                "shared_visual_evidence_status": visual_status,
                "st_vocal_evidence_status": st_vocal_status,
                "st_intermodal_status": st_intermodal_status,
                **st_values,
            }
            errors: list[str] = []
            if st_presence not in {"Overt", "No Overt"}:
                errors.append("ST Naming Presence必须解决为Overt或No Overt后才能锁定")
            errors.extend(blank_fields(["st_host_utterance", "st_characterizing_cotext", "shared_visual_evidence_status"], values))
            if st_presence == "Overt":
                errors.extend(blank_fields([
                    "st_naming_head", "st_naming_expression", "st_text_span", "st_naming_onset", "st_naming_offset",
                    "st_realization_environment", "st_naming_bases", "st_interactional_treatment",
                    "st_vocal_evidence_status", "st_intermodal_status",
                ], values))
            else:
                values.update({
                    "st_naming_head": "NULL_NO_OVERT", "st_naming_expression": "NULL_NO_OVERT",
                    "st_text_span": "", "st_naming_onset": "", "st_naming_offset": "",
                    "st_realization_environment": "Unclear／Not Applicable", "st_naming_bases": [],
                    "st_interactional_treatment": "Mixed／Unclear／Not Applicable",
                })
            errors.extend(record_constraint_errors(schema, values))
            if errors:
                st.error("ST阶段尚未完成：" + "、".join(errors))
            else:
                values["_st_phase_locked"] = True
                save_annotation(values)
                st.session_state["st_phase_locks"].add(lock_key)
                st.rerun()
    else:
        st.success("ST L1／L3已锁定，TT阶段已开放。", icon=":material/lock:")
        with st.expander("查看已锁定ST证据", icon=":material/visibility:"):
            show_evidence({**existing, **current_annotation()}, [
                "st_naming_presence", "st_naming_head", "st_naming_expression", "st_characterizing_cotext",
                "st_realization_environment", "st_naming_bases", "st_interactional_treatment",
                "shared_visual_evidence_records", "st_vocal_evidence_records", "st_intermodal_relation_records",
            ])

    if lock_key not in st.session_state["st_phase_locks"]:
        download_my_annotations()
        st.stop()

    existing = {**source_defaults, **event_overrides, **current_annotation()}
    st.subheader("TT阶段 · L1与L3及跨版本对应")
    tt_locked = lock_key in st.session_state["tt_phase_locks"]
    if not tt_locked:
        tt_presence = field_widget(fmap["tt_naming_presence"], existing, f"ttgate__{actor}__{event_id}")
        if tt_presence == "Overt":
            tt_vocal_status = field_widget(fmap["tt_vocal_evidence_status"], existing, f"ttvocgate__{actor}__{event_id}")
            tt_intermodal_status = field_widget(fmap["tt_intermodal_status"], existing, f"ttimgate__{actor}__{event_id}")
            tt_synchrony_status = field_widget(fmap["tt_synchrony_status"], existing, f"ttsyncgate__{actor}__{event_id}")
        else:
            tt_vocal_status = "Not Applicable No Overt"
            tt_intermodal_status = "Not Applicable"
            tt_synchrony_status = "Not Applicable No Overt"
            st.caption("TT为No Overt时，TT Vocal、TT Intermodal和Synchrony自动设为Not Applicable。")
        tt_ids = ["tt_host_utterance", "tt_characterizing_cotext", "host_verification", "cotext_verification"]
        if tt_presence == "Overt":
            tt_ids += [
                "tt_naming_head", "tt_naming_expression", "tt_text_span", "tt_naming_onset", "tt_naming_offset",
                "tt_realization_environment", "tt_naming_bases", "tt_interactional_treatment", "treatment_note",
            ]
        tt_ids += ["verbal_correspondence", "verbal_correspondence_note"]
        if tt_vocal_status == "One or More Salient Vocal Cues":
            tt_ids.append("tt_vocal_evidence_records")
        if tt_intermodal_status == "One or More Material Relations":
            tt_ids.append("tt_intermodal_relation_records")
        if tt_synchrony_status == "One or More Noticeable Mismatches":
            tt_ids.append("tt_synchrony_mismatch_records")
        with st.form(f"tt_phase_form__{actor}__{event_id}"):
            tt_values = render_fields(tt_ids, existing, f"ttphase__{actor}__{event_id}")
            tt_submitted = st.form_submit_button("保存并锁定TT L1／L3", type="primary", icon=":material/lock:")
        if tt_submitted:
            values = {
                "tt_naming_presence": tt_presence,
                "tt_vocal_evidence_status": tt_vocal_status,
                "tt_intermodal_status": tt_intermodal_status,
                "tt_synchrony_status": tt_synchrony_status,
                **tt_values,
            }
            errors: list[str] = []
            if tt_presence not in {"Overt", "No Overt"}:
                errors.append("TT Naming Presence必须解决为Overt或No Overt后才能锁定")
            errors.extend(blank_fields([
                "tt_host_utterance", "tt_characterizing_cotext", "host_verification",
                "cotext_verification", "verbal_correspondence",
            ], values))
            if tt_presence == "Overt":
                errors.extend(blank_fields([
                    "tt_naming_head", "tt_naming_expression", "tt_text_span", "tt_naming_onset", "tt_naming_offset",
                    "tt_realization_environment", "tt_naming_bases", "tt_interactional_treatment",
                    "tt_vocal_evidence_status", "tt_intermodal_status", "tt_synchrony_status",
                ], values))
            else:
                values.update({
                    "tt_naming_head": "NULL_NO_OVERT", "tt_naming_expression": "NULL_NO_OVERT",
                    "tt_text_span": "", "tt_naming_onset": "", "tt_naming_offset": "",
                    "tt_realization_environment": "Unclear／Not Applicable", "tt_naming_bases": [],
                    "tt_interactional_treatment": "Mixed／Unclear／Not Applicable",
                })
            errors.extend(record_constraint_errors(schema, values))
            if errors:
                st.error("TT阶段尚未完成：" + "、".join(errors))
            else:
                values["_tt_phase_locked"] = True
                save_annotation(values)
                st.session_state["tt_phase_locks"].add(lock_key)
                st.rerun()
    else:
        st.success("TT L1／L3已锁定，L4已开放。", icon=":material/lock:")
        with st.expander("System生成的Normalized Naming-span Alignment", icon=":material/timeline:"):
            st.json(derive_temporal_values({**existing, **current_annotation()}))

    if lock_key not in st.session_state["tt_phase_locks"]:
        download_my_annotations()
        st.stop()

    current_record = {**source_defaults, **event_overrides, **current_annotation()}
    st.subheader("L4 版本内人物刻画功能")
    st_l4_locked = lock_key in st.session_state["st_l4_locks"]
    if not st_l4_locked:
        with st.expander("已锁定的ST L1／L3 cues", expanded=True, icon=":material/visibility:"):
            show_evidence(current_record, [
                "st_naming_expression", "st_characterizing_cotext", "shared_visual_evidence_records",
                "st_vocal_evidence_records", "st_intermodal_relation_records",
            ])
        with st.form(f"st_l4_form__{actor}__{event_id}"):
            st_l4_status = field_widget(fmap["st_characterizing_function_status"], current_record, f"stl4__{actor}__{event_id}")
            st_l4_text = field_widget(fmap["st_characterizing_function"], current_record, f"stl4__{actor}__{event_id}")
            lock_submitted = st.form_submit_button("保存并锁定ST L4.1", type="primary", icon=":material/lock:")
        if lock_submitted:
            errors = []
            if is_blank(st_l4_status):
                errors.append("ST Characterizing Function Status")
            if st_l4_status == "Supported Local Function" and is_blank(st_l4_text):
                errors.append("ST Characterizing Function")
            if errors:
                st.error("以下字段尚未完成：" + "、".join(errors))
            else:
                save_annotation({
                    "st_characterizing_function_status": st_l4_status,
                    "st_characterizing_function": st_l4_text,
                    "_st_l4_locked": True,
                })
                st.session_state["st_l4_locks"].add(lock_key)
                st.rerun()
    else:
        st.success("ST L4.1已锁定，TT L4.2现已开放。", icon=":material/lock:")
        with st.expander("已锁定的TT L1／L3 cues", expanded=True, icon=":material/visibility:"):
            show_evidence(current_record, [
                "tt_naming_expression", "tt_characterizing_cotext", "shared_visual_evidence_records",
                "tt_vocal_evidence_records", "tt_intermodal_relation_records", "tt_synchrony_mismatch_records",
            ])
        tt_l4_locked = lock_key in st.session_state["tt_l4_locks"]
        if not tt_l4_locked:
            with st.form(f"tt_l4_form__{actor}__{event_id}"):
                tt_l4_status = field_widget(fmap["tt_characterizing_function_status"], current_record, f"ttl4__{actor}__{event_id}")
                tt_l4_text = field_widget(fmap["tt_characterizing_function"], current_record, f"ttl4__{actor}__{event_id}")
                tt_saved = st.form_submit_button("保存并锁定TT L4.2", type="primary", icon=":material/lock:")
            if tt_saved:
                errors = []
                if is_blank(tt_l4_status):
                    errors.append("TT Characterizing Function Status")
                if tt_l4_status == "Supported Local Function" and is_blank(tt_l4_text):
                    errors.append("TT Characterizing Function")
                if errors:
                    st.error("以下字段尚未完成：" + "、".join(errors))
                else:
                    save_annotation({
                        "tt_characterizing_function_status": tt_l4_status,
                        "tt_characterizing_function": tt_l4_text,
                        "_tt_l4_locked": True,
                    })
                    st.session_state["tt_l4_locks"].add(lock_key)
                    st.rerun()
        else:
            st.success("该Coder的L1至L4已经完成并锁定。")

else:
    st.subheader("Researcher元数据维护")
    researcher_key = annotation_key_for(actor)
    researcher_existing = {
        **source_defaults,
        **event_overrides,
        **st.session_state["annotations"].get(researcher_key, {}),
    }
    editable_metadata_ids = [
        field["id"] for field in schema["fields"]
        if field.get("entry_role") in {"researcher", "coder_verification"}
        and field["code"].split(".", 1)[0] in {"L0", "L1"}
        and field["id"] not in {"event_id", "clip_duration"}
    ]
    with st.expander("更正Researcher预填字段", icon=":material/edit_note:"):
        with st.form(f"researcher_metadata__{event_id}"):
            metadata_values = render_fields(editable_metadata_ids, researcher_existing, f"resmeta__{event_id}")
            metadata_saved = st.form_submit_button("保存元数据更正", type="primary", icon=":material/save:")
        if metadata_saved:
            duration = derive_clip_duration(metadata_values)
            if duration is not None:
                metadata_values["clip_duration"] = duration
            st.session_state["event_overrides"][event_id] = {**event_overrides, **metadata_values}
            save_annotation(metadata_values, annotation_role="Researcher")
            st.success("Researcher元数据更正已保存，并会作为Coder后续核验的最新预填值。")
            st.rerun()

    coder_records = [
        record for record in st.session_state["annotations"].values()
        if str(record.get("event_id")) == event_id and record.get("role") == "Coder"
    ]
    if not coder_records:
        st.warning("当前会话中没有该Event的Coder记录。L5必须从已完成的Coder记录生成；可先让Coder完成标注。")
    else:
        coder_ids = [str(record.get("coder_id", "unknown")) for record in coder_records]
        selected_coder = st.selectbox("选择L5依据的Coder记录", coder_ids, key=f"source_coder__{event_id}")
        coder_record = next(record for record in coder_records if str(record.get("coder_id")) == selected_coder)
        combined = {
            **source_defaults,
            **event_overrides,
            **coder_record,
            **st.session_state["annotations"].get(researcher_key, {}),
        }
        with st.expander("Coder已锁定的L1至L4证据", expanded=True, icon=":material/visibility:"):
            show_evidence(combined, [
                "st_naming_expression", "tt_naming_expression", "st_naming_bases", "tt_naming_bases",
                "st_interactional_treatment", "tt_interactional_treatment", "shared_visual_evidence_records",
                "st_vocal_evidence_records", "tt_vocal_evidence_records", "st_intermodal_relation_records",
                "tt_intermodal_relation_records", "tt_synchrony_mismatch_records",
                "st_characterizing_function", "tt_characterizing_function",
            ])
        if not coder_record.get("_tt_l4_locked"):
            st.warning("所选Coder记录尚未完成并锁定两侧L4；L5暂不开放。")
        else:
            system_suggestions = {
                **derive_verbal_values(combined),
                "intermodal_relation_change_records": derive_intermodal_change_records(combined, event_id),
                **derive_temporal_values(combined),
            }
            st.subheader("System派生与Researcher核验")
            st.caption("L3.5、L5.1和L5.2先生成可追溯建议；Researcher根据完整证据核验，不接受机械替代判断。")
            st.json({key: value for key, value in system_suggestions.items() if key != "intermodal_relation_change_records"})
            form_existing = dict(combined)
            for field_id, suggested_value in system_suggestions.items():
                if is_blank(form_existing.get(field_id)):
                    form_existing[field_id] = suggested_value
            researcher_ids = [
                field["id"] for field in schema["fields"]
                if field.get("entry_role") == "researcher"
                and field["code"].split(".", 1)[0] in {"L3", "L5", "L6"}
                and field["id"] not in {
                    "normalized_st_onset", "normalized_st_offset", "normalized_tt_onset", "normalized_tt_offset",
                    "temporal_iou", "temporal_comparability",
                }
            ]
            with st.form(f"researcher_analysis__{actor}__{event_id}"):
                researcher_values = render_fields(researcher_ids, form_existing, f"resanalysis__{actor}__{event_id}")
                researcher_saved = st.form_submit_button("保存Researcher L3.7／L5／L6", type="primary", icon=":material/save:")
            if researcher_saved:
                values = {"source_coder_id": selected_coder, **system_suggestions, **researcher_values}
                errors = record_constraint_errors(schema, values)
                if errors:
                    st.error("Researcher记录尚未完成：" + "、".join(errors))
                else:
                    save_annotation(values, annotation_role="Researcher")
                    st.success("Researcher记录已保存，并保留所依据的Coder ID。")

download_my_annotations()
