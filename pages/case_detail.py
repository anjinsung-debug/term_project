"""케이스 상세 화면 (모든 역할). 볼 수 있는 케이스의 정보와 영상을 보여준다."""
import streamlit as st

from pacs import algorithms, auth, cases, config, viewer

user = auth.require_login()
st.header("케이스 상세")

rows = cases.list_cases(user)
if not rows:
    st.info("볼 수 있는 케이스가 없습니다.")
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
except cases.CaseError as e:
    st.error(str(e))
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("모의 케이스 ID", case["mock_id"])
c2.metric("긴급도", config.LABELS[case["urgency"]])
c3.metric("상태", config.LABELS[case["status"]])
c4.metric("등록 시각", cases.format_kst(case.get("registered_at")))
st.caption(
    f"{config.LABELS[case['exam_type']]} · {image['format'].upper()} · "
    f"{image['width']}×{image['height']} · 모의 케이스"
)

if image["bytes"] is None:
    st.warning(
        "이 컴퓨터에 영상 파일이 없습니다. 기록은 있지만 파일은 등록한 사람의 컴퓨터에만 있을 수 있습니다 "
        "(README '영상 파일 저장')."
    )
    st.stop()

gray = viewer.to_gray(image["bytes"])
view_tab, compare_tab = st.tabs(["영상 보기 · ROI 선택", "처리 결과 비교"])

with view_tab:
    roi = viewer.show(gray, key=f"view_{case_id}", select_roi=True)
    if roi:
        st.write(f"선택한 ROI: x={roi['x']}, y={roi['y']}, 가로 {roi['w']}, 세로 {roi['h']} (원본 픽셀 좌표)")

with compare_tab:
    modules = algorithms.available()
    if not modules:
        st.info("아직 사용할 수 있는 알고리즘이 없습니다.")
    else:
        name = st.selectbox("알고리즘", list(modules), format_func=lambda n: config.LABELS[n])
        params = viewer.param_controls(modules[name].PARAMS, key=f"{case_id}_{name}")
        try:
            processed = modules[name].apply(gray, **params)
        except ValueError as e:
            st.error(str(e))
        else:
            viewer.compare(gray, processed, key=f"compare_{case_id}_{name}")
            st.caption("처리 결과는 아직 저장되지 않습니다. 처리 이력 저장은 다음 작업에서 추가합니다.")
