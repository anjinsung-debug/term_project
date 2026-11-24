"""기능과 예외 상황 검증 (안내문 09장). 실제 Firestore와 영상 저장 폴더로 시나리오를 처음부터 끝까지 실행한다.

화면이 부르는 데이터 접근 함수(cases, workflow, processing, reviews, notes)를 같은 순서로 직접 불러,
화면을 숨기는 것과 별개로 데이터 접근 단계에서 권한·입력·상태가 검사되는지 확인한다.
결과는 노션 "검증 결과" 페이지에 옮길 수 있는 표로 출력하고, 하나라도 실패하면 종료 코드 1로 끝난다.

사용법 (프로젝트 폴더에서, 배포 서버면 ~/term_project에서):
    python scripts/verify_scenarios.py <정상 흉부 X-ray PNG 경로>

- 테스트 계정은 users 컬렉션에서 역할로 찾는다 (등록 1, 관리 1, 검토 2명 필요). 이메일·비밀번호는 쓰지 않는다.
- 실행할 때마다 "VERIFY-월일-시분초" 모의 케이스가 하나 생기고 완료 상태로 남는다 (재조회 확인에 쓴다).
"""
import io
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pacs import algorithms, cases, firebase_app, notes, processing, reviews, workflow  # noqa: E402

ROWS = []


def accounts():
    """역할별 테스트 계정. 이메일 순으로 골라 매번 같은 계정을 쓴다."""
    by_role = {}
    for d in firebase_app.db().collection("users").stream():
        u = d.to_dict()
        by_role.setdefault(u.get("role"), []).append({"uid": d.id, "role": u.get("role"), "email": u.get("email", "")})
    for users in by_role.values():
        users.sort(key=lambda u: u["email"])
    need = {"registrar": 1, "manager": 1, "reviewer": 2}
    missing = [r for r, n in need.items() if len(by_role.get(r, [])) < n]
    if missing:
        sys.exit(f"테스트 계정이 부족합니다: {missing}. scripts/create_user.py로 만들어 주세요.")
    return by_role["registrar"][0], by_role["manager"][0], *by_role["reviewer"][:2]


def check(cid, group, action, expected, fn, ok):
    """fn을 실행하고 ok(결과, 예외)로 통과를 판단해 표에 한 줄 남긴다."""
    try:
        res, err = fn(), None
        actual = repr(res)
    except Exception as e:  # noqa: BLE001 - 거절 자체가 확인 대상이다
        res, err = None, e
        actual = f"{type(e).__name__}: {e}"
    ROWS.append((cid, group, action, expected, actual[:160].replace("|", "/"), bool(ok(res, err))))


