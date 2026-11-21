"""케이스 상세 화면 (모든 역할). 볼 수 있는 케이스의 정보와 영상을 보여준다."""
import streamlit as st

from pacs import algorithms, auth, cases, config, notes, processing, reviews, roi as roi_mod, viewer, workflow

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
    f"{config.LABELS[case['exam_type']]} · {image['format'].upper()}"
    + (f" ({image['modality']})" if image.get("modality") else "")
    + f" · {image['width']}×{image['height']}"
    + (f" · 픽셀 간격 {image['pixel_spacing'][0]:.3f} mm" if image.get("pixel_spacing") else "")
    + " · 모의 케이스"
)
quality = image.get("quality")
if quality and not quality["passed"]:
    st.warning(
        "품질 자동 점검: 점검 필요 · " + " / ".join(quality["reasons"])
        + (f" · 그대로 진행한 사유: {image['proceed_reason']}" if image.get("proceed_reason") else "")
        + " (교육용 결과)"
    )
elif quality:
    st.caption("품질 자동 점검: 통과 (교육용 결과)")


# --- 업무 진행 (상태 전이, 노션 3장) ---
# 버튼은 allowed_actions로 고르지만, 실제 검사는 workflow.transition이 데이터 접근 단계에서 다시 한다.
reviewer_uids = case.get("reviewer_uids") or []
names = workflow.display_names(user, reviewer_uids)
st.caption(
    "검토 담당자: " + (", ".join(names[u] for u in reviewer_uids) if reviewer_uids else "배정 전")
    + (f" · 검토 {workflow.current_round(case)}회차" if workflow.current_round(case) > 1 else "")
)

ACTION_HELP = {
    "assign": "서로 다른 검토 담당자 2명을 고릅니다.",
    "start_review": "검토를 시작하면 영상처리 결과를 저장할 수 있습니다. 두 검토자 중 한 명만 누르면 됩니다.",
    "request_revision": "영상이나 정보 보완이 필요하면 사유를 적어 등록 담당자에게 돌려보냅니다.",
    "revision_done": "케이스 등록 화면에서 영상을 다시 올렸거나 보완을 마쳤으면 누릅니다.",
    "reopen": "완료된 케이스를 다시 검토합니다. 지금 회차의 검토·판정은 '이전 검토 회차'에 그대로 남고, "
    "두 검토자가 새 회차에서 다시 제출합니다. 사유가 변경 이력에 남습니다.",
}
# 중재 확정은 두 검토 결과를 비교한 의견과 함께 저장해야 해서 중재 화면에서 한다.
actions = [a for a in workflow.allowed_actions(user, case) if a != "arbitrate"]
if actions:
    with st.container(border=True):
        st.markdown("**업무 진행**")
        for action in actions:
            with st.form(f"{action}_{case_id}"):
                st.caption(ACTION_HELP[action])
                kwargs = {}
                if action == "assign":
                    accounts = workflow.reviewer_accounts(user)
                    by_uid = {a["uid"]: a["name"] for a in accounts}
                    kwargs["reviewer_uids"] = st.multiselect(
                        "검토 담당자 2명", list(by_uid), format_func=by_uid.get, max_selections=2,
                    )
                if workflow.TRANSITIONS[action].needs_reason:
                    kwargs["reason"] = st.text_area("사유")
                if st.form_submit_button(config.LABELS[action]):
                    try:
                        new_status = workflow.transition(user, case_id, action, **kwargs)
                    except (workflow.TransitionError, cases.CaseError, PermissionError) as e:
                        st.error(str(e))
                    else:
                        st.toast(f"{config.LABELS[action]}: {config.LABELS[new_status]}(으)로 바뀌었습니다.")
                        st.rerun()
if case["status"] == "arbitration" and user["role"] == "manager":
    st.info("두 검토자의 ROI가 어긋나 중재 중입니다. 중재 화면에서 두 결과를 비교하고 확정합니다.")
if case["status"] == "revision_requested" and user["role"] == "registrar":
    st.info("보완 요청을 받았습니다. 케이스 등록 화면에서 영상을 다시 올린 뒤 '보완 완료'를 눌러 주세요.")

with st.expander("상태 변경 이력"):
    events = workflow.list_events(user, case_id)
    actors = workflow.display_names(user, [e.get("actor_uid") for e in events])
    st.dataframe(
        [
            {
                "시각": cases.format_kst(e.get("at"), with_seconds=True),
                "동작": config.LABELS.get(e["action"], e["action"]),
                "상태": f"{config.LABELS.get(e.get('from_status'), '-')} → {config.LABELS[e['to_status']]}",
                "실행자": actors.get(e.get("actor_uid"), "-"),
                "사유": e.get("reason") or "",
            }
            for e in events
        ],
        hide_index=True,
    )

