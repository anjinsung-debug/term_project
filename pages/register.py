"""케이스 등록 화면 (등록 담당자)."""
from datetime import datetime

import streamlit as st

from pacs import auth, cases, config

user = auth.require_login()
st.header("케이스 등록")

if user["role"] != "registrar":
    st.warning("등록 담당자만 케이스를 등록할 수 있습니다.")
    st.stop()

st.caption(
    f"흉부 X-ray PNG 또는 JPEG, 가로·세로 {config.MIN_IMAGE_SIDE}픽셀 이상, "
    f"{config.MAX_UPLOAD_MB}MB 이하만 올릴 수 있습니다. 모의 케이스만 등록합니다."
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
    upload = st.file_uploader("흉부 X-ray 영상", type=["png", "jpg", "jpeg"])
    submitted = st.form_submit_button("등록")

if submitted:
    if upload is None:
        st.error("영상 파일을 올려 주세요.")
    else:
        try:
            cases.register_case(user, mock_id, urgency, upload.getvalue())
        except cases.CaseError as e:
            st.error(str(e))
        else:
            st.success(f"{mock_id.strip()} 케이스를 등록했습니다.")

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
                "등록 시각": cases.format_kst(r.get("registered_at")),
            }
            for r in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
