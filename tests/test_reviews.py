import itertools

import pytest

from pacs import reviews, workflow
from pacs.cases import CaseError
from pacs.reviews import ReviewError
from pacs.workflow import TransitionError

REV_A = {"uid": "revA", "role": "reviewer"}
REV_B = {"uid": "revB", "role": "reviewer"}
REV_OTHER = {"uid": "revC", "role": "reviewer"}
REGISTRAR = {"uid": "reg1", "role": "registrar"}
MANAGER = {"uid": "man1", "role": "manager"}

ROI_A = {"x": 100, "y": 120, "w": 80, "h": 60}
ROI_NEAR = {"x": 110, "y": 125, "w": 80, "h": 60}  # ROI_A와 겹침 비율 약 0.67 → 일치
ROI_FAR = {"x": 300, "y": 200, "w": 60, "h": 60}   # ROI_A와 겹치지 않음 → 불일치


# --- Firestore를 흉내 내는 최소한의 가짜 객체 (tests/test_workflow.py와 같은 방식) ---

class Snap:
    def __init__(self, data, doc_id=None):
        self._data, self.exists, self.id = data, data is not None, doc_id

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, store, name, doc_id):
        self.store, self.name, self.id = store, name, doc_id

    def get(self, transaction=None):
        return Snap(self.store[self.name].get(self.id), self.id)


class Collection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def document(self, doc_id=None):
        return Ref(self.store, self.name, doc_id or f"{self.name}-{next(self.store['_ids'])}")


class Transaction:
    """쓰기를 모아 두었다가 commit에서 한 번에 반영한다. 중간에 오류가 나면 아무것도 저장되지 않는다."""

    def __init__(self, store):
        self.store, self.ops = store, []

    def update(self, ref, data):
        self.ops.append(("update", ref, data))

    def set(self, ref, data):
        self.ops.append(("set", ref, data))

    def commit(self):
        for kind, ref, data in self.ops:
            docs = self.store[ref.name]
            if kind == "set":
                docs[ref.id] = dict(data)
                continue
            doc = docs[ref.id]
            for key, value in data.items():
                *parents, last = key.split(".")
                target = doc
                for p in parents:
                    target = target.setdefault(p, {})
                target[last] = value


class FakeDb:
    def __init__(self):
        self.store = {
            "cases": {}, "case_events": {}, "images": {}, "processing_logs": {},
            "reviews": {}, "comparisons": {}, "_ids": itertools.count(1),
            "users": {"revA": {"role": "reviewer"}, "revB": {"role": "reviewer"}, "man1": {"role": "manager"}},
        }

    def collection(self, name):
        return Collection(self.store, name)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(reviews.firebase_app, "db", lambda: fake)  # workflow도 같은 firebase_app을 쓴다
    fake.store["images"]["img1"] = {"case_id": "c1", "width": 512, "height": 512}
    fake.store["cases"]["c1"] = {
        "status": "in_review", "registrar_uid": "reg1", "reviewer_uids": ["revA", "revB"],
        "target_image_id": "img1", "flags": {"quality_check": False, "mismatch": False}, "completed_at": None,
    }
    return fake


def run(body, *args, **kwargs):
    """save_draft()·submit()·arbitrate()와 같은 일을 가짜 트랜잭션으로 한다."""
    db = reviews.firebase_app.db()
    tx = Transaction(db.store)
    result = body(tx, *args, **kwargs)
    tx.commit()
    return result


def draft(user, roi=ROI_A, memo="", logs=None):
    return run(reviews.save_draft_in, user, "c1", roi, memo, logs)


def submit(user, roi=ROI_A, memo="", logs=None):
    return run(reviews.submit_in, user, "c1", roi, memo, logs)


def case(db):
    return db.store["cases"]["c1"]


def review(db, uid):
    return db.store["reviews"].get(f"c1_{uid}")


def events(db):
    return [(e["action"], e["from_status"], e["to_status"], e["actor_uid"]) for e in db.store["case_events"].values()]


# --- 문서 ID ---

def test_review_doc_id_is_case_and_reviewer():
    assert reviews.review_id("c1", "revA") == "c1_revA"


# --- 제출 전 저장 ---

