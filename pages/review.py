"""검토 화면 (검토 담당). 배정된 케이스에 ROI·메모·처리 결과를 담아 검토를 저장하고 제출한다.

- 블라인드 규칙은 pacs/reviews.py의 함수가 지킨다. 이 화면은 그 함수가 돌려준 것만 보여준다.
- 영상처리 결과 저장은 케이스 상세 화면의 "처리 결과 비교"에서 하고, 여기서는 저장한 결과를 첨부한다.
"""
import streamlit as st

from pacs import auth, cases, config, processing, reviews, viewer, workflow
from pacs import roi as roi_mod

user = auth.require_login()
st.header("검토")
if user["role"] != "reviewer":
    st.info("검토 담당자만 쓰는 화면입니다.")
    st.stop()

ERRORS = (reviews.ReviewError, workflow.TransitionError, cases.CaseError, PermissionError)
SHOWN = ("assigned", "in_review", "revision_requested", "arbitration", "done")

rows = [r for r in cases.list_cases(user) if r.get("status") in SHOWN]
if not rows:
    st.info("배정된 케이스가 없습니다.")
    st.stop()

by_id = {r["id"]: r for r in rows}
case_id = st.selectbox(
    "케이스",
    list(by_id),
    format_func=lambda i: f"{by_id[i]['mock_id']} · {config.LABELS[by_id[i]['status']]} · {config.LABELS[by_id[i]['urgency']]}",
)

try:
    case = cases.get_case(user, case_id)
    image = cases.load_image(user, case["target_image_id"])
    mine = reviews.get_review(user, case_id, user["uid"])
    comparison = reviews.get_comparison(user, case_id)
except ERRORS as e:
    st.error(str(e))
    st.stop()

status = case["status"]
c1, c2, c3 = st.columns(3)
c1.metric("모의 케이스 ID", case["mock_id"])
c2.metric("상태", config.LABELS[status])
c3.metric("내 검토", "제출함" if mine and mine.get("submitted") else ("임시 저장" if mine else "작성 전"))
st.caption("두 검토자가 모두 제출하기 전에는 서로의 결과를 볼 수 없습니다 (블라인드 이중 검토). 교육용 결과입니다.")

if status == "assigned":
    st.info("아직 검토를 시작하지 않았습니다. 케이스 상세 화면의 '업무 진행'에서 '검토 시작'을 눌러 주세요.")
    st.stop()
if status == "revision_requested":
    st.info("보완 요청 중입니다. 등록 담당자가 보완을 마치면 다시 검토할 수 있습니다.")

if image["bytes"] is None:
    st.warning("이 컴퓨터에 영상 파일이 없습니다 (README '영상 파일 저장').")
    st.stop()
try:
    gray = viewer.to_gray(image["bytes"])
except ValueError as e:
    st.error(f"{e} 등록 담당자에게 다시 올려 달라고 요청해 주세요.")
    st.stop()


def roi_text(r):
    return f"x={r['x']}, y={r['y']}, 가로 {r['w']}, 세로 {r['h']}" if r else "ROI 없음"


def show_stats(r):
    """ROI의 평균·분산·표준편차와 히스토그램."""
    if not r:
        return
    try:
        stats = roi_mod.roi_stats(gray, r)
    except roi_mod.RoiError as e:
        st.error(str(e))
        return
    s1, s2, s3 = st.columns(3)
    s1.metric("ROI 평균 밝기", stats["mean"])
    s2.metric("분산", stats["variance"])
    s3.metric("표준편차", stats["std"])
    st.bar_chart({"ROI 픽셀 수": stats["histogram"]}, x_label="밝기", y_label="픽셀 수")


