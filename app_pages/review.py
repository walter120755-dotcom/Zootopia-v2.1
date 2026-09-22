from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.core import annotations_frame, csv_bytes, field_map
from utils.ui import source_card


st.title("审核工作台")
st.caption("Reviewer检查证据链与规则一致性；Return退回可修正问题，Escalate提交研究者裁决。")

uploaded = st.file_uploader("可选：上传Coder导出的CSV", type=["csv"], key="review_upload")
annotations = pd.read_csv(uploaded, dtype=str).fillna("") if uploaded else annotations_frame(st.session_state["annotations"])

if annotations.empty:
    st.warning("尚无可审核的标注记录。可先完成初标，或上传Coder CSV。")
    st.stop()
if "event_id" not in annotations:
    st.error("审核文件缺少event_id。")
    st.stop()

items = st.session_state["items"].set_index("event_id", drop=False)
index = st.selectbox(
    "选择审核记录",
    range(len(annotations)),
    format_func=lambda idx: (
        f"{idx + 1}/{len(annotations)} · {annotations.iloc[idx]['event_id']} · "
        f"{annotations.iloc[idx].get('coder_id', 'unknown')}"
    ),
)
record = annotations.iloc[index]
event_id = str(record["event_id"])
if event_id in items.index:
    source_card(items.loc[event_id])
else:
    st.warning("当前items数据中找不到此event_id；仍可审核编码结果。")

st.info("网页不加载媒体。Reviewer根据AV window访问同一套外部ST／TT音画材料进行抽查。", icon=":material/movie_info:")

st.subheader("Coder输出")
visible = pd.DataFrame({"field": record.index, "value": record.values})
visible = visible[visible["value"].astype(str).str.strip().ne("")]
st.dataframe(visible, hide_index=True)

reviewer_id = st.session_state["actor_id"]
coder_id = str(record.get("coder_id", "unknown"))
self_review = reviewer_id == coder_id
if self_review:
    st.error("Reviewer不得审核自己的annotation。请切换人员ID。")

evidence_field = field_map(st.session_state["schema"])["evidence_sufficiency_gate"]
revision_targets_field = field_map(st.session_state["schema"])["revision_targets"]
with st.form(f"review_form__{coder_id}__{event_id}"):
    decision = st.segmented_control(
        "审核决定",
        ["Accept", "Return", "Escalate"],
        default="Accept",
        key=f"decision__{coder_id}__{event_id}",
    )
    evidence_sufficiency_gate = st.selectbox(
        evidence_field["display_name"],
        [""] + evidence_field["full_value_list"],
        help=evidence_field["definition"] + "\n\n" + evidence_field["decision_rule"],
    )
    revision_targets = st.multiselect(
        revision_targets_field["display_name"],
        revision_targets_field["full_value_list"],
        help=revision_targets_field["definition"] + "\n\n" + revision_targets_field["decision_rule"],
    )
    note = st.text_area("审核意见／修改指令", height=120)
    adjudicated_value = st.text_area("裁决值（仅Escalate后由Researcher填写）", height=80)
    submitted = st.form_submit_button(
        "追加审核记录",
        type="primary",
        icon=":material/fact_check:",
        disabled=self_review,
    )

if submitted:
    if not evidence_sufficiency_gate:
        st.error("必须填写Evidence Sufficiency Gate。")
    elif evidence_sufficiency_gate == "Revise" and not revision_targets:
        st.error("Evidence Sufficiency Gate为Revise时，必须选择Revision Targets。")
    elif evidence_sufficiency_gate in {"Revise", "Not Assessable"} and not note.strip():
        st.error("Revise或Not Assessable必须填写可执行的审核说明。")
    else:
        action_id = f"REV-{uuid4().hex[:12]}"
        st.session_state["reviews"][action_id] = {
            "review_action_id": action_id,
            "event_id": event_id,
            "coder_id": coder_id,
            "reviewer_id": reviewer_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_decision": decision,
            "evidence_sufficiency_gate": evidence_sufficiency_gate,
            "revision_targets": revision_targets,
            "review_note": note,
            "adjudicated_value": adjudicated_value,
            "codebook_version": st.session_state["schema"]["schema_version"],
        }
        st.success(f"已追加审核决定：{decision}。旧记录未被覆盖。")

reviews = annotations_frame(st.session_state["reviews"])
if not reviews.empty:
    st.download_button(
        "下载审核记录CSV", csv_bytes(reviews), "review_records.csv", "text/csv", icon=":material/download:"
    )

with st.expander("Reviewer的职责边界", icon=":material/policy:"):
    st.markdown(
        "- 按Shared AV Window抽查外部ST／TT音画，检查naming expression与co-text边界。\n"
        "- 检查字段间逻辑与证据链，不按个人偏好重写Coder答案。\n"
        "- 可修正问题用Return；规则或证据无法解决的分歧用Escalate。\n"
        "- Reviewer不得审核自己的annotation，也不得覆盖旧审核动作。"
    )