def test_assigned_reviewer_can_save_and_overwrite_draft(db):
    first = draft(REV_A, memo=" 우하엽 확인 ")
    assert review(db, "revA")["roi"] == ROI_A
    assert review(db, "revA")["memo"] == "우하엽 확인"  # 앞뒤 공백 정리
    assert review(db, "revA")["submitted"] is False

    draft(REV_A, roi=ROI_NEAR, memo="다시 봄")
    assert len(db.store["reviews"]) == 1  # 같은 문서를 덮어쓴다
    assert review(db, "revA")["roi"] == ROI_NEAR
    assert review(db, "revA")["created_at"] == first["created_at"]  # 처음 저장한 시각은 유지


def test_no_roi_can_be_saved(db):
    draft(REV_A, roi=None)
    assert review(db, "revA")["roi"] is None


def test_draft_rejects_invalid_roi_with_reason(db):
    with pytest.raises(ReviewError, match="범위"):
        draft(REV_A, roi={"x": 500, "y": 0, "w": 50, "h": 50})
    with pytest.raises(ReviewError, match="너무 작습니다"):
        draft(REV_A, roi={"x": 0, "y": 0, "w": 3, "h": 3})
    assert db.store["reviews"] == {}


def test_draft_rejects_too_long_memo(db):
    with pytest.raises(ReviewError, match="메모"):
        draft(REV_A, memo="가" * (reviews.MEMO_MAX_LENGTH + 1))


@pytest.mark.parametrize("status", ["received", "assigned", "revision_requested", "arbitration", "done"])
def test_only_in_review_case_is_editable(db, status):
    case(db)["status"] = status
    with pytest.raises(ReviewError, match="검토 중인 케이스"):
        draft(REV_A)


def test_unassigned_reviewer_gets_not_found(db):
    with pytest.raises(CaseError, match="찾을 수 없습니다"):
        draft(REV_OTHER)


@pytest.mark.parametrize("user", [MANAGER, REGISTRAR, None])
def test_only_reviewer_can_save(db, user):
    with pytest.raises(PermissionError):
        draft(user)


# --- 처리 이력 첨부 ---

def add_log(db, log_id, **changes):
    log = {"case_id": "c1", "image_id": "img1", "executed_by": "revA", "status": "saved"}
    db.store["processing_logs"][log_id] = {**log, **changes}


def test_own_processing_logs_are_attached_once(db):
    add_log(db, "log1")
    draft(REV_A, logs=["log1", "log1"])
    assert review(db, "revA")["processing_log_ids"] == ["log1"]


@pytest.mark.parametrize("changes", [
    {"executed_by": "revB"},       # 다른 검토자가 저장한 처리 결과 (블라인드 규칙)
    {"image_id": "img0"},          # 다른 영상
    {"case_id": "c2"},             # 다른 케이스
    {"status": "failed"},          # 저장에 실패한 기록
])
def test_rejects_processing_logs_that_are_not_mine_for_this_image(db, changes):
    add_log(db, "log1", **changes)
    with pytest.raises(ReviewError, match="처리 결과"):
        draft(REV_A, logs=["log1"])


def test_rejects_missing_processing_log(db):
    with pytest.raises(ReviewError, match="처리 결과"):
        draft(REV_A, logs=["nope"])


# --- 제출과 자동 판정 ---

def test_first_submit_waits_for_the_other_reviewer(db):
    result = submit(REV_A)
    assert result == {"status": "in_review", "verdict": None, "iou": None}
    assert review(db, "revA")["submitted"] is True
    assert review(db, "revA")["submitted_at"] is not None
    assert db.store["comparisons"] == {}
    assert events(db) == []


def test_cannot_submit_or_edit_twice(db):
    submit(REV_A)
    before = dict(review(db, "revA"))
    with pytest.raises(ReviewError, match="이미 제출"):
        submit(REV_A, roi=ROI_FAR)  # 버튼을 연달아 눌러도 기록은 그대로
    with pytest.raises(ReviewError, match="이미 제출"):
        draft(REV_A, roi=ROI_FAR)
    assert review(db, "revA") == before


