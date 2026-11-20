"""블라인드 이중 검토: 검토 저장·제출, 블라인드 조회, 자동 판정, 중재 확정 (노션 설계 문서 6-2, 담당: 고영민).

규칙 (CLAUDE.md):
- reviews 문서 ID는 "케이스ID_검토자UID", comparisons 문서 ID는 케이스 ID다. ID를 정해 두어 같은 기록이 두 번 생기지 않게 한다.
- 검토 메모는 reviews.memo에 둔다. 블라인드 규칙을 reviews 문서 하나에만 적용하기 위해서다.
- 두 검토자가 모두 제출하기 전에는 상대의 검토 결과를 이 모듈의 함수에서 거절한다. 화면에서 숨기는 것만으로 끝내지 않는다.
- 판정은 comparison.judge(겹침 비율)만으로 한다. 상태는 workflow로만 바꾼다.
  자동 판정(auto_match, auto_mismatch)은 workflow.SYSTEM이, 중재 확정(arbitrate)은 관리 담당이 실행한다.

트랜잭션 순서: Firestore 트랜잭션은 읽기를 모두 마친 뒤에 써야 한다.
그래서 모든 함수가 "필요한 문서 읽기 → workflow.apply(안에서 케이스를 다시 읽고 상태를 씀) → 검토·판정 기록 쓰기" 순서로 한다.
이 순서 덕분에 검토 제출과 판정, 상태 변경이 한 번에 저장되거나 하나도 저장되지 않는다.
"""
from datetime import datetime, timezone

from google.cloud import firestore

from pacs import comparison, config, firebase_app, workflow
from pacs import roi as roi_mod
from pacs.auth import require_role
from pacs.cases import CaseError, can_view
from pacs.workflow import TransitionError

# 검토를 저장·제출할 수 있는 케이스 상태 (노션 3장: 검토자가 판독하는 단계는 "검토 중").
EDITABLE_STATUSES = ("in_review",)
MEMO_MAX_LENGTH = 2000
# 중재에서 최종 ROI를 고르는 방법: 검토자 A의 ROI, B의 ROI, 관리 담당이 새로 그림, ROI 없음.
ARBITRATION_CHOICES = ("a", "b", "custom", "none")


class ReviewError(Exception):
    """검토 저장·제출·중재가 규칙에 맞지 않을 때. 메시지는 화면에 그대로 보여준다."""


def review_id(case_id, reviewer_uid):
    """reviews 문서 ID. 검토자 한 명당 케이스 하나에 문서 하나만 생긴다."""
    return f"{case_id}_{reviewer_uid}"


# --- 읽기 도우미 (트랜잭션 안·밖 모두에서 쓴다. transaction=None이면 일반 읽기) ---

def _read_case(db, transaction, user, case_id):
    snap = db.collection("cases").document(case_id).get(transaction=transaction)
    case = snap.to_dict() if snap.exists else None
    # 없는 케이스와 볼 권한이 없는 케이스를 구분하지 않는다 (cases.get_case와 같은 방식).
    if not case or not can_view(user, case):
        raise CaseError("케이스를 찾을 수 없습니다.")
    return {"id": case_id, **case}


def _read_review(db, transaction, case_id, reviewer_uid):
    if not reviewer_uid:
        return None
    snap = db.collection("reviews").document(review_id(case_id, reviewer_uid)).get(transaction=transaction)
    return snap.to_dict() if snap.exists else None


def _read_doc(db, transaction, collection, doc_id):
    snap = db.collection(collection).document(doc_id).get(transaction=transaction)
    return snap.to_dict() if snap.exists else None


def _reviewers(case):
    """배정된 검토자 2명 [A, B]. 순서는 배정할 때 정해진 reviewer_uids 순서를 따른다."""
    uids = list(case.get("reviewer_uids") or [])
    if len(uids) != 2:
        raise ReviewError("검토 담당자 2명이 배정되지 않은 케이스입니다.")
    return uids


