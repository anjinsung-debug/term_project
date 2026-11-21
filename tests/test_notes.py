from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from pacs import config, notes
from pacs.cases import CaseError, can_view

REGISTRAR = {"uid": "reg1", "role": "registrar"}
REV_A = {"uid": "revA", "role": "reviewer"}
REV_B = {"uid": "revB", "role": "reviewer"}
REV_OTHER = {"uid": "revC", "role": "reviewer"}
MANAGER = {"uid": "man1", "role": "manager"}


# --- Firestore를 흉내 내는 최소한의 가짜 객체 ---

class Snap:
    def __init__(self, data):
        self._data, self.exists = data, data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, docs, doc_id):
        self.docs, self.id = docs, doc_id

    def get(self):
        return Snap(self.docs.get(self.id))

    def create(self, data):
        if self.id in self.docs:
            raise AlreadyExists("exists")
        self.docs[self.id] = dict(data)

    def update(self, data):
        self.docs[self.id].update(data)


class Collection:
    def __init__(self, docs, filters=()):
        self.docs, self.filters = docs, filters

    def document(self, doc_id):
        return Ref(self.docs, doc_id)

    def where(self, filter):
        return Collection(self.docs, self.filters + (filter,))

    def stream(self):
        return [
            type("Doc", (), {"id": i, "to_dict": lambda self, d=d: dict(d)})()
            for i, d in self.docs.items()
            if all(d.get(f.field_path) == f.value for f in self.filters)
        ]


class FakeDb:
    def __init__(self):
        self.store = {"notes": {}, "comparisons": {}}

    def collection(self, name):
        return Collection(self.store[name])


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    case = {
        "id": "c1", "mock_id": "M-1", "urgency": "urgent", "status": "in_review", "registrar_uid": "reg1",
        "reviewer_uids": ["revA", "revB"], "target_image_id": "img1", "completed_at": None,
    }
    fake.case = case

    def get_case(user, case_id):
        if case_id != "c1" or not can_view(user, case):
            raise CaseError("케이스를 찾을 수 없습니다.")
        return dict(case)

    monkeypatch.setattr(notes.firebase_app, "db", lambda: fake)
    monkeypatch.setattr(notes, "get_case", get_case)
    return fake


def bodies(user):
    return [n["body"] for n in notes.list_notes(user, "c1")]


# --- 쓰기 ---

def test_add_saves_fields_and_double_click_makes_one_note(db):
    note_id, created = notes.add(REV_A, "c1", "  왼쪽 폐야 확인  ")
    assert created
    assert notes.add(REV_A, "c1", "왼쪽 폐야 확인") == (note_id, False)  # 같은 내용을 다시 눌러도 하나
    note = db.store["notes"][note_id]
    assert note["body"] == "왼쪽 폐야 확인"
    assert (note["case_id"], note["image_id"], note["type"], note["author_uid"]) == ("c1", "img1", "memo", "revA")
    assert note["edited_at"] is None and note["edit_history"] == []


@pytest.mark.parametrize("body", ["", "   ", "가" * (config.NOTE_MAX_LENGTH + 1)])
def test_add_rejects_empty_or_too_long(db, body):
    with pytest.raises(notes.NoteError):
        notes.add(REV_A, "c1", body)
    assert db.store["notes"] == {}


def test_add_rejects_unknown_type_and_unassigned_user(db):
    with pytest.raises(notes.NoteError):
        notes.add(MANAGER, "c1", "내용", note_type="opinion")
    with pytest.raises(CaseError):
        notes.add(REV_OTHER, "c1", "내용")


def test_report_only_by_manager_on_done_case(db):
    with pytest.raises(notes.NoteError):
        notes.add(MANAGER, "c1", "리포트", note_type="report")  # 아직 완료 전
    db.case["status"] = "done"
    with pytest.raises(PermissionError):
        notes.add(REV_A, "c1", "리포트", note_type="report")
    _, created = notes.add(MANAGER, "c1", "리포트", note_type="report")
    assert created


