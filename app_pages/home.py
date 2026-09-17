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
st.header("Codebook v2.1 Revised · Pre-pilot")
st.caption(
    f"版本 {standard['version']} · {standard['field_count']} 个字段。"
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

for level in standard["levels"]:
    with st.expander(
        f"{level['id']} · {level['title_zh']}（{len(level['fields'])}个字段）",
        icon=":material/menu_book:",
    ):
        for field in level["fields"]:
            st.markdown(f"#### {field['display_name']}  `{field['id']}`")
            if field["definition_zh"]:
                st.markdown(f"**定义：** {field['definition_zh']}")
            if field["fill_zh"]:
                st.markdown(f"**填写规则：** {field['fill_zh']}")
            if field["options"]:
                st.markdown("**可选值：** " + " · ".join(field["options"]))
            for guide in field.get("value_guides", []):
                rows = [dict(zip(guide["headers"], row)) for row in guide["rows"]]
                if rows:
                    st.table(rows)
            required = "Coder必填／核验" if field["required"] else field["entry_role"]
            st.caption(f"字段类型：{field['field_type']} · 责任：{required}")

role = st.session_state["role"]
if role == "Reviewer":
    st.info("你当前是Reviewer：核查证据链、材料适用性、字段逻辑和不确定性，不重做整份初标。", icon=":material/fact_check:")
elif role == "Researcher":
    st.info("你当前是Researcher：维护候选语料与来源，核验系统派生字段，并完成L5和L6。", icon=":material/science:")
else:
    st.info("你当前是Coder：依据Shared AV Window访问外部影片，核验预建Event并完成全部红色字段；网页不加载视频或Praat截图。", icon=":material/edit_note:")