def _both_submitted(db, transaction, case):
    a, b = _reviewers(case)
    reviews = {uid: _read_review(db, transaction, case["id"], uid) for uid in (a, b)}
    return all(r and r.get("submitted") for r in reviews.values()), reviews


# --- 입력 검사 ---

def _clean_input(db, transaction, user, case, roi, memo, processing_log_ids):
    """ROI·메모·첨부할 처리 이력을 검사해 저장할 형태로 돌려준다. 읽기만 한다."""
    image_id = case.get("target_image_id")
    image = _read_doc(db, transaction, "images", image_id) if image_id else None
    if not image:
        raise ReviewError("검토할 영상을 찾을 수 없습니다.")
    try:
        roi = roi_mod.validate_roi(roi, image["width"], image["height"])
    except roi_mod.RoiError as e:
        raise ReviewError(str(e)) from e

    memo = (memo or "").strip()
    if len(memo) > MEMO_MAX_LENGTH:
        raise ReviewError(f"메모는 {MEMO_MAX_LENGTH}자 이하로 적어 주세요.")

    # 처리 이력(processing.save가 돌려준 ID)은 본인이 이 케이스의 이 영상에 저장한 것만 첨부할 수 있다.
    log_ids = list(dict.fromkeys(processing_log_ids or []))  # 순서를 지키며 중복 제거
    for log_id in log_ids:
        log = _read_doc(db, transaction, "processing_logs", log_id)
        if not (
            log
            and log.get("executed_by") == user["uid"]
            and log.get("case_id") == case["id"]
            and log.get("image_id") == image_id
            and log.get("status") == "saved"
        ):
            raise ReviewError("본인이 이 영상에 저장한 처리 결과만 검토에 첨부할 수 있습니다.")
    return {"image_id": image_id, "roi": roi, "memo": memo, "processing_log_ids": log_ids}


def _check_editable(user, case, mine):
    require_role(user, "reviewer")
    if case.get("status") not in EDITABLE_STATUSES:
        raise ReviewError("검토 중인 케이스에서만 검토를 저장하거나 제출할 수 있습니다. 먼저 '검토 시작'을 눌러 주세요.")
    if mine and mine.get("submitted"):
        raise ReviewError("이미 제출한 검토입니다. 제출한 뒤에는 고칠 수 없습니다.")


def _review_record(user, case, cleaned, mine, now, *, submitted):
    record = {
        "case_id": case["id"],
        "reviewer_uid": user["uid"],
        **cleaned,
        "submitted": submitted,
        "submitted_at": now if submitted else None,
        "created_at": (mine or {}).get("created_at") or now,
        "updated_at": now,
    }
    return record


# --- 트랜잭션 안에서 실행하는 본체 (테스트는 가짜 트랜잭션으로 이 함수들을 부른다) ---

def save_draft_in(transaction, user, case_id, roi, memo, processing_log_ids=None):
    """제출 전 검토를 저장한다. 같은 문서를 덮어쓰므로 여러 번 저장해도 기록은 하나다."""
    require_role(user, "reviewer")
    db = firebase_app.db()
    case = _read_case(db, transaction, user, case_id)
    mine = _read_review(db, transaction, case_id, user["uid"])
    _check_editable(user, case, mine)
    cleaned = _clean_input(db, transaction, user, case, roi, memo, processing_log_ids)

    now = datetime.now(timezone.utc)
    record = _review_record(user, case, cleaned, mine, now, submitted=False)
    transaction.set(db.collection("reviews").document(review_id(case_id, user["uid"])), record)
    return record


