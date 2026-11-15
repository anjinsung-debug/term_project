"""케이스 상세 화면 (모든 역할). 볼 수 있는 케이스의 정보와 영상을 보여준다."""
import streamlit as st

from pacs import algorithms, auth, cases, config, processing, viewer

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

try:
    gray = viewer.to_gray(image["bytes"])
except ValueError as e:
    st.error(f"{e} 등록 담당자에게 다시 올려 달라고 요청해 주세요.")
    st.stop()
view_tab, compare_tab, history_tab = st.tabs(["영상 보기 · ROI 선택", "처리 결과 비교", "처리 이력"])

with view_tab:
    roi = viewer.show(gray, key=f"view_{case_id}", select_roi=True)
    if roi:
        st.write(f"선택한 ROI: x={roi['x']}, y={roi['y']}, 가로 {roi['w']}, 세로 {roi['h']} (원본 픽셀 좌표)")

with compare_tab:
    modules = algorithms.available()
    if not modules:
        st.info("아직 사용할 수 있는 알고리즘이 없습니다.")
    else:
        recommend = (image.get("quality") or {}).get("recommend") or []
        name = st.selectbox(
            "알고리즘", list(modules),
            format_func=lambda n: config.LABELS[n] + (" (품질 점검 추천)" if n in recommend else ""),
        )
        params = viewer.param_controls(modules[name].PARAMS, key=f"{case_id}_{name}")
        try:
            processed = processing.run(name, gray, params)
        except processing.ProcessingError as e:
            st.error(str(e))
        else:
            viewer.compare(gray, processed, key=f"compare_{case_id}_{name}")
            feats = processing.features(gray, processed, roi)
            names = {"brightness": "밝기", "contrast": "대비", "noise": "잡음", "sharpness": "선명도"}
            rows = {names[k]: [feats["before"][k], feats["after"][k]] for k in feats["before"]}
            if roi:
                for k in ("mean", "variance", "std"):
                    rows[f"ROI {k}"] = [feats["roi_before"][k], feats["roi_after"][k]]
            st.dataframe(
                {"지표": list(rows), "원본": [v[0] for v in rows.values()], "처리 결과": [v[1] for v in rows.values()]},
                hide_index=True,
            )
            if roi:
                st.bar_chart(
                    {"원본": feats["roi_before"]["histogram"], "처리 결과": feats["roi_after"]["histogram"]},
                    x_label="밝기", y_label="ROI 픽셀 수", stack=False,
                )
            st.caption("교육용 결과입니다. 진단에 사용할 수 없습니다.")
            if user["role"] == "reviewer" and case["status"] in processing.PROCESS_STATUSES:
                st.caption("ROI는 '영상 보기 · ROI 선택' 탭에서 그린 것이 함께 저장됩니다." if roi else "ROI 없이 저장됩니다.")
                if st.button("이 설정으로 저장", key=f"save_{case_id}"):
                    try:
                        log_id, created = processing.save(user, case_id, name, params, roi)
                    except (processing.ProcessingError, cases.CaseError, PermissionError) as e:
                        st.error(str(e))
                    else:
                        st.success("저장했습니다." if created else "같은 설정의 결과가 이미 저장돼 있습니다.")

with history_tab:
    try:
        logs = processing.list_logs(user, case_id)
    except cases.CaseError as e:
        st.error(str(e))
        logs = []
    if not logs:
        st.info("저장된 처리 이력이 없습니다.")
    for log in logs:
        r = log.get("roi")
        st.markdown(
            f"**{config.LABELS.get(log['algorithm'], log['algorithm'])}** v{log['algorithm_version']} · "
            f"{cases.format_kst(log.get('executed_at'), with_seconds=True)} · "
            f"{'저장됨' if log['status'] == 'saved' else '파일 저장 실패'}"
        )
        st.caption(
            f"설정값 {log['params']} · "
            + (f"ROI x={r['x']}, y={r['y']}, {r['w']}×{r['h']}" if r else "ROI 없음")
            + (" · 품질 점검 추천" if log.get("recommended") else "")
        )
        if st.toggle("결과 보기", key=f"show_{log['id']}"):
            result = processing.load_result(user, log["id"])
            if result["bytes"] is None:
                st.warning("이 컴퓨터에 결과 파일이 없습니다.")
            else:
                viewer.compare(gray, viewer.to_gray(result["bytes"]), key=f"hist_{log['id']}")