# --- 고치기 ---

def test_edit_keeps_history_and_only_author_can_edit(db):
    note_id, _ = notes.add(REGISTRAR, "c1", "첫 내용")
    created_at = db.store["notes"][note_id]["created_at"]
    with pytest.raises(PermissionError):
        notes.edit(MANAGER, note_id, "남이 고침")
    assert notes.edit(REGISTRAR, note_id, "첫 내용") is False  # 바뀐 게 없음
    assert notes.edit(REGISTRAR, note_id, "둘째 내용")
    assert notes.edit(REGISTRAR, note_id, "셋째 내용")
    note = db.store["notes"][note_id]
    assert note["body"] == "셋째 내용"
    assert [h["body"] for h in note["edit_history"]] == ["첫 내용", "둘째 내용"]
    assert note["edit_history"][0]["edited_at"] == created_at


def test_edit_hidden_note_looks_missing(db):
    note_id, _ = notes.add(REV_B, "c1", "B 메모")
    with pytest.raises(CaseError):
        notes.edit(REV_A, note_id, "A가 고침")  # 판정 전에는 있는지도 알려주지 않는다
    with pytest.raises(CaseError):
        notes.edit(MANAGER, "없는 ID", "내용")


# --- 블라인드 규칙 ---

def test_reviewer_cannot_see_other_reviewer_notes_before_both_submitted(db):
    notes.add(REGISTRAR, "c1", "등록 메모")
    notes.add(MANAGER, "c1", "관리 메모")
    notes.add(REV_A, "c1", "A 메모")
    notes.add(REV_B, "c1", "B 메모")
    assert set(bodies(REV_A)) == {"등록 메모", "관리 메모", "A 메모"}
    assert set(bodies(REV_B)) == {"등록 메모", "관리 메모", "B 메모"}
    assert len(bodies(MANAGER)) == len(bodies(REGISTRAR)) == 4

    db.store["comparisons"]["c1"] = {"verdict": "mismatch"}  # 두 번째 제출로 판정 기록이 생김
    assert len(bodies(REV_A)) == len(bodies(REV_B)) == 4


def test_list_is_oldest_first_and_checks_case_access(db):
    for i, body in enumerate(["둘째", "첫째"]):
        note_id, _ = notes.add(MANAGER, "c1", body)
        db.store["notes"][note_id]["created_at"] = datetime(2026, 11, 20, 10 - i, tzinfo=timezone.utc)
    assert bodies(MANAGER) == ["첫째", "둘째"]
    with pytest.raises(CaseError):
        notes.list_notes(REV_OTHER, "c1")


# --- 리포트 초안 ---

def test_report_draft_lists_verdict_arbitration_and_logs(db):
    case = {**db.case, "status": "done", "completed_at": datetime(2026, 11, 20, 5, tzinfo=timezone.utc)}
    comparison = {
        "verdict": "mismatch", "iou": 0.123, "iou_threshold": 0.5,
        "arbitration": {"choice": "b", "decided_by": "man1", "reason": "B가 병변 범위에 맞음"},
    }
    logs = [{
        "algorithm": "clahe", "algorithm_version": "1", "params": {"clip_limit": 2.0},
        "executed_by": "revA", "executed_at": datetime(2026, 11, 20, 4, tzinfo=timezone.utc),
    }]
    text = notes.report_draft(case, comparison, logs, {"man1": "관리자", "revA": "검토자 A"})
    assert "M-1" in text and "2026-11-20 14:00" in text  # 완료 시각은 한국 시간
    assert "불일치 (겹침 비율 0.12, 기준 0.5)" in text
    assert "검토자 B의 ROI · 관리자 · 사유: B가 병변 범위에 맞음" in text
    assert "CLAHE v1 {'clip_limit': 2.0} · 검토자 A · 2026-11-20 13:00" in text
    assert "처리 이력: 없음" in notes.report_draft(case, None, [], {})