def submit_in(transaction, user, case_id, roi, memo, processing_log_ids=None):
    """검토를 제출한다. 두 번째 제출이면 판정하고 상태를 바꾼다.

    돌려주는 값: {"status": 케이스의 새 상태, "verdict": "match"/"mismatch" 또는 아직 판정 전이면 None, "iou": 값 또는 None}
    """
    require_role(user, "reviewer")
    db = firebase_app.db()
    # 1) 읽기
    case = _read_case(db, transaction, user, case_id)
    a, b = _reviewers(case)
    mine = _read_review(db, transaction, case_id, user["uid"])
    _check_editable(user, case, mine)
    other_uid = b if user["uid"] == a else a
    other = _read_review(db, transaction, case_id, other_uid)
    cleaned = _clean_input(db, transaction, user, case, roi, memo, processing_log_ids)

    now = datetime.now(timezone.utc)
    record = _review_record(user, case, cleaned, mine, now, submitted=True)
    result = {"status": case["status"], "verdict": None, "iou": None}
    comparison_record = None

    if other and other.get("submitted"):
        # 상대가 이전 영상으로 제출한 뒤 영상이 바뀌었다면 같은 영상끼리 비교한 것이 아니므로 판정하지 않는다.
        if other.get("image_id") != cleaned["image_id"]:
            raise ReviewError("다른 검토자가 이전 영상으로 제출해 판정할 수 없습니다. 관리 담당자에게 알려 주세요.")
        rois = {user["uid"]: cleaned["roi"], other_uid: other.get("roi")}
        judged = comparison.judge(rois[a], rois[b])
        action = "auto_match" if judged["verdict"] == "match" else "auto_mismatch"
        # 2) 상태 변경 (workflow.apply는 안에서 케이스를 한 번 더 읽고 쓴다. 우리 쓰기보다 먼저 불러야 한다.)
        result["status"] = workflow.apply(transaction, workflow.SYSTEM, case_id, action)
        result.update(verdict=judged["verdict"], iou=judged["iou"])
        comparison_record = {
            "case_id": case_id,
            "image_id": cleaned["image_id"],
            "reviewer_uids": [a, b],
            "roi_a": rois[a],
            "roi_b": rois[b],
            "verdict": judged["verdict"],
            "iou": judged["iou"],
            "iou_threshold": config.IOU_MATCH_THRESHOLD,  # 판정 당시 기준값. 나중에 기준을 바꿔도 비교할 수 있게 남긴다
            "compared_at": now,
            "arbitration": None,
        }

    # 3) 쓰기
    transaction.set(db.collection("reviews").document(review_id(case_id, user["uid"])), record)
    if comparison_record:
        transaction.set(db.collection("comparisons").document(case_id), comparison_record)
    return result


def arbitrate_in(transaction, user, case_id, choice, reason, custom_roi=None):
    """불일치 케이스의 최종 결과를 확정하고 상태를 '완료'로 바꾼다. 관리 담당만.

    choice: "a"(검토자 A의 ROI), "b"(B의 ROI), "custom"(custom_roi로 새로 그림), "none"(ROI 없음)
    """
    require_role(user, "manager")
    if choice not in ARBITRATION_CHOICES:
        raise ReviewError("최종 결과를 골라 주세요.")
    reason = (reason or "").strip()
    if not reason:
        raise ReviewError("중재 사유를 입력해 주세요. 두 검토자에게 피드백으로 보여줍니다.")
    if len(reason) > MEMO_MAX_LENGTH:
        raise ReviewError(f"중재 사유는 {MEMO_MAX_LENGTH}자 이하로 적어 주세요.")

    db = firebase_app.db()
    # 1) 읽기
    case = _read_case(db, transaction, user, case_id)
    comp = _read_doc(db, transaction, "comparisons", case_id)
    if not comp:
        raise ReviewError("아직 두 검토가 모두 제출되지 않아 중재할 수 없습니다.")
    if comp.get("arbitration"):
        raise ReviewError("이미 중재가 끝난 케이스입니다.")
    if choice == "custom":
        image = _read_doc(db, transaction, "images", comp["image_id"])
        if not image:
            raise ReviewError("검토할 영상을 찾을 수 없습니다.")
        try:
            final_roi = roi_mod.validate_roi(custom_roi, image["width"], image["height"])
        except roi_mod.RoiError as e:
            raise ReviewError(str(e)) from e
        if final_roi is None:
            raise ReviewError("새 ROI를 그려 주세요. ROI가 없다는 결론이면 'ROI 없음'을 고르세요.")
    else:
        final_roi = {"a": comp.get("roi_a"), "b": comp.get("roi_b"), "none": None}[choice]

    # 2) 상태 변경 (중재 중 → 완료). 상태 검사는 workflow가 한다.
    # 사유를 함께 넘겨 케이스 상세의 "상태 변경 이력"에도 중재 사유가 남게 한다.
    new_status = workflow.apply(transaction, user, case_id, "arbitrate", reason=reason)

    # 3) 쓰기
    transaction.update(db.collection("comparisons").document(case_id), {
        "arbitration": {
            "choice": choice,
            "final_roi": final_roi,
            "reason": reason,
            "decided_by": user["uid"],
            "decided_at": datetime.now(timezone.utc),
        },
    })
    return new_status