# --- 이전 검토 회차 (재검토로 닫힌 회차의 검토·판정, workflow.list_rounds) ---
if user["role"] != "registrar" and workflow.current_round(case) > 1:
    with st.expander(f"이전 검토 회차 ({workflow.current_round(case) - 1}회)"):
        rounds = workflow.list_rounds(user, case_id)
        people = workflow.display_names(
            user, [u for r in rounds for u in r["reviewer_uids"]] + [r.get("closed_by") for r in rounds]
        )
        for r in rounds:
            comp = r.get("comparison") or {}
            arb = comp.get("arbitration") or {}
            st.markdown(
                f"**{r['round']}회차** · 판정 {config.LABELS.get(comp.get('verdict'), '-')}"
                + (f" (겹침 비율 {comp['iou']:.2f})" if comp.get("iou") is not None else "")
                + (f" · 중재 {notes.CHOICE_LABELS.get(arb['choice'], arb['choice'])}" if arb.get("choice") else "")
            )
            st.caption(
                f"{cases.format_kst(r.get('closed_at'))}에 {people.get(r.get('closed_by'), '-')}이(가) 재검토로 닫음 · "
                f"사유: {r.get('reason') or '-'}"
            )
            for uid in r["reviewer_uids"]:
                rv = (r.get("reviews") or {}).get(uid) or {}
                box = rv.get("roi")
                st.caption(
                    f"- {people.get(uid, uid)}: "
                    + (f"ROI x={box['x']}, y={box['y']}, {box['w']}×{box['h']}" if box else "ROI 없음")
                    + f" · 메모: {rv.get('memo') or '없음'}"
                )

# --- 메모·리포트 (pacs/notes.py). 검토 메모는 검토 화면에서 쓴다 (reviews.memo). ---
with st.expander("메모 · 리포트", expanded=True):
    try:
        note_rows = notes.list_notes(user, case_id)
    except cases.CaseError as e:
        st.error(str(e))
        note_rows = []
    authors = workflow.display_names(user, [n["author_uid"] for n in note_rows])
    if user["role"] == "reviewer":
        st.caption("다른 검토자의 메모는 두 사람 모두 검토를 제출한 뒤에 보입니다.")
    if not note_rows:
        st.info("아직 메모가 없습니다.")
    for n in note_rows:
        with st.container(border=True):
            st.caption(
                f"**{config.LABELS[n['type']]}** · {authors.get(n['author_uid'], '-')} · "
                f"{cases.format_kst(n.get('created_at'))}"
                + (f" · 고친 시각 {cases.format_kst(n['edited_at'])}" if n.get("edited_at") else "")
            )
            st.text(n["body"])
            c1, c2 = st.columns(2)
            if n.get("edit_history"):
                with c1.popover(f"고치기 전 내용 {len(n['edit_history'])}건"):
                    for h in reversed(n["edit_history"]):
                        st.caption(f"{cases.format_kst(h.get('edited_at'))}까지")
                        st.text(h["body"])
            if n["author_uid"] == user["uid"]:
                with c2.popover("고치기"), st.form(f"edit_{n['id']}"):
                    body = st.text_area("내용", value=n["body"], max_chars=config.NOTE_MAX_LENGTH)
                    if st.form_submit_button("저장"):
                        try:
                            changed = notes.edit(user, n["id"], body)
                        except (notes.NoteError, cases.CaseError, PermissionError) as e:
                            st.error(str(e))
                        else:
                            st.toast("고쳤습니다. 이전 내용은 기록에 남습니다." if changed else "바뀐 내용이 없습니다.")
                            st.rerun()

    forms = [("memo", "", "메모 남기기")]
    if user["role"] == "manager" and case["status"] == "done":
        # 리포트 초안: 판정·중재 결과와 처리 이력(알고리즘·설정값·실행자·시간)을 채워 두고 관리 담당이 고친다.
        comparison = reviews.get_comparison(user, case_id)
        logs = [log for log in processing.list_logs(user, case_id) if log["status"] == "saved"]
        uids = [log.get("executed_by") for log in logs] + [((comparison or {}).get("arbitration") or {}).get("decided_by")]
        draft = notes.report_draft(case, comparison, logs, workflow.display_names(user, uids))
        forms.append(("report", draft, "리포트 저장"))
    for note_type, value, button in forms:
        with st.form(f"new_{note_type}_{case_id}", clear_on_submit=True):
            body = st.text_area(
                f"새 {config.LABELS[note_type]}", value=value, max_chars=config.NOTE_MAX_LENGTH,
                height=200 if note_type == "report" else None,
            )
            if st.form_submit_button(button):
                try:
                    _, created = notes.add(user, case_id, body, note_type)
                except (notes.NoteError, cases.CaseError, PermissionError) as e:
                    st.error(str(e))
                else:
                    st.toast("저장했습니다." if created else "같은 내용이 이미 저장돼 있습니다.")
                    st.rerun()

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
    try:
        roi = roi_mod.validate_roi(roi, gray.shape[1], gray.shape[0])
    except roi_mod.RoiError as e:
        st.warning(f"{e} 이 ROI는 통계와 저장에 쓰지 않습니다.")
        roi = None
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
            # 영상을 다시 올렸으면 지금 검토 대상과 이 결과의 원본이 다르다. 결과를 만든 원본과 비교한다.
            source = image if log["image_id"] == image["id"] else cases.load_image(user, log["image_id"])
            if result["bytes"] is None or source["bytes"] is None:
                st.warning("이 컴퓨터에 결과 파일이나 그 원본 파일이 없습니다.")
            else:
                if source is not image:
                    st.caption("다시 올리기 전의 영상으로 만든 결과입니다. 그 원본과 비교합니다.")
                viewer.compare(viewer.to_gray(source["bytes"]), viewer.to_gray(result["bytes"]), key=f"hist_{log['id']}")
