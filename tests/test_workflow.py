import itertools
from datetime import datetime, timezone

import pytest

from pacs import config, workflow
from pacs.cases import CaseError

REGISTRAR = {"uid": "reg1", "role": "registrar"}
OTHER_REGISTRAR = {"uid": "reg2", "role": "registrar"}
REV_A = {"uid": "revA", "role": "reviewer"}
REV_B = {"uid": "revB", "role": "reviewer"}
REV_OTHER = {"uid": "revC", "role": "reviewer"}
MANAGER = {"uid": "man1", "role": "manager"}


# --- Firestore를 흉내 내는 최소한의 가짜 객체 ---

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
    def __init__(self, store, name, filters=()):
        self.store, self.name, self.filters = store, name, filters

    def where(self, filter):
        return Collection(self.store, self.name, self.filters + (filter,))

    def stream(self):
        return [
            type("Doc", (), {"id": i, "to_dict": lambda self, d=d: dict(d)})()
            for i, d in self.store[self.name].items()
            if all(d.get(f.field_path) == f.value for f in self.filters)
        ]

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
            for key, value in data.items():  # "flags.mismatch"처럼 점으로 묶음 필드 안을 바꾼다
                *parents, last = key.split(".")
                target = doc
                for p in parents:
                    target = target.setdefault(p, {})
                target[last] = value


class FakeDb:
    def __init__(self):
        self.store = {
            "cases": {}, "case_events": {}, "_ids": itertools.count(1),
            "users": {
                "revA": {"role": "reviewer", "display_name": "검토자 A"}, "revB": {"role": "reviewer", "email": "b@pacs.test"},
                "revC": {"role": "reviewer", "display_name": "검토자 C"}, "man1": {"role": "manager", "display_name": "관리자"},
            },
        }

    def collection(self, name):
        return Collection(self.store, name)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(workflow.firebase_app, "db", lambda: fake)
    fake.store["cases"]["c1"] = {
        "status": "received", "registrar_uid": "reg1", "reviewer_uids": [],
        "flags": {"quality_check": True, "mismatch": False}, "completed_at": None,
    }
    return fake


def run(db, user, action, case_id="c1", **kwargs):
    """transition()과 같은 일을 가짜 트랜잭션으로 한다."""
    tx = Transaction(db.store)
    status = workflow.apply(tx, user, case_id, action, **kwargs)
    tx.commit()
    return status


def case(db):
    return db.store["cases"]["c1"]


def events(db):
    return [(e["action"], e["from_status"], e["to_status"], e["actor_uid"]) for e in db.store["case_events"].values()]


# --- 전이 표 ---

def test_table_uses_only_defined_statuses_and_labels():
    for action, t in workflow.TRANSITIONS.items():
        assert t.from_status in config.STATUSES + (None,)
        assert t.to_status in config.STATUSES
        assert t.role in config.ROLES + ("system",)
        assert action in config.LABELS
    # 모든 상태에 들어오는 전이가 있다
    assert {t.to_status for t in workflow.TRANSITIONS.values()} == set(config.STATUSES)


# --- 정상 흐름 ---

def test_full_flow_records_every_change(db):
    assert run(db, MANAGER, "assign", reviewer_uids=["revA", "revB"]) == "assigned"
    assert case(db)["reviewer_uids"] == ["revA", "revB"]
    assert run(db, REV_A, "start_review") == "in_review"
    assert run(db, workflow.SYSTEM, "auto_mismatch") == "arbitration"
    assert case(db)["flags"] == {"quality_check": True, "mismatch": True}  # 다른 표시는 그대로
    assert run(db, MANAGER, "arbitrate") == "done"
    assert case(db)["completed_at"] is not None
    assert run(db, MANAGER, "reopen", reason="ROI 위치 재확인") == "in_review"
    assert case(db)["completed_at"] is None
    assert run(db, workflow.SYSTEM, "auto_match") == "done"

    assert events(db) == [
        ("assign", "received", "assigned", "man1"),
        ("start_review", "assigned", "in_review", "revA"),
        ("auto_mismatch", "in_review", "arbitration", "system"),
        ("arbitrate", "arbitration", "done", "man1"),
        ("reopen", "done", "in_review", "man1"),
        ("auto_match", "in_review", "done", "system"),
    ]
    reopen = list(db.store["case_events"].values())[4]
    assert reopen["case_id"] == "c1" and reopen["reason"] == "ROI 위치 재확인"


def test_revision_round_trip(db):
    case(db).update(status="in_review", reviewer_uids=["revA", "revB"])
    assert run(db, REV_B, "request_revision", reason="  영상이 잘림  ") == "revision_requested"
    assert list(db.store["case_events"].values())[0]["reason"] == "영상이 잘림"
    assert run(db, REGISTRAR, "revision_done") == "in_review"


# --- 거절 ---

def assert_unchanged(db, status):
    assert case(db)["status"] == status
    assert db.store["case_events"] == {}


@pytest.mark.parametrize("action", ["start_review", "arbitrate", "reopen", "revision_done", "register", "nope"])
def test_rejects_transitions_not_in_table(db, action):
    case(db)["reviewer_uids"] = ["revA", "revB"]  # 담당 범위 검사는 통과하고 상태 검사에서 걸리게 한다
    user = {"start_review": REV_A, "revision_done": REGISTRAR, "register": REGISTRAR}.get(action, MANAGER)
    with pytest.raises(workflow.TransitionError):
        run(db, user, action, reason="사유")
    assert_unchanged(db, "received")