def rejected(*types):
    return lambda r, e: isinstance(e, types)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    png = Path(sys.argv[1]).read_bytes()
    reg, man, ra, rb = accounts()
    outsider = {"uid": "verify-outsider", "role": "reviewer"}  # 어느 케이스에도 배정되지 않은 검토자
    mock_id = "VERIFY-" + datetime.now().strftime("%m%d-%H%M%S")
    P, C, T = PermissionError, cases.CaseError, workflow.TransitionError
    PE, R = processing.ProcessingError, reviews.ReviewError
    buf = io.BytesIO()
    Image.new("L", (100, 100), 128).save(buf, "PNG")

    # --- 입력: 잘못된 파일과 모의 ID ---
    check("I-1", "입력", "텍스트 파일을 영상으로 등록", "거절, 이유 안내",
          lambda: cases.register_case(reg, mock_id + "-T", "urgent", b"not an image"), rejected(C))
    check("I-2", "입력", "뒤가 잘린 PNG 등록", "거절, 손상 안내",
          lambda: cases.register_case(reg, mock_id + "-C", "urgent", png[: len(png) // 2]), rejected(C))
    check("I-3", "입력", "100×100 영상 등록", "거절, 최소 크기 안내",
          lambda: cases.register_case(reg, mock_id + "-S", "urgent", buf.getvalue()), rejected(C))
    check("I-4", "입력", "모의 ID에 허용 안 되는 문자", "거절, 형식 안내",
          lambda: cases.register_case(reg, "가나/다", "urgent", png), rejected(C))
    check("P-1", "권한", "검토 담당이 케이스 등록", "거절",
          lambda: cases.register_case(ra, mock_id + "-R", "urgent", png), rejected(P))

    # --- 등록·배정 ---
    cid = cases.register_case(reg, mock_id, "urgent", png)
    check("N-1", "정상 흐름", f"등록 담당이 {mock_id} 등록", "접수",
          lambda: cases.get_case(reg, cid)["status"], lambda r, e: r == "received")
    check("S-1", "상태·중복", "같은 모의 ID로 다시 등록", "거절, 중복 안내",
          lambda: cases.register_case(reg, mock_id, "urgent", png), rejected(C))
    check("P-2", "권한", "등록 담당이 검토자 배정", "거절",
          lambda: workflow.transition(reg, cid, "assign", reviewer_uids=[ra["uid"], rb["uid"]]), rejected(P, C, T))
    check("S-2", "상태·중복", "배정 전에 검토자가 검토 시작", "거절",
          lambda: workflow.transition(ra, cid, "start_review"), rejected(P, C, T))
    check("S-3", "상태·중복", "같은 검토자 2명 배정", "거절",
          lambda: workflow.transition(man, cid, "assign", reviewer_uids=[ra["uid"], ra["uid"]]), rejected(T))
    check("N-2", "정상 흐름", "관리 담당이 A·B 배정", "배정됨",
          lambda: workflow.transition(man, cid, "assign", reviewer_uids=[ra["uid"], rb["uid"]]), lambda r, e: r == "assigned")
    check("S-4", "상태·중복", "배정 버튼을 한 번 더 누름", "거절",
          lambda: workflow.transition(man, cid, "assign", reviewer_uids=[ra["uid"], rb["uid"]]), rejected(T))
    check("P-3", "권한", "배정 안 된 검토자가 케이스 조회", "찾을 수 없음",
          lambda: cases.get_case(outsider, cid), rejected(C))
    check("P-4", "권한", "역할 값을 바꾼 사용자(admin)가 목록 조회", "거절",
          lambda: cases.list_cases({"uid": ra["uid"], "role": "admin"}), rejected(P))
    check("N-3", "정상 흐름", "검토자 A가 검토 시작", "검토 중",
          lambda: workflow.transition(ra, cid, "start_review"), lambda r, e: r == "in_review")

    # --- 영상 처리 ---
    name = "clahe"
    params = {k: v["default"] for k, v in algorithms.available()[name].PARAMS.items()}
    roi = {"x": 300, "y": 300, "w": 200, "h": 200}
    log = {}
    check("P-5", "권한", "등록 담당이 처리 결과 저장", "거절",
          lambda: processing.save(reg, cid, name, params), rejected(P))
    check("I-5", "입력", "5×5 ROI로 처리 저장", "거절, 최소 크기 안내",
          lambda: processing.save(ra, cid, name, params, {"x": 10, "y": 10, "w": 5, "h": 5}), rejected(PE))
    check("I-6", "입력", "영상 밖으로 나간 ROI", "거절, 범위 안내",
          lambda: processing.save(ra, cid, name, params, {"x": 100000, "y": 0, "w": 200, "h": 200}), rejected(PE))
    check("I-7", "입력", "없는 설정값 이름(gamma)", "거절, 설정값 안내",
          lambda: processing.save(ra, cid, name, {**params, "gamma": 2}), rejected(PE))
    check("I-8", "입력", "범위 밖 설정값(clip_limit=-1)", "거절, 범위 안내",
          lambda: processing.save(ra, cid, name, {**params, "clip_limit": -1.0}), rejected(PE))
    check("I-9", "입력", "없는 알고리즘(sobel)", "거절",
          lambda: processing.save(ra, cid, "sobel", {}), rejected(PE))
    check("N-4", "정상 흐름", "A가 CLAHE 결과 저장(ROI 포함)", "저장, 새 기록",
          lambda: log.setdefault("id", processing.save(ra, cid, name, params, roi)), lambda r, e: r and r[1] is True)
    if "id" not in log:
        return report()  # 처리 결과가 없으면 뒤 시나리오가 의미 없다
    log_id = log["id"][0]
    check("S-5", "상태·중복", "같은 설정으로 저장을 한 번 더 누름", "기록 추가 안 됨",
          lambda: processing.save(ra, cid, name, params, roi), lambda r, e: r == (log_id, False))
    check("P-6", "권한", "B가 처리 이력 조회", "A의 이력 안 보임",
          lambda: [x["id"] for x in processing.list_logs(rb, cid)], lambda r, e: r is not None and log_id not in r)
    check("P-7", "권한", "B가 A의 처리 결과를 ID로 직접 조회", "찾을 수 없음",
          lambda: processing.load_result(rb, log_id), rejected(C))

    # --- 블라인드 이중 검토 ---
    check("I-10", "입력", "A가 5×5 ROI로 검토 제출", "거절, 최소 크기 안내",
          lambda: reviews.submit(ra, cid, {"x": 10, "y": 10, "w": 5, "h": 5}, "작은 ROI"), rejected(R))
    check("N-5", "정상 흐름", "A가 ROI·메모·처리 이력을 붙여 제출", "판정 대기",
          lambda: reviews.submit(ra, cid, roi, "검증: A 메모", [log_id])["verdict"], lambda r, e: e is None and r is None)
    check("S-6", "상태·중복", "A가 제출을 한 번 더 누름", "거절, 이미 제출 안내",
          lambda: reviews.submit(ra, cid, roi, "검증: A 메모"), rejected(R))
    check("P-8", "권한", "B가 제출 전에 A의 검토 조회", "거절(블라인드)",
          lambda: reviews.get_review(rb, cid, ra["uid"]), lambda r, e: e is not None or r is None)
    check("P-9", "권한", "B가 제출 전에 판정 기록 조회", "없음(블라인드)",
          lambda: reviews.get_comparison(rb, cid), lambda r, e: e is None and r is None)
    check("P-10", "권한", "등록 담당이 검토 기록 조회", "거절",
          lambda: reviews.list_reviews(reg, cid), rejected(P))
    notes.add(ra, cid, "검증: A의 케이스 메모")
    check("P-11", "권한", "B가 제출 전에 메모 목록 조회", "A의 메모 안 보임",
          lambda: [n["author_uid"] for n in notes.list_notes(rb, cid)], lambda r, e: r is not None and ra["uid"] not in r)
    check("N-6", "정상 흐름", "B가 겹치는 ROI로 제출", "자동 판정 일치 → 완료",
          lambda: reviews.submit(rb, cid, {"x": 310, "y": 310, "w": 200, "h": 200}, "검증: B 메모"),
          lambda r, e: r and r["verdict"] == "match" and r["status"] == "done")
    check("P-12", "권한", "제출 뒤 B가 A의 검토 조회", "보임",
          lambda: reviews.get_review(rb, cid, ra["uid"])["memo"], lambda r, e: r == "검증: A 메모")

    # --- 메모·리포트·이력, 다시 조회 ---
    report_text = f"검증 리포트: {mock_id} 일치로 완료"
    check("P-13", "권한", "검토 담당이 리포트 작성", "거절",
          lambda: notes.add(ra, cid, "리포트", "report"), rejected(P))
    check("N-7", "정상 흐름", "관리 담당이 리포트 작성", "저장",
          lambda: notes.add(man, cid, report_text, "report"), lambda r, e: r and r[1] is True)
    check("S-7", "상태·중복", "같은 리포트 저장을 한 번 더 누름", "기록 추가 안 됨",
          lambda: notes.add(man, cid, report_text, "report"), lambda r, e: r and r[1] is False)
    check("S-8", "상태·중복", "사유 없이 재검토", "거절, 사유 안내",
          lambda: workflow.transition(man, cid, "reopen", reason=" "), rejected(T))
    check("P-14", "권한", "검토 담당이 재검토", "거절",
          lambda: workflow.transition(ra, cid, "reopen", reason="x"), rejected(P, C, T))
    check("N-8", "정상 흐름", "완료 목록에서 다시 조회", "완료 목록에 있음",
          lambda: [c["id"] for c in cases.list_cases(man, status="done")], lambda r, e: r is not None and cid in r)
    check("N-9", "정상 흐름", "처리 결과를 원본·설정과 함께 다시 조회", "결과 파일·설정·ROI·원본 영상 연결",
          lambda: (lambda x: (x["bytes"] is not None, x["params"] == params, x["roi"] == roi,
                              x["image_id"] == cases.get_case(man, cid)["target_image_id"]))(processing.load_result(man, log_id)),
          lambda r, e: r == (True, True, True, True))
    check("N-10", "정상 흐름", "상태 변경 이력 조회", "등록·배정·검토 시작·자동 판정 순서",
          lambda: [x["action"] for x in workflow.list_events(man, cid)],
          lambda r, e: r == ["register", "assign", "start_review", "auto_match"])
    return report(mock_id, cid)


def report(mock_id=None, cid=None):
    print("| ID | 구분 | 수행 동작 | 예상 결과 | 실제 결과 | 판정 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for cid_, group, action, expected, actual, passed in ROWS:
        print(f"| {cid_} | {group} | {action} | {expected} | {actual} | {'통과' if passed else '실패'} |")
    failed = [r[0] for r in ROWS if not r[5]]
    print(f"\n{len(ROWS) - len(failed)}/{len(ROWS)} 통과" + (f", 실패: {', '.join(failed)}" if failed else "")
          + (f" · 모의 케이스 {mock_id} ({cid})" if mock_id else ""))
    return 1 if failed or mock_id is None else 0


if __name__ == "__main__":
    sys.exit(main())
