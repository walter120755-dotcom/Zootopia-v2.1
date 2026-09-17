from __future__ import annotations

import streamlit as st

from utils.core import (
    annotations_frame,
    csv_bytes,
    field_map,
    fields_by_level,
    fields_for_role,
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
    st.info("Reviewer请转到“审核”页；此页用于Coder初标和Researcher字段填写。")
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
    "网页不加载视频或Praat截图。请根据Shared AV Window，在项目授权的ST原片与TT普通话配音文件中核验音画；"
    "Praat只在Researcher提出具体核验请求后于网页外使用。",
    icon=":material/movie_info:",
)

annotation_key = f"{actor}::{event_id}"
source_defaults = {
    field["id"]: str(row.get(field["id"], "")).strip()
    for field in st.session_state["schema"]["fields"]
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
existing = {**source_defaults, **st.session_state["annotations"].get(annotation_key, {})}
fields = fields_for_role(st.session_state["schema"], role)


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
        "support_redistribution_records": "SUP",
    }
    fmap = field_map(st.session_state["schema"])
    normalized = dict(values)
    for field_id, prefix in prefixes.items():
        records = normalized.get(field_id)
        if not isinstance(records, list):
            continue
        columns = fmap.get(field_id, {}).get("record_fields", [])
        id_column = next((name for name in ("record_id", "visual_record_id", "outcome_record_id", "intermodal_pair_id") if name in columns), None)
        if not id_column:
            continue
        for index, record in enumerate(records, start=1):
            if not str(record.get(id_column, "")).strip():
                record[id_column] = f"{event_id}-{prefix}-{index:02d}"
    return normalized


def derived_temporal_values(values: dict) -> dict:
    merged = {**existing, **values}
    try:
        duration = float(merged.get("clip_duration", ""))
        s0, s1 = float(merged.get("st_naming_onset", "")), float(merged.get("st_naming_offset", ""))
        t0, t1 = float(merged.get("tt_naming_onset", "")), float(merged.get("tt_naming_offset", ""))
        if duration <= 0 or s1 < s0 or t1 < t0:
            raise ValueError
    except (TypeError, ValueError):
        return {}
    intersection = max(0.0, min(s1, t1) - max(s0, t0))
    union = max(s1, t1) - min(s0, t0)
    return {
        "normalized_st_onset": round(s0 / duration, 6),
        "normalized_st_offset": round(s1 / duration, 6),
        "normalized_tt_onset": round(t0 / duration, 6),
        "normalized_tt_offset": round(t1 / duration, 6),
        "temporal_iou": round(intersection / union, 6) if union > 0 else 1.0,
        "temporal_comparability": "Comparable",
    }


def save_values(values: dict) -> None:
    values = assign_record_ids(values)
    previous = st.session_state["annotations"].get(annotation_key, {})
    st.session_state["annotations"][annotation_key] = {
        **previous,
        "event_id": event_id,
        "coder_id": actor,
        "role": role,
        "codebook_version": st.session_state["schema"]["schema_version"],
        **values,
        **derived_temporal_values(values),
    }