def test_second_submit_with_overlapping_roi_completes_the_case(db):
    submit(REV_A, roi=ROI_A)
    result = submit(REV_B, roi=ROI_NEAR)
    assert result == {"status": "done", "verdict": "match", "iou": 0.6696}
    assert case(db)["status"] == "done"
    assert case(db)["completed_at"] is not None
    comp = db.store["comparisons"]["c1"]  # 문서 ID는 케이스 ID
    assert comp["reviewer_uids"] == ["revA", "revB"]
    assert comp["roi_a"] == ROI_A and comp["roi_b"] == ROI_NEAR
    assert comp["verdict"] == "match" and comp["iou_threshold"] == 0.5
    assert comp["arbitration"] is None
    assert events(db) == [("auto_match", "in_review", "done", "system")]


def test_second_submit_with_far_roi_goes_to_arbitration(db):
    submit(REV_B, roi=ROI_FAR)  # B가 먼저 내도 A/B 순서는 배정 순서를 따른다
    result = submit(REV_A, roi=ROI_A)
    assert result["status"] == "arbitration" and result["verdict"] == "mismatch"
    assert case(db)["flags"]["mismatch"] is True
    comp = db.store["comparisons"]["c1"]
    assert comp["roi_a"] == ROI_A and comp["roi_b"] == ROI_FAR
    assert events(db) == [("auto_mismatch", "in_review", "arbitration", "system")]


def test_both_no_roi_is_match_and_one_no_roi_is_mismatch(db):
    submit(REV_A, roi=None)
    assert submit(REV_B, roi=None)["verdict"] == "match"


def test_one_no_roi_is_mismatch(db):
    submit(REV_A, roi=None)
    result = submit(REV_B, roi=ROI_A)
    assert result == {"status": "arbitration", "verdict": "mismatch", "iou": None}


def test_judging_is_refused_when_image_changed_after_first_submit(db):
    submit(REV_A)
    review(db, "revA")["image_id"] = "img0"  # A는 이전 영상으로 제출한 상황
    with pytest.raises(ReviewError, match="이전 영상"):
        submit(REV_B)
    assert review(db, "revB") is None and case(db)["status"] == "in_review"  # 아무것도 저장되지 않음


def test_failed_status_change_saves_nothing(db, monkeypatch):
    submit(REV_A)

    def broken(*args, **kwargs):
        raise TransitionError("지금 상태에서는 할 수 없습니다.")

    monkeypatch.setattr(reviews.workflow, "apply", broken)
    with pytest.raises(TransitionError):
        submit(REV_B, roi=ROI_NEAR)
    assert review(db, "revB") is None  # 제출·판정·상태가 한 번에 저장되거나 하나도 저장되지 않는다
    assert db.store["comparisons"] == {}


# --- 블라인드 조회 ---

def test_reviewer_cannot_see_other_review_before_both_submit(db):
    draft(REV_A)
    with pytest.raises(PermissionError, match="모두 제출하기 전"):
        reviews.get_review(REV_B, "c1", "revA")
    submit(REV_A)
    with pytest.raises(PermissionError, match="모두 제출하기 전"):  # 한 명만 제출해도 아직 안 됨
        reviews.get_review(REV_B, "c1", "revA")


def test_reviewer_can_see_other_review_after_both_submit(db):
    submit(REV_A, roi=ROI_A)
    submit(REV_B, roi=ROI_FAR)
    assert reviews.get_review(REV_B, "c1", "revA")["roi"] == ROI_A


def test_reviewer_can_always_see_own_review(db):
    assert reviews.get_review(REV_A, "c1", "revA") is None  # 아직 저장 전
    draft(REV_A)
    assert reviews.get_review(REV_A, "c1", "revA")["roi"] == ROI_A


def test_manager_can_see_reviews_any_time(db):
    draft(REV_A)
    assert reviews.get_review(MANAGER, "c1", "revA")["roi"] == ROI_A
    assert set(reviews.list_reviews(MANAGER, "c1")) == {"revA", "revB"}


def test_registrar_and_unassigned_reviewer_cannot_see(db):
    submit(REV_A)
    with pytest.raises(PermissionError):
        reviews.get_review(REGISTRAR, "c1", "revA")
    with pytest.raises(CaseError):
        reviews.get_review(REV_OTHER, "c1", "revA")


