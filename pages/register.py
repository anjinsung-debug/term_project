"""케이스 등록 화면 (등록 담당자)."""
from datetime import datetime

import streamlit as st

from pacs import auth, cases, config

user = auth.require_login()
UPLOAD_TYPES = ["png", "jpg", "jpeg", "dcm"]
st.header("케이스 등록")

if user["role"] != "registrar":
    st.warning("등록 담당자만 케이스를 등록할 수 있습니다.")
    st.stop()

st.caption(
    f"흉부 X-ray PNG·JPEG 또는 DICOM({'·'.join(config.DICOM_MODALITIES)}, 압축되지 않은 것), "
    f"가로·세로 {config.MIN_IMAGE_SIDE}픽셀 이상, {config.MAX_UPLOAD_MB}MB 이하만 올릴 수 있습니다. 모의 케이스만 등록합니다."
)

with st.form("register", clear_on_submit=True):
    mock_id = st.text_input(
        "모의 케이스 ID",
        value=f"MOCK-{datetime.now(cases.KST):%Y%m%d-%H%M%S}",
        help="다른 케이스와 겹치지 않아야 합니다. 영문·숫자로 시작하고 영문·숫자·-·_ 로 40자 이내.",
    )
    urgency = st.selectbox(
        "긴급도",
        config.URGENCIES,
        index=None,
        format_func=lambda u: config.LABELS[u],
        placeholder="선택해 주세요",
        help="처방에서 넘어온 값을 가정한 모의 입력입니다.",
    )
    upload = st.file_uploader("흉부 X-ray 영상", type=UPLOAD_TYPES)
    submitted = st.form_submit_button("등록")

if submitted:
    if upload is None:
        st.error("영상 파일을 올려 주세요.")
    else:
        try:
            case_id = cases.register_case(user, mock_id, urgency, upload.getvalue())
        except cases.CaseError as e:
            st.error(str(e))
        else:
            st.success(f"{mock_id.strip()} 케이스를 등록했습니다.")
            quality = cases.get_image(user, cases.get_case(user, case_id)["target_image_id"])["quality"]
            if quality["passed"]:
                st.info("품질 자동 점검: 통과")
            else:
                st.warning("품질 자동 점검: 점검 필요 · " + " / ".join(quality["reasons"]) + ". 아래에서 처리해 주세요.")


def quality_metrics(q):
    return f"밝기 {q['brightness']} · 대비 {q['contrast']} · 잡음 {q['noise']} · 선명도 {q['sharpness']} (교육용 결과)"


# 품질 "점검 필요"인데 아직 다시 올리지도, 사유를 남기지도 않은 케이스 (노션 6-1)
pending = []
for r in cases.list_cases(user):
    if r["status"] in cases.REGISTRAR_EDIT_STATUSES and r.get("flags", {}).get("quality_check"):
        image = cases.get_image(user, r["target_image_id"])
        if not image.get("proceed_reason"):
            pending.append((r, image))

if pending:
    st.divider()
    st.subheader(f"품질 점검이 필요한 케이스 ({len(pending)})")
    st.caption("영상을 다시 올리거나, 다시 올릴 수 없으면 사유를 입력하고 그대로 진행해 주세요. 자동으로 보정하지 않습니다.")
    for r, image in pending:
        with st.expander(f"{r['mock_id']} · {config.LABELS[r['urgency']]} · " + " / ".join(image["quality"]["reasons"])):
            st.caption(quality_metrics(image["quality"]))
            again, proceed = st.columns(2)
            with again.form(f"replace_{r['id']}", clear_on_submit=True):
                new_upload = st.file_uploader("다시 올리기", type=UPLOAD_TYPES)
                if st.form_submit_button("이 영상으로 바꾸기"):
                    try:
                        if new_upload is None:
                            raise cases.CaseError("영상 파일을 올려 주세요.")
                        cases.replace_image(user, r["id"], new_upload.getvalue())
                    except cases.CaseError as e:
                        st.error(str(e))
                    else:
                        st.rerun()  # 새 영상의 점검 결과로 목록을 다시 그린다
            with proceed.form(f"proceed_{r['id']}"):
                reason = st.text_area("그대로 진행하는 사유", placeholder="예: 재촬영이 어려워 현재 영상으로 검토 요청")
                if st.form_submit_button("사유 저장하고 진행"):
                    try:
                        cases.set_proceed_reason(user, r["id"], reason)
                    except cases.CaseError as e:
                        st.error(str(e))
                    else:
                        st.rerun()

st.divider()
st.subheader("내가 등록한 케이스")

c1, c2, c3 = st.columns(3)
status = c1.selectbox("상태", config.STATUSES, index=None, format_func=lambda s: config.LABELS[s], placeholder="전체")
urgency_filter = c2.selectbox(
    "긴급도", config.URGENCIES, index=None, format_func=lambda u: config.LABELS[u], placeholder="전체", key="f_urg"
)
query = c3.text_input("모의 ID 검색")

rows = cases.list_cases(user, status=status, urgency=urgency_filter, mock_id_query=query)
if not rows:
    st.info("조건에 맞는 케이스가 없습니다.")
else:
    st.dataframe(
        [
            {
                "모의 ID": r["mock_id"],
                "긴급도": config.LABELS[r["urgency"]],
                "상태": config.LABELS[r["status"]],
                "품질": "점검 필요" if r.get("flags", {}).get("quality_check") else "통과",
                "등록 시각": cases.format_kst(r.get("registered_at")),
            }
            for r in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