if role == "Coder":
    l4_ids = {
        "st_characterizing_function_status", "st_characterizing_function",
        "tt_characterizing_function_status", "tt_characterizing_function",
    }
    base_fields = [field for field in fields if field["id"] not in l4_ids]
    st.subheader("L0、L1与L3编码表")
    st.caption("星号表示Included Event的Coder必填或核验字段。结构化Record表可增删行，空record_id会在保存时自动生成。")
    with st.form(f"coding_form__{actor}__{event_id}"):
        base_values = {}
        for level, level_fields in fields_by_level(base_fields).items():
            with st.expander(level, expanded=level in {"L0", "L1"}, icon=":material/layers:"):
                columns = st.columns(2)
                for index, field in enumerate(level_fields):
                    with columns[index % 2]:
                        base_values[field["id"]] = field_widget(field, existing, f"ann__{actor}__{event_id}")
        base_saved = st.form_submit_button("保存L0、L1与L3", type="primary", icon=":material/save:")

    if base_saved:
        status = base_values.get("inclusion_status") or existing.get("inclusion_status", "")
        errors = []
        if status == "Included":
            errors.extend(
                field["display_name"] for field in base_fields
                if field.get("required_for_included_item") and is_blank(base_values.get(field["id"]))
            )
            errors.extend(record_constraint_errors(st.session_state["schema"], base_values))
        elif status == "Excluded" and is_blank(base_values.get("exclusion_reason")):
            errors.append("L0.4 Exclusion Reason")
        if errors:
            st.error("以下字段或结构尚未完成：" + "、".join(errors))
        else:
            save_values(base_values)
            st.success("已保存L0、L1与L3。")

    st.subheader("L4 版本内人物刻画功能")
    current_record = {**existing, **st.session_state["annotations"].get(annotation_key, {})}
    with st.expander("已记录的L1–L3 cues", expanded=True, icon=":material/visibility:"):
        cue_ids = [
            "st_naming_expression", "tt_naming_expression", "st_characterizing_cotext", "tt_characterizing_cotext",
            "shared_visual_evidence_records", "st_vocal_evidence_records", "tt_vocal_evidence_records",
            "st_intermodal_relation_records", "tt_intermodal_relation_records", "tt_synchrony_mismatch_records",
        ]
        for cue_id in cue_ids:
            value = current_record.get(cue_id)
            if not is_blank(value):
                st.markdown(f"**{cue_id}**")
                st.write(value)

    fmap = field_map(st.session_state["schema"])
    st_status_field = fmap["st_characterizing_function_status"]
    st_text_field = fmap["st_characterizing_function"]
    tt_status_field = fmap["tt_characterizing_function_status"]
    tt_text_field = fmap["tt_characterizing_function"]
    lock_key = f"{actor}::{event_id}"
    locked = lock_key in st.session_state["st_l4_locks"]

    if not locked:
        with st.form(f"st_l4_form__{actor}__{event_id}"):
            st_l4_status = field_widget(st_status_field, current_record, f"stl4__{actor}__{event_id}")
            st_l4_text = field_widget(st_text_field, current_record, f"stl4__{actor}__{event_id}")
            lock_submitted = st.form_submit_button("保存并锁定ST L4.1", type="primary", icon=":material/lock:")
        if lock_submitted:
            if is_blank(st_l4_status):
                st.error("必须选择ST Characterizing Function Status。")
            elif st_l4_status == "Supported Local Function" and is_blank(st_l4_text):
                st.error("Supported Local Function必须填写一至两句Characterizing Function。")
            else:
                save_values({
                    "st_characterizing_function_status": st_l4_status,
                    "st_characterizing_function": st_l4_text,
                })
                st.session_state["st_l4_locks"].add(lock_key)
                st.rerun()
    else:
        st.success("ST L4.1已锁定，TT L4.2现已开放。", icon=":material/lock:")
        st.text_area(
            "已锁定的ST Characterizing Function",
            value=str(st.session_state["annotations"].get(annotation_key, {}).get("st_characterizing_function", "")),
            disabled=True,
        )
        with st.form(f"tt_l4_form__{actor}__{event_id}"):
            tt_l4_status = field_widget(tt_status_field, current_record, f"ttl4__{actor}__{event_id}")
            tt_l4_text = field_widget(tt_text_field, current_record, f"ttl4__{actor}__{event_id}")
            tt_saved = st.form_submit_button("保存TT L4.2", type="primary", icon=":material/save:")
        if tt_saved:
            if is_blank(tt_l4_status):
                st.error("必须选择TT Characterizing Function Status。")
            elif tt_l4_status == "Supported Local Function" and is_blank(tt_l4_text):
                st.error("Supported Local Function必须填写一至两句Characterizing Function。")
            else:
                save_values({
                    "tt_characterizing_function_status": tt_l4_status,
                    "tt_characterizing_function": tt_l4_text,
                })
                st.success("已保存TT L4.2。")
else:
    st.subheader("Researcher字段")
    st.caption("用于语料来源、系统派生结果、L5跨版本综合和L6聚合；不会反向覆盖Coder证据字段。")
    with st.form(f"researcher_form__{actor}__{event_id}"):
        researcher_values = {}
        for level, level_fields in fields_by_level(fields).items():
            with st.expander(level, expanded=level in {"L5", "L6"}, icon=":material/layers:"):
                columns = st.columns(2)
                for index, field in enumerate(level_fields):
                    with columns[index % 2]:
                        researcher_values[field["id"]] = field_widget(field, existing, f"res__{actor}__{event_id}")
        researcher_saved = st.form_submit_button("保存Researcher记录", type="primary", icon=":material/save:")
    if researcher_saved:
        save_values(researcher_values)
        st.success("已保存Researcher记录。")

all_annotations = annotations_frame(st.session_state["annotations"])
mine = all_annotations[all_annotations["coder_id"].astype(str) == actor] if not all_annotations.empty else all_annotations
if not mine.empty:
    st.download_button(
        "下载我的标注CSV",
        csv_bytes(mine),
        f"{actor}_annotations.csv",
        "text/csv",
        icon=":material/download:",
    )
