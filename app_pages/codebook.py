import json

import streamlit as st

from utils.core import field_map, json_bytes, schema_errors
from utils.ui import field_card


st.title("Codebook查看与治理")
schema = st.session_state["schema"]
errors = schema_errors(schema)
if errors:
    st.error("当前codebook无效。")
    st.code("\n".join(errors))
else:
    st.success(f"验证通过：{len(schema['fields'])}个L0、L1、L3–L6字段；原L2已撤销。")

query = st.text_input("搜索字段、定义或填写规则", placeholder="例如component / synchrony / Naming Head")
provenance = st.multiselect(
    "来源性质",
    list(schema["provenance_classes"]),
    default=list(schema["provenance_classes"]),
)
filtered = [
    field for field in schema["fields"]
    if field.get("provenance_class") in provenance
    and query.lower() in " ".join(
        str(field.get(key, ""))
        for key in ("id", "display_name", "definition", "decision_rule")
    ).lower()
]
st.caption(f"显示 {len(filtered)} / {len(schema['fields'])} 个字段。")
for field in filtered:
    field_card(field)

st.subheader("导入、导出与单字段编辑")
uploaded = st.file_uploader("导入codebook JSON", type=["json"], key="schema_upload")
if uploaded:
    try:
        candidate = json.load(uploaded)
        candidate_errors = schema_errors(candidate)
        if candidate_errors:
            st.error("导入文件未通过验证。")
            st.code("\n".join(candidate_errors))
        elif st.button("应用到当前会话", type="primary"):
            st.session_state["schema"] = candidate
            st.success("Codebook已载入当前会话。")
            st.rerun()
    except Exception as exc:
        st.error(f"JSON读取失败：{exc}")

if st.session_state["role"] == "Researcher":
    ids = [field["id"] for field in schema["fields"]]
    selected = st.selectbox("选择要编辑的字段", ids)
    current = field_map(schema)[selected]
    with st.form(f"edit_schema__{selected}"):
        definition = st.text_area("Definition", value=current.get("definition", ""), height=90)
        values = st.text_area("Value list（每行一个）", value="\n".join(current.get("full_value_list", [])), height=130)
        rule = st.text_area("Decision rule", value=current.get("decision_rule", ""), height=110)
        apply_edit = st.form_submit_button("应用编辑并重新验证", type="primary")
    if apply_edit:
        replacement = {
            **current,
            "definition": definition,
            "full_value_list": [value.strip() for value in values.splitlines() if value.strip()],
            "decision_rule": rule,
            "theoretical_basis": "",
        }
        candidate = {
            **schema,
            "fields": [replacement if field["id"] == selected else field for field in schema["fields"]],
        }
        candidate_errors = schema_errors(candidate)
        if candidate_errors:
            st.error("编辑未应用，因为验证失败。")
            st.code("\n".join(candidate_errors))
        else:
            st.session_state["schema"] = candidate
            st.success("编辑已应用到当前会话；请下载JSON保存。")
            st.rerun()
else:
    st.caption("只有Researcher角色显示编辑表单；所有角色都可查看和导出。")

st.download_button(
    "下载当前codebook JSON",
    json_bytes(st.session_state["schema"]),
    "codebook_schema.json",
    "application/json",
    icon=":material/download:",
)

with st.expander("本版本的数据与媒体原则", icon=":material/policy:"):
    st.write(schema["analysis_scope"])
    st.write(schema["media_policy"])
