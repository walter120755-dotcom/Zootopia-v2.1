from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from utils.core import parse_multi, parse_records


SOURCE_COLUMNS = {
    "AV start": ["shared_av_window_start", "av_event_window", "AV Event Window", "Timecode", "Timestamp"],
    "AV end": ["shared_av_window_end"],
    "说话者": ["speaker", "Speaker"],
    "受话者": ["addressee", "Addressee"],
    "指称对象": ["target", "Target"],
    "ST naming expression": ["st_naming_expression", "ST Naming Expression", "ST naming instance", "ST naming practice"],
    "TT naming expression": ["tt_naming_expression", "TT Naming Expression", "TT rendering", "TT Rendering"],
    "ST host utterance": ["st_host_utterance", "ST Host Utterance", "Local context / source line"],
    "TT host utterance": ["tt_host_utterance", "TT Host Utterance"],
}


def first_value(row, names: list[str]) -> str:
    for name in names:
        value = str(row.get(name, "")).strip()
        if value and value.lower() != "nan":
            return value
    return "—"


def source_card(row) -> None:
    st.subheader("当前 naming event")
    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.badge(f"ID: {row.get('event_id', '—')}", color="blue")
            start = first_value(row, SOURCE_COLUMNS["AV start"])
            end = first_value(row, SOURCE_COLUMNS["AV end"])
            window = start if end == "—" or "-" in start else f"{start}–{end}"
            st.caption(f"Shared AV window：{window}")
            source_candidate = str(row.get("source_candidate_id", "")).strip()
            if source_candidate:
                st.caption(f"Source candidate：{source_candidate}")
        st.caption(
            "说话者 → 受话者；Target："
            f"{first_value(row, SOURCE_COLUMNS['说话者'])} → "
            f"{first_value(row, SOURCE_COLUMNS['受话者'])}；"
            f"{first_value(row, SOURCE_COLUMNS['指称对象'])}"
        )
        columns = st.columns(2)
        with columns[0].container(border=True, height="stretch"):
            st.caption("ST naming expression")
            st.write(first_value(row, SOURCE_COLUMNS["ST naming expression"]))
            st.caption("ST host utterance")
            st.write(first_value(row, SOURCE_COLUMNS["ST host utterance"]))
        with columns[1].container(border=True, height="stretch"):
            st.caption("TT naming expression")
            st.write(first_value(row, SOURCE_COLUMNS["TT naming expression"]))
            st.caption("TT host utterance")
            st.write(first_value(row, SOURCE_COLUMNS["TT host utterance"]))
        heads = st.columns(2)
        with heads[0]:
            st.caption("ST naming head")
            st.write(str(row.get("st_naming_head", "")).strip() or "—")
        with heads[1]:
            st.caption("TT naming head")
            st.write(str(row.get("tt_naming_head", "")).strip() or "—")


def field_help(field: dict[str, Any]) -> str:
    definition = field.get("definition", "") or "见codebook。"
    rule = field.get("decision_rule", "") or "按定义填写。"
    example = ""
    guides = field.get("value_guides", [])
    if guides and guides[0].get("rows"):
        row = guides[0]["rows"][0]
        if len(row) >= 3:
            example = f"\n\n示例：{row[0]} — {row[2]}"
    role = field.get("entry_role", "unknown")
    return f"定义：{definition}\n\n填写：{rule}\n\n责任：{role}{example}"


def field_label(field: dict[str, Any]) -> str:
    label = field["display_name"]
    if field.get("entry_role") in {"coder", "coder_verification"} and field.get("required_for_included_item"):
        return f":red[{label}]"
    return label


def field_widget(field: dict[str, Any], existing: dict[str, Any], key_prefix: str):
    field_id = field["id"]
    key = f"{key_prefix}__{field_id}"
    label = field_label(field)
    field_type = field["field_type"]
    current = existing.get(field_id, []) if field_type == "controlled_multi" else existing.get(field_id, "")
    options = field.get("full_value_list", [])
    if field_type == "controlled_single":
        choices = [""] + options
        index = choices.index(current) if current in choices else 0
        return st.selectbox(label, choices, index=index, help=field_help(field), key=key)
    if field_type == "controlled_multi":
        default = [value for value in parse_multi(current) if value in options]
        return st.multiselect(label, options, default=default, help=field_help(field), key=key)
    if field_type == "record_list":
        columns = field.get("record_fields", [])
        records = parse_records(current, columns)
        column_types = field.get("record_column_types", {})
        value_lists = field.get("record_value_lists", {})
        required = set(field.get("required_record_fields", []))
        disabled = set(field.get("disabled_record_fields", []))
        if records:
            frame = pd.DataFrame(records, columns=columns)
        else:
            frame = pd.DataFrame({column: pd.Series(dtype="object") for column in columns})
        for column, column_type in column_types.items():
            if column_type == "multiselect" and column in frame:
                frame[column] = frame[column].map(lambda value: value if isinstance(value, list) else parse_multi(value))
        st.markdown(f"**{label}**")
        st.caption(field_help(field))
        configs: dict[str, Any] = {}
        for column in columns:
            column_type = column_types.get(column, "text")
            common = {
                "label": column,
                "required": column in required,
                "disabled": column in disabled,
            }
            if column_type == "select":
                configs[column] = st.column_config.SelectboxColumn(
                    **common,
                    options=value_lists.get(column, []),
                )
            elif column_type == "multiselect":
                configs[column] = st.column_config.MultiselectColumn(
                    **common,
                    options=value_lists.get(column, []),
                    accept_new_options=False,
                    color="primary",
                )
            else:
                configs[column] = st.column_config.TextColumn(**common)
        edited = st.data_editor(
            frame,
            key=key,
            hide_index=True,
            num_rows="dynamic",
            width="stretch",
            column_config=configs,
        )
        cleaned = []
        for row in edited.to_dict("records"):
            result: dict[str, Any] = {}
            for column in columns:
                value = row.get(column, "")
                if column_types.get(column) == "multiselect":
                    result[column] = [str(item).strip() for item in (value or []) if str(item).strip()]
                else:
                    result[column] = str(value or "").strip()
            if any(value if isinstance(value, list) else str(value).strip() for value in result.values()):
                cleaned.append(result)
        return cleaned
    if field_type == "decimal":
        return st.text_input(label, value=str(current), help=field_help(field), key=key, placeholder="例如 1.25")
    if field_type == "long_text":
        return st.text_area(label, value=str(current), height=120, help=field_help(field), key=key)
    return st.text_input(label, value=str(current), help=field_help(field), key=key)


def field_card(field: dict[str, Any]) -> None:
    provenance = field.get("provenance_class", "unknown")
    color = {
        "source-derived": "green",
        "data-driven": "orange",
        "project-governance": "gray",
    }.get(provenance, "gray")
    with st.container(border=True):
        with st.container(horizontal=True):
            st.subheader(field["display_name"])
            st.badge(provenance, color=color)
            st.badge(field.get("entry_role", "unknown"), color="gray")
        st.write(field.get("definition", ""))
        if field.get("decision_rule"):
            st.markdown(f"**填写规则：** {field['decision_rule']}")
        if field.get("full_value_list"):
            st.markdown("**值域：** " + " · ".join(field["full_value_list"]))
        for guide in field.get("value_guides", []):
            rows = [dict(zip(guide["headers"], row)) for row in guide["rows"]]
            if rows:
                st.table(rows)
        if field.get("record_fields"):
            st.markdown("**Record结构：** " + " · ".join(field["record_fields"]))
        if field.get("record_example"):
            st.markdown("**完整Record示例：**")
            st.table([field["record_example"]])