def test_list_reviews_hides_other_review_until_both_submit(db):
    submit(REV_A)
    draft(REV_B, roi=ROI_FAR)
    assert set(reviews.list_reviews(REV_B, "c1")) == {"revB"}
    submit(REV_B, roi=ROI_FAR)
    assert set(reviews.list_reviews(REV_B, "c1")) == {"revA", "revB"}


def test_comparison_exists_only_after_both_submit(db):
    submit(REV_A)
    assert reviews.get_comparison(REV_A, "c1") is None
    submit(REV_B, roi=ROI_FAR)
    assert reviews.get_comparison(REV_A, "c1")["verdict"] == "mismatch"


# --- 중재 ---

@pytest.fixture
def mismatched(db):
    submit(REV_A, roi=ROI_A)
    submit(REV_B, roi=ROI_FAR)
    return db


def test_manager_confirms_reviewer_a_roi(mismatched):
    status = run(reviews.arbitrate_in, MANAGER, "c1", "a", "  A가 병변 위치를 정확히 잡음 ")
    assert status == "done" and case(mismatched)["status"] == "done"
    arb = mismatched.store["comparisons"]["c1"]["arbitration"]
    assert arb["choice"] == "a" and arb["final_roi"] == ROI_A
    assert arb["reason"] == "A가 병변 위치를 정확히 잡음" and arb["decided_by"] == "man1"
    assert events(mismatched)[-1] == ("arbitrate", "arbitration", "done", "man1")


def test_manager_can_draw_new_roi_or_choose_no_roi(mismatched):
    custom = {"x": 50, "y": 50, "w": 40, "h": 40}
    run(reviews.arbitrate_in, MANAGER, "c1", "custom", "둘 다 조금씩 벗어남", custom_roi=custom)
    assert mismatched.store["comparisons"]["c1"]["arbitration"]["final_roi"] == custom


def test_arbitration_no_roi(mismatched):
    run(reviews.arbitrate_in, MANAGER, "c1", "none", "이상 소견 없음")
    assert mismatched.store["comparisons"]["c1"]["arbitration"]["final_roi"] is None


@pytest.mark.parametrize("choice, reason, custom, message", [
    ("a", "  ", None, "사유"),
    ("x", "사유", None, "골라"),
    ("custom", "사유", None, "새 ROI"),
    ("custom", "사유", {"x": 600, "y": 0, "w": 20, "h": 20}, "범위"),
])
def test_arbitration_input_is_checked(mismatched, choice, reason, custom, message):
    with pytest.raises(ReviewError, match=message):
        run(reviews.arbitrate_in, MANAGER, "c1", choice, reason, custom_roi=custom)
    assert case(mismatched)["status"] == "arbitration"


@pytest.mark.parametrize("user", [REV_A, REGISTRAR])
def test_only_manager_can_arbitrate(mismatched, user):
    with pytest.raises(PermissionError):
        run(reviews.arbitrate_in, user, "c1", "a", "사유")


def test_cannot_arbitrate_before_judging(db):
    submit(REV_A)
    with pytest.raises(ReviewError, match="모두 제출되지 않아"):
        run(reviews.arbitrate_in, MANAGER, "c1", "a", "사유")


def test_cannot_arbitrate_matched_or_already_arbitrated_case(db):
    submit(REV_A, roi=ROI_A)
    submit(REV_B, roi=ROI_NEAR)  # 일치 → 완료
    with pytest.raises(TransitionError):  # 상태 검사는 workflow가 한다
        run(reviews.arbitrate_in, MANAGER, "c1", "a", "사유")


def test_cannot_arbitrate_twice(mismatched):
    run(reviews.arbitrate_in, MANAGER, "c1", "a", "사유")
    with pytest.raises(ReviewError, match="이미 중재"):
        run(reviews.arbitrate_in, MANAGER, "c1", "b", "다시")


def test_reviewers_see_arbitration_feedback_after_done(mismatched):
    run(reviews.arbitrate_in, MANAGER, "c1", "b", "B가 맞음")
    assert reviews.get_comparison(REV_A, "c1")["arbitration"]["reason"] == "B가 맞음"
