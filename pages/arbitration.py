"""중재 화면 (관리 담당). 불일치로 판정된 케이스의 두 검토 결과를 비교하고 최종 결과를 확정한다.

- 판정에는 겹침 비율만 썼다. 여기서 보여주는 ROI 통계 차이와 Canny 경계 비율은 판단을 돕는 참고 정보다 (CLAUDE.md).
- 확정은 reviews.arbitrate가 중재 의견 저장과 상태 변경(중재 중 → 완료)을 한 트랜잭션으로 한다.
"""
import streamlit as st

from pacs import auth, cases, comparison as comparison_mod, config, processing, reviews, viewer, workflow

user = auth.require_login()
st.header("중재")
if user["role"] != "manager":
    st.info("관리 담당자만 쓰는 화면입니다.")
    st.stop()

ERRORS = (reviews.ReviewError, workflow.TransitionError, cases.CaseError, PermissionError)

rows = cases.list_cases(user, status="arbitration")
if not rows:
    st.info("중재할 케이스가 없습니다. 두 검토자의 ROI가 어긋난 케이스가 여기에 나타납니다.")
    st.stop()

by_id = {r["id"]: r for r in rows}
case_id = st.selectbox(
    "중재할 케이스",
    list(by_id),
    format_func=lambda i: f"{by_id[i]['mock_id']} · {config.LABELS[by_id[i]['urgency']]}",
)

try:
    case = cases.get_case(user, case_id)
    comp = reviews.get_comparison(user, case_id)
    both = reviews.list_reviews(user, case_id)
    image = cases.load_image(user, comp["image_id"] if comp else case["target_image_id"])
except ERRORS as e:
    st.error(str(e))
    st.stop()
if not comp:
    st.warning("판정 기록이 없습니다. 두 검토가 모두 제출됐는지 확인해 주세요.")
    st.stop()

a_uid, b_uid = comp["reviewer_uids"]
names = workflow.display_names(user, [a_uid, b_uid])
roi_a, roi_b = comp.get("roi_a"), comp.get("roi_b")


def roi_text(r):
    return f"x={r['x']}, y={r['y']}, 가로 {r['w']}, 세로 {r['h']}" if r else "ROI 없음"


iou = comp.get("iou")
c1, c2, c3 = st.columns(3)
c1.metric("판정", config.LABELS[comp["verdict"]])
c2.metric("겹침 비율(IoU)", f"{iou:.2f}" if iou is not None else "계산 안 함")
c3.metric("일치 기준", f"{comp['iou_threshold']} 이상")
st.caption("교육용 결과입니다. 진단에 사용할 수 없습니다.")

if image["bytes"] is None:
    st.warning("이 컴퓨터에 영상 파일이 없습니다 (README '영상 파일 저장').")
    st.stop()
try:
    gray = viewer.to_gray(image["bytes"])
except ValueError as e:
    st.error(str(e))
    st.stop()

# 두 ROI를 색을 달리해 겹쳐 그린다. 새 ROI가 필요하면 이 영상 위에 그린다.
drawn = viewer.show(
    gray, key=f"arb_{case_id}", select_roi=True,
    rois=[r for r in [(roi_a, f"A · {names.get(a_uid, a_uid)}", "red"), (roi_b, f"B · {names.get(b_uid, b_uid)}", "blue")] if r[0]],
)

# --- 두 검토자의 결과 ---
try:
    logs = {log["id"]: log for log in processing.list_logs(user, case_id)}  # 관리 담당은 모든 처리 이력을 본다
except ERRORS:
    logs = {}
left, right = st.columns(2)
for col, uid, label, r in ((left, a_uid, "A (빨간색)", roi_a), (right, b_uid, "B (파란색)", roi_b)):
    review = both.get(uid) or {}
    with col:
        st.markdown(f"**검토자 {label} · {names.get(uid, uid)}**")
        st.caption(f"ROI: {roi_text(r)}")
        st.caption(f"메모: {review.get('memo') or '없음'}")
        used = [logs[i] for i in review.get("processing_log_ids", []) if i in logs]
        st.caption(
            "사용한 처리: "
            + (", ".join(f"{config.LABELS.get(l['algorithm'], l['algorithm'])} {l['params']}" for l in used) or "없음")
        )

# --- 참고 정보: 판정에는 쓰지 않는다 ---
with st.expander("참고 정보: ROI 밝기 통계와 경계 비율 (판정에는 쓰지 않음)", expanded=True):
    try:
        info = comparison_mod.reference_info(gray, roi_a, roi_b)
    except ValueError as e:
        st.error(str(e))
    else:
        def cell(side, key):
            return info[side][key] if info[side] else "-"

        table = {
            "항목": ["평균 밝기", "표준편차", "Canny 경계 비율"],
            "A": [cell("a", "mean"), cell("a", "std"), cell("a", "edge_ratio")],
            "B": [cell("b", "mean"), cell("b", "std"), cell("b", "edge_ratio")],
            "차이 (B - A)": [info["diff"][k] for k in ("mean", "std", "edge_ratio")] if info["diff"] else ["-"] * 3,
        }
        st.dataframe(table, hide_index=True)
        if info["a"] and info["b"]:
            st.bar_chart(
                {"A": info["a"]["histogram"], "B": info["b"]["histogram"]},
                x_label="밝기", y_label="ROI 픽셀 수", stack=False,
            )
        st.caption("경계 비율은 Canny 기본 설정으로 영상 전체의 경계를 뽑은 뒤 ROI 안에서 센 값입니다.")

# --- 확정 ---
with st.form(f"arbitrate_{case_id}"):
    st.markdown("**최종 결과 확정**")
    options = ["a", "b"] + (["custom"] if drawn else []) + ["none"]
    labels = {
        "a": f"검토자 A의 ROI ({roi_text(roi_a)})",
        "b": f"검토자 B의 ROI ({roi_text(roi_b)})",
        "custom": f"방금 그린 ROI ({roi_text(drawn)})",
        "none": "ROI 없음 (이상 소견 없음)",
    }
    choice = st.radio("최종 ROI", options, format_func=labels.get)
    if not drawn:
        st.caption("새 ROI로 확정하려면 위 영상에 네모를 그리면 선택지가 생깁니다.")
    reason = st.text_area(
        "중재 사유", max_chars=reviews.MEMO_MAX_LENGTH,
        placeholder="두 검토자에게 피드백으로 보여줍니다. 예: B가 병변 경계를 더 정확히 잡음",
    )
    if st.form_submit_button("확정하고 완료로 바꾸기", type="primary"):
        try:
            reviews.arbitrate(user, case_id, choice, reason, custom_roi=drawn if choice == "custom" else None)
        except ERRORS as e:
            st.error(str(e))
        else:
            st.toast("중재를 확정했습니다. 케이스가 완료로 바뀌었습니다.")
            st.rerun()
