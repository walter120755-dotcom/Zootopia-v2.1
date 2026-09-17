import pandas as pd
import streamlit as st

from utils.core import compare_coders, csv_bytes


st.title("双人标注一致性")
st.caption("上传两份独立 Coder CSV。多选字段按规范化后的整组标签进行 exact-set comparison。")

left_file = st.file_uploader("Coder 1 CSV", type=["csv"], key="rel_left")
right_file = st.file_uploader("Coder 2 CSV", type=["csv"], key="rel_right")
schema = st.session_state["schema"]
eligible = [field["id"] for field in schema["fields"] if field.get("reliability_eligible")]
defaults = [field for field in schema.get("recommended_primary_reliability_fields", []) if field in eligible]
fields = st.multiselect("比较字段", eligible, default=defaults)

if left_file and right_file and fields:
    try:
        left = pd.read_csv(left_file, dtype=str).fillna("")
        right = pd.read_csv(right_file, dtype=str).fillna("")
        summary, disagreements = compare_coders(left, right, fields)
        if summary.empty:
            st.warning("文件中没有找到所选字段。")
        else:
            st.subheader("字段级结果")
            st.dataframe(
                summary,
                hide_index=True,
                column_config={
                    "percent_agreement": st.column_config.NumberColumn("Percent agreement", format="percent"),
                    "cohen_kappa": st.column_config.NumberColumn("Cohen's κ", format="%.3f"),
                },
            )
            with st.container(horizontal=True):
                st.download_button("下载一致性结果", csv_bytes(summary), "reliability_summary.csv", "text/csv", icon=":material/download:")
                if not disagreements.empty:
                    st.download_button("下载分歧清单", csv_bytes(disagreements), "disagreements.csv", "text/csv", icon=":material/download:")
            st.subheader("分歧定位")
            if disagreements.empty:
                st.success("所选字段没有分歧。")
            else:
                st.dataframe(disagreements, hide_index=True)
    except Exception as exc:
        st.error(f"无法比较：{exc}")

with st.expander("如何解释结果", icon=":material/info:"):
    st.write("Percent agreement 用于直观检查；Cohen's κ 校正偶然一致。低频、极度偏斜或开放文本字段不宜机械追求 κ。先审查分歧清单与规则，再决定修订 codebook 或培训，不要只优化数字。")
