import streamlit as st

from utils.core import annotations_frame


st.title("《疯狂动物城》命名实践标注平台")
st.caption("English–Mandarin dubbing · naming practices · multimodal characterization")

items = st.session_state["items"]
annotations = annotations_frame(st.session_state["annotations"])
actor = st.session_state["actor_id"]
mine = (
    annotations[annotations["coder_id"].astype(str) == actor]
    if not annotations.empty and "coder_id" in annotations
    else annotations.iloc[0:0]
)

columns = st.columns(3)
columns[0].metric("语料条目", len(items))
columns[1].metric("当前人员已保存", len(mine))
columns[2].metric(
    "审核记录",
    len(st.session_state["reviews"]),
)

standard = st.session_state["annotation_standard"]
schema = st.session_state["schema"]
st.header("Codebook v2.1 Revised · Web Alignment Fix")
st.caption(
    f"版本 {schema['schema_version']} · {len(schema['fields'])} 个字段。"
    "原L2已撤销；L3至L6保留编号以维持审计追踪。"
)

with st.expander("适用范围、标注单位与角色", expanded=True, icon=":material/info:"):
    quick_start = standard["quick_start"]
    st.markdown(f"**适用范围**  \n{standard['scope']}")
    st.markdown(f"**最小标注单位**  \n{quick_start['minimum_unit']}")
    st.markdown(f"**流程**  \n{quick_start['workflow']}")
    st.markdown(f"**媒体访问规则**  \n{standard['media_policy']}")
    st.markdown("**角色与任务**")
    for role_name, role_text in quick_start["roles"].items():
        st.markdown(f"- **{role_name}**：{role_text}")

overview = standard.get("overview", {})
with st.expander("纳入、排除与Event切分规则", expanded=True, icon=":material/rule:"):
    if overview.get("status_glossary"):
        st.markdown("**统一状态值**")
        st.table([{"状态": row[0], "使用条件": row[1]} for row in overview["status_glossary"]])
    for title, key in (
        ("纳入标准", "inclusion_rules"),
        ("排除标准", "exclusion_rules"),
        ("Event切分规则", "event_split_rules"),
    ):
        st.markdown(f"**{title}**")
        for rule in overview.get(key, []):
            st.markdown(f"- {rule}")

st.caption("显示规则：红色字段标题表示Coder在相应条件成立时必须提交或核验；★表示核心分析字段，不等同于Coder责任。")

level_titles = {
    "L0": "候选语料与可追溯性",
    "L1": "命名实现与语言对应",
    "L3": "版本内多模态证据",
    "L4": "版本内人物刻画功能",
    "L5": "跨版本重构与结果",
    "L6": "语料与叙事聚合",
}
for level_id, title in level_titles.items():
    level_fields = [
        field for field in schema["fields"]
        if str(field.get("analytical_level", "")).split(maxsplit=1)[0] == level_id
    ]
    with st.expander(
        f"{level_id} · {title}（{len(level_fields)}个字段）",
        icon=":material/menu_book:",
    ):
        for field in level_fields:
            title_text = field["display_name"]
            if field.get("entry_role") in {"coder", "coder_verification"} and field.get("required_for_included_item"):
                title_text = f":red[{title_text}]"
            st.markdown(f"#### {title_text}  `{field['id']}`")
            if field.get("definition"):
                st.markdown(f"**定义：** {field['definition']}")
            if field.get("decision_rule"):
                st.markdown(f"**填写规则：** {field['decision_rule']}")
            if field.get("full_value_list"):
                st.markdown("**可选值：** " + " · ".join(field["full_value_list"]))
            for guide in field.get("value_guides", []):
                rows = [dict(zip(guide["headers"], row)) for row in guide["rows"]]
                if rows:
                    st.table(rows)
            if field.get("record_fields"):
                st.markdown("**Record结构：** " + " · ".join(field["record_fields"]))
            if field.get("record_example"):
                st.markdown("**完整Record示例：**")
                st.table([field["record_example"]])
            responsibility = "Coder必填／核验" if field.get("required_for_included_item") and field.get("entry_role") in {"coder", "coder_verification"} else field.get("entry_role")
            st.caption(f"字段类型：{field['field_type']} · 责任：{responsibility}")

role = st.session_state["role"]
if role == "Reviewer":
    st.info("你当前是Reviewer：核查证据链、材料适用性、字段逻辑和不确定性，不重做整份初标。", icon=":material/fact_check:")
elif role == "Researcher":
    st.info("你当前是Researcher：维护候选语料与来源，核验系统派生字段，并完成L5和L6。", icon=":material/science:")
else:
    st.info("你当前是Coder：依据Shared AV Window访问外部影片，核验预建Event并完成全部红色字段；网页不加载视频或Praat截图。", icon=":material/edit_note:")
