import pandas as pd
import streamlit as st

from utils.core import compare_coders, csv_bytes


st.title("双人标注一致性")
st.caption("上传两份独立Coder CSV。页面按字段类型计算名义分类、多选集合与时间span的一致性指标。")

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
        summary, disagreements = compare_coders(left, right, fields, schema=schema)
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
                    "mean_jaccard": st.column_config.NumberColumn("Mean Jaccard", format="%.3f"),
                    "mean_set_f1": st.column_config.NumberColumn("Mean set F1", format="%.3f"),
                    "mean_span_iou": st.column_config.NumberColumn("Mean span IoU", format="%.3f"),
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
    st.write(
        "单选名义字段报告Percent agreement与Cohen's κ；多选字段同时报告Jaccard与set F1；"
        "Naming span报告时间IoU。开放文本字段以分歧定位为主。低频或极度偏斜字段不宜机械追求κ，"
        "应结合分歧清单、规则适切性与培训记录解释。"
    )
