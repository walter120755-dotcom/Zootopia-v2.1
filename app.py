from __future__ import annotations

import streamlit as st

from utils.core import read_annotation_standard, read_json, read_sample_items, schema_errors


st.set_page_config(
    page_title="Zootopia naming annotation · v2.1 pilot",
    page_icon=":material/label:",
    layout="wide",
)

st.session_state.setdefault("schema", read_json())
st.session_state.setdefault("annotation_standard", read_annotation_standard())
st.session_state.setdefault("items", read_sample_items())
st.session_state.setdefault("annotations", {})
st.session_state.setdefault("reviews", {})
st.session_state.setdefault("current_item", 0)
st.session_state.setdefault("st_l4_locks", set())

errors = schema_errors(st.session_state["schema"])
if errors:
    st.error("当前 codebook 未通过验证，标注功能已停用。", icon=":material/error:")
    st.code("\n".join(errors))
    st.stop()

with st.sidebar:
    st.header("工作身份")
    st.session_state["role"] = st.segmented_control(
        "角色",
        ["Coder", "Reviewer", "Researcher"],
        default=st.session_state.get("role", "Coder"),
        key="global_role",
    )
    st.session_state["actor_id"] = st.text_input(
        "人员 ID",
        value=st.session_state.get("actor_id", "coder_01"),
        key="global_actor_id",
    ).strip() or "anonymous"
    st.caption("角色用于工作分工，不等同于账户权限。浏览器会话关闭前，请下载CSV保存进度。")
    st.badge(f"Codebook {st.session_state['schema']['schema_version']}", color="blue")
    st.caption("v2.1 revised pre-pilot：一个Event锚定一个可独立定位的naming expression occurrence。")

pages = {
    "工作台": [
        st.Page("app_pages/home.py", title="开始", icon=":material/home:"),
        st.Page("app_pages/data.py", title="数据", icon=":material/database:"),
        st.Page("app_pages/code.py", title="标注", icon=":material/edit_note:"),
        st.Page("app_pages/review.py", title="审核", icon=":material/fact_check:"),
    ],
    "质量与治理": [
        st.Page("app_pages/reliability.py", title="一致性", icon=":material/compare_arrows:"),
        st.Page("app_pages/codebook.py", title="Codebook", icon=":material/menu_book:"),
    ],
}

page = st.navigation(pages, position="sidebar")
page.run()
