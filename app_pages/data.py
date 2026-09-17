import streamlit as st

from utils.core import csv_bytes, preferred_sheet, read_table, workbook_sheets


st.title("导入与检查语料")
st.caption("文件只进入当前浏览器会话；应用不会把数据永久写入服务器。")

uploaded = st.file_uploader("上传 CSV / XLSX / XLS", type=["csv", "xlsx", "xls"], key="items_upload")
if uploaded:
    data = uploaded.getvalue()
    try:
        sheets = workbook_sheets(data, uploaded.name)
    except Exception as exc:
        st.error(f"无法读取工作簿结构：{exc}")
        st.info("请确认上传的是有效的 CSV、XLSX 或 XLS 文件；部署端应安装 requirements.txt 中的 Excel 依赖。")
        st.stop()
    sheet = None
    if sheets:
        preferred = preferred_sheet(sheets)
        sheet = st.selectbox("选择工作表", sheets, index=sheets.index(preferred))
        st.caption(f"优先建议：{preferred}")
    if st.button("载入当前文件", type="primary", icon=":material/upload:"):
        try:
            st.session_state["items"] = read_table(data, uploaded.name, sheet)
            st.session_state["current_item"] = 0
            st.success(f"已载入 {len(st.session_state['items'])} 条记录。")
        except Exception as exc:
            st.error(f"载入失败：{exc}")

items = st.session_state["items"]
st.subheader("当前数据预览")
st.dataframe(items.head(100), hide_index=True)

recommended = {
    "event_id", "source_candidate_id", "candidate_version_origin",
    "shared_av_window_start", "shared_av_window_end", "speaker", "addressee", "target",
    "st_host_utterance", "tt_host_utterance", "st_naming_head", "tt_naming_head",
    "st_naming_expression", "tt_naming_expression", "st_characterizing_cotext", "tt_characterizing_cotext",
}
missing = sorted(recommended.difference(items.columns))
if missing:
    st.warning(
        "以下推荐预填列当前不存在，Coder仍可在标注页补填，但开始正式标注前最好补齐："
        + "、".join(missing)
    )
for column in ("shared_av_window_start", "shared_av_window_end"):
    if column in items and items[column].astype(str).str.strip().eq("").any():
        st.warning(f"部分条目的 {column} 为空。网页不播放视频，试标前请补齐或记录Not Assessable。")

with st.container(horizontal=True):
    st.download_button("下载当前items CSV", csv_bytes(items), "items_current.csv", "text/csv", icon=":material/download:")
    st.caption(f"共 {len(items)} 行、{len(items.columns)} 列；event_id已稳定化并检查重复。")

with st.expander("导入文件需要包含什么", icon=":material/info:"):
    st.markdown(
        "`event_id`是每条Naming Event的唯一编号；`source_candidate_id`保留拆分前候选行；"
        "`correspondence_group_id`仅连接一对多或多对一对应。Shared AV Window由start和end两列组成。"
    )
    st.markdown(
        "网页仍兼容旧列名：`item_id`、`No.`、`Speaker`、`Target`、`ST naming instance`、"
        "`Local context / source line`和`TT rendering`。其他列会保留，不会静默删除。"
    )
    st.warning("不需要上传视频URL、视频文件或Praat截图列；这些材料不会在网页中加载。")