# --- 작성 (검토 중이고 아직 제출하지 않았을 때) ---
editable = status in reviews.EDITABLE_STATUSES and not (mine and mine.get("submitted"))
if editable:
    saved_roi = (mine or {}).get("roi")
    drawn = viewer.show(
        gray, key=f"review_{case_id}", select_roi=True,
        rois=[(saved_roi, "저장한 ROI", "orange")] if saved_roi else (),
    )

    options = []
    if drawn:
        options.append("drawn")
    if saved_roi:
        options.append("saved")
    options.append("none")
    labels = {"drawn": "방금 그린 ROI", "saved": "저장한 ROI (주황색)", "none": "ROI 없음 (이상 소견 없음)"}
    # key를 두지 않아 선택지가 바뀌면(새로 그림) 처음 항목으로 돌아간다.
    pick = st.radio("제출할 ROI", options, format_func=labels.get, horizontal=True)
    chosen = {"drawn": drawn, "saved": saved_roi, "none": None}[pick]
    st.caption(f"선택한 ROI: {roi_text(chosen)} (원본 픽셀 좌표)")
    show_stats(chosen)

    try:
        logs = [
            log for log in processing.list_logs(user, case_id)
            if log.get("status") == "saved" and log.get("image_id") == case["target_image_id"]
        ]
    except ERRORS as e:
        st.error(str(e))
        logs = []
    log_labels = {
        log["id"]: f"{config.LABELS.get(log['algorithm'], log['algorithm'])} · {log['params']} · "
        f"{cases.format_kst(log.get('executed_at'))}"
        for log in logs
    }
    attached = st.multiselect(
        "첨부할 처리 결과",
        list(log_labels),
        default=[i for i in (mine or {}).get("processing_log_ids", []) if i in log_labels],
        format_func=log_labels.get,
        help="케이스 상세 화면의 '처리 결과 비교'에서 '이 설정으로 저장'한 결과만 보입니다.",
        key=f"logs_{case_id}",
    )
    memo = st.text_area(
        "검토 메모", value=(mine or {}).get("memo", ""), max_chars=reviews.MEMO_MAX_LENGTH,
        placeholder="예: 오른쪽 폐 아래쪽에 밝은 부분이 있음. CLAHE로 대비를 높여 확인함",
        key=f"memo_{case_id}",
    )

    b1, b2 = st.columns(2)
    if b1.button("임시 저장", key=f"draft_{case_id}", use_container_width=True):
        try:
            reviews.save_draft(user, case_id, chosen, memo, attached)
        except ERRORS as e:
            st.error(str(e))
        else:
            st.toast("임시 저장했습니다. 제출 전까지 고칠 수 있습니다.")
            st.rerun()
    with b2:
        sure = st.checkbox("제출하면 고칠 수 없다는 것을 확인했습니다", key=f"sure_{case_id}")
        if st.button("제출", type="primary", disabled=not sure, key=f"submit_{case_id}", use_container_width=True):
            try:
                result = reviews.submit(user, case_id, chosen, memo, attached)
            except ERRORS as e:
                st.error(str(e))
            else:
                if result["verdict"] is None:
                    st.toast("제출했습니다. 다른 검토자의 제출을 기다립니다.")
                else:
                    st.toast(f"두 검토가 모두 제출되어 '{config.LABELS[result['verdict']]}'로 판정됐습니다.")
                st.rerun()
    st.stop()


# --- 제출 후: 상대 제출 대기 ---
if comparison is None:
    if mine and mine.get("submitted"):
        st.success(f"제출했습니다 ({cases.format_kst(mine.get('submitted_at'))}). 다른 검토자의 제출을 기다리는 중입니다.")
        viewer.show(gray, key=f"mine_{case_id}", rois=[(mine["roi"], "내 ROI", "orange")] if mine.get("roi") else ())
        st.caption(f"내 ROI: {roi_text(mine.get('roi'))}")
        if mine.get("memo"):
            st.caption(f"내 메모: {mine['memo']}")
    else:
        st.info("지금 상태에서는 검토를 작성할 수 없습니다.")
    st.stop()


# --- 판정 후: 두 결과와 피드백 (두 사람 모두 제출했으므로 공개) ---
a_uid, b_uid = comparison["reviewer_uids"]
names = workflow.display_names(user, [a_uid, b_uid])
me_label = {a_uid: "A", b_uid: "B"}
verdict = config.LABELS[comparison["verdict"]]
iou = comparison.get("iou")
st.subheader(f"판정: {verdict}")
st.caption(
    (f"겹침 비율(IoU) {iou:.2f} · 기준 {comparison['iou_threshold']} 이상이면 일치" if iou is not None
     else "한 명 이상이 'ROI 없음'으로 제출해 겹침 비율을 계산하지 않았습니다.")
    + f" · 나는 검토자 {me_label.get(user['uid'], '-')}"
)
arbitration = comparison.get("arbitration")
final_choice = (arbitration or {}).get("choice")
# 중재에서 A나 B의 ROI를 그대로 고르면 최종 ROI가 같은 자리에 겹쳐 원래 색을 덮는다.
# 그래서 이때는 따로 그리지 않고 그 검토자 이름 옆에 "= 최종"을 붙인다. 새로 그린 ROI만 연두색으로 따로 그린다.
rois = [
    (comparison.get("roi_a"), f"A · {names.get(a_uid, a_uid)}" + (" = 최종" if final_choice == "a" else ""), "red"),
    (comparison.get("roi_b"), f"B · {names.get(b_uid, b_uid)}" + (" = 최종" if final_choice == "b" else ""), "#4da3ff")  # 어두운 배경에서도 보이는 밝은 파랑,
]
if final_choice == "custom" and arbitration.get("final_roi"):
    rois.append((arbitration["final_roi"], "최종 (관리 담당이 새로 그림)", "lime"))
viewer.show(gray, key=f"result_{case_id}", rois=[r for r in rois if r[0]])

try:
    both = reviews.list_reviews(user, case_id)
except ERRORS as e:
    st.error(str(e))
    both = {}
for uid in (a_uid, b_uid):
    r = both.get(uid) or {}
    st.markdown(f"**검토자 {me_label[uid]} · {names.get(uid, uid)}**")
    st.caption(f"ROI: {roi_text(r.get('roi'))} · 메모: {r.get('memo') or '없음'}")

if arbitration:
    choice = {"a": "검토자 A의 ROI", "b": "검토자 B의 ROI", "custom": "관리 담당이 새로 그린 ROI", "none": "ROI 없음"}
    st.info(f"중재 결과: {choice[arbitration['choice']]} · 사유: {arbitration['reason']}")
elif status == "arbitration":
    st.info("두 ROI가 어긋나 관리 담당자가 중재 중입니다.")