def test_second_click_is_rejected(db):
    run(db, MANAGER, "assign", reviewer_uids=["revA", "revB"])
    with pytest.raises(workflow.TransitionError, match="지금 상태\\(배정됨\\)"):
        run(db, MANAGER, "assign", reviewer_uids=["revA", "revB"])
    assert len(db.store["case_events"]) == 1


def test_rejects_wrong_role(db):
    with pytest.raises(PermissionError, match="관리 담당자"):
        run(db, REV_A, "assign", reviewer_uids=["revA", "revB"])
    case(db)["status"] = "in_review"
    with pytest.raises(PermissionError, match="시스템"):
        run(db, MANAGER, "auto_match")  # 사람은 자동 판정을 대신할 수 없다
    with pytest.raises(PermissionError):
        run(db, None, "auto_match")


def test_rejects_users_outside_their_cases(db):
    case(db).update(status="assigned", reviewer_uids=["revA", "revB"])
    with pytest.raises(CaseError, match="찾을 수 없습니다"):
        run(db, REV_OTHER, "start_review")
    case(db)["status"] = "revision_requested"
    with pytest.raises(CaseError):
        run(db, OTHER_REGISTRAR, "revision_done")
    assert db.store["case_events"] == {}


def test_missing_case(db):
    with pytest.raises(CaseError):
        run(db, MANAGER, "assign", case_id="nope", reviewer_uids=["revA", "revB"])


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_required(db, reason):
    case(db).update(status="in_review", reviewer_uids=["revA", "revB"])
    with pytest.raises(workflow.TransitionError, match="사유"):
        run(db, REV_A, "request_revision", reason=reason)
    case(db)["status"] = "done"
    with pytest.raises(workflow.TransitionError, match="사유"):
        run(db, MANAGER, "reopen", reason=reason)


@pytest.mark.parametrize("uids", [None, [], ["revA"], ["revA", "revA"], ["revA", "revB", "revC"], ["revA", ""]])
def test_assign_needs_two_different_reviewers(db, uids):
    with pytest.raises(workflow.TransitionError, match="2명"):
        run(db, MANAGER, "assign", reviewer_uids=uids)
    assert_unchanged(db, "received")


@pytest.mark.parametrize("uids", [["revA", "man1"], ["revA", "ghost"]])
def test_assign_only_reviewer_accounts(db, uids):
    with pytest.raises(workflow.TransitionError, match="검토 담당자 계정만"):
        run(db, MANAGER, "assign", reviewer_uids=uids)
    assert_unchanged(db, "received")


# --- 화면용 ---

def test_allowed_actions(db):
    c = {"id": "c1", **case(db)}
    assert workflow.allowed_actions(MANAGER, c) == ["assign"]
    assert workflow.allowed_actions(REGISTRAR, c) == []
    c.update(status="in_review", reviewer_uids=["revA", "revB"])
    assert workflow.allowed_actions(REV_A, c) == ["request_revision"]  # 자동 판정은 버튼으로 보이지 않는다
    assert workflow.allowed_actions(REV_OTHER, c) == []
    assert workflow.allowed_actions(None, c) == []


def test_transition_wraps_unexpected_errors(db, monkeypatch):
    class BrokenDb(FakeDb):
        def transaction(self):
            return Transaction(self.store)

        def collection(self, name):
            raise RuntimeError("network down")
    monkeypatch.setattr(workflow.firestore, "transactional", lambda fn: lambda tx: fn(tx))
    monkeypatch.setattr(workflow.firebase_app, "db", lambda: BrokenDb())
    with pytest.raises(workflow.TransitionError, match="다시 시도"):
        workflow.transition(MANAGER, "c1", "assign", reviewer_uids=["revA", "revB"])


def test_plan_uses_given_time():
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    c = {"id": "c1", "status": "arbitration", "registrar_uid": "reg1", "reviewer_uids": []}
    updates, event = workflow.plan(MANAGER, c, "arbitrate", now=now)
    assert updates == {"status": "done", "updated_at": now, "completed_at": now}
    assert event["at"] == now and event["reason"] is None


# --- 화면용 조회 ---

def test_list_events_in_order_and_only_for_viewers(db):
    run(db, MANAGER, "assign", reviewer_uids=["revA", "revB"])
    run(db, REV_A, "start_review")
    rows = workflow.list_events(REGISTRAR, "c1")
    assert [r["action"] for r in rows] == ["assign", "start_review"]
    with pytest.raises(CaseError):
        workflow.list_events(OTHER_REGISTRAR, "c1")
    with pytest.raises(CaseError):
        workflow.list_events(REV_OTHER, "c1")


def test_reviewer_accounts_only_for_manager(db):
    assert [r["uid"] for r in workflow.reviewer_accounts(MANAGER)] == ["revB", "revA", "revC"]  # 이름 순
    with pytest.raises(PermissionError):
        workflow.reviewer_accounts(REV_A)


def test_display_names(db):
    names = workflow.display_names(REGISTRAR, ["revA", "revB", "system", "ghost", None])
    assert names == {"revA": "검토자 A", "revB": "b@pacs.test", "system": "시스템", "ghost": "ghost"}
    with pytest.raises(PermissionError):
        workflow.display_names(None, ["revA"])