# --- 화면에서 부르는 함수 (Firestore 트랜잭션으로 감싼다) ---

def _run(body, *args, **kwargs):
    @firestore.transactional
    def run(transaction):
        return body(transaction, *args, **kwargs)

    try:
        return run(firebase_app.db().transaction())
    except (ReviewError, TransitionError, CaseError, PermissionError):
        raise
    except Exception as e:
        # 트랜잭션이라 일부만 저장되지는 않는다. 다시 시도하면 된다.
        raise ReviewError("저장하지 못했습니다. 잠시 후 다시 시도해 주세요.") from e


def save_draft(user, case_id, roi, memo, processing_log_ids=None):
    """제출 전 검토 저장. 돌려주는 값은 저장한 검토 기록."""
    return _run(save_draft_in, user, case_id, roi, memo, processing_log_ids)


def submit(user, case_id, roi, memo, processing_log_ids=None):
    """검토 제출. 버튼을 두 번 눌러도 두 번째는 "이미 제출한 검토입니다"로 거절된다."""
    return _run(submit_in, user, case_id, roi, memo, processing_log_ids)


def arbitrate(user, case_id, choice, reason, custom_roi=None):
    """중재 확정. 돌려주는 값은 케이스의 새 상태("done")."""
    return _run(arbitrate_in, user, case_id, choice, reason, custom_roi)


# --- 조회 (블라인드 규칙을 여기서 지킨다) ---

def get_review(user, case_id, reviewer_uid):
    """한 검토자의 검토 기록. 저장한 적이 없으면 None.

    - 검토 담당: 본인 검토는 언제든, 다른 검토자의 검토는 두 사람 모두 제출한 뒤에만
    - 관리 담당: 언제든 (중재해야 하므로)
    - 등록 담당: 볼 수 없음
    """
    require_role(user, "reviewer", "manager")
    db = firebase_app.db()
    case = _read_case(db, None, user, case_id)
    if reviewer_uid not in (case.get("reviewer_uids") or []):
        raise CaseError("검토 기록을 찾을 수 없습니다.")
    if user["role"] == "reviewer" and reviewer_uid != user["uid"]:
        both, _ = _both_submitted(db, None, case)
        if not both:
            raise PermissionError("두 검토자가 모두 제출하기 전에는 다른 검토자의 결과를 볼 수 없습니다.")
    return _read_review(db, None, case_id, reviewer_uid)


def list_reviews(user, case_id):
    """볼 수 있는 검토 기록만 {검토자UID: 기록 또는 None}으로 돌려준다.

    검토 담당은 두 사람 모두 제출하기 전에는 본인 것만 들어 있다.
    """
    require_role(user, "reviewer", "manager")
    db = firebase_app.db()
    case = _read_case(db, None, user, case_id)
    both, reviews = _both_submitted(db, None, case)
    if user["role"] == "reviewer" and not both:
        return {user["uid"]: reviews.get(user["uid"])}
    return reviews


def get_comparison(user, case_id):
    """판정·중재 기록. 두 검토가 모두 제출되기 전에는 None.

    판정 기록은 두 번째 제출 때 처음 생기므로, 검토 담당이 받아도 블라인드 규칙이 깨지지 않는다.
    """
    require_role(user, "reviewer", "manager")
    db = firebase_app.db()
    _read_case(db, None, user, case_id)  # 역할·담당 범위 확인
    return _read_doc(db, None, "comparisons", case_id)
