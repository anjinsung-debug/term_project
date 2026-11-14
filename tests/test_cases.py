import io
import itertools
from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists
from PIL import Image

from pacs import cases, viewer

REGISTRAR = {"uid": "reg1", "role": "registrar"}
OTHER_REGISTRAR = {"uid": "reg2", "role": "registrar"}
REVIEWER = {"uid": "rev1", "role": "reviewer"}
MANAGER = {"uid": "man1", "role": "manager"}


def make_image(fmt="PNG", size=(512, 512)):
    buf = io.BytesIO()
    Image.new("L", size, 128).save(buf, format=fmt)
    return buf.getvalue()


# --- Firestore를 흉내 내는 최소한의 가짜 객체 (실제 데이터를 건드리지 않기 위함) ---

class Snap:
    def __init__(self, doc_id, data):
        self.id, self._data, self.exists = doc_id, data, data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, store, name, doc_id):
        self.store, self.name, self.id = store, name, doc_id

    def get(self):
        if self.store.get("_fail_get"):
            raise RuntimeError("network down")
        return Snap(self.id, self.store[self.name].get(self.id))


class Query:
    OPS = {
        "==": lambda v, x: v == x,
        "array_contains": lambda v, x: x in (v or []),
    }

    def __init__(self, store, name, filters=(), limit=None):
        self.store, self.name, self.filters, self._limit = store, name, filters, limit

    def where(self, filter):
        return Query(self.store, self.name, self.filters + (filter,), self._limit)

    def limit(self, n):
        return Query(self.store, self.name, self.filters, n)

    def stream(self):
        if self.store.get("_hide_queries"):  # 동시 등록: 상대가 아직 저장하기 전에 확인한 상황
            return []
        rows = [
            Snap(i, d) for i, d in self.store[self.name].items()
            if all(self.OPS[f.op_string](d.get(f.field_path), f.value) for f in self.filters)
        ]
        return rows[: self._limit] if self._limit else rows

    get = stream


class Collection(Query):
    def document(self, doc_id=None):
        return Ref(self.store, self.name, doc_id or f"{self.name}-{next(self.store['_ids'])}")


class Batch:
    def __init__(self, db):
        self.db, self.ops = db, []

    def set(self, ref, data):
        self.ops.append((ref, data, False))

    def create(self, ref, data):
        self.ops.append((ref, data, True))

    def commit(self):
        if self.db.fail_commit:
            raise RuntimeError("network down")
        # Firestore처럼 create는 문서가 이미 있으면 묶음 전체가 실패한다
        for ref, _, must_be_new in self.ops:
            if must_be_new and ref.id in self.db.store[ref.name]:
                raise AlreadyExists("document already exists")
        for ref, data, _ in self.ops:
            self.db.store[ref.name][ref.id] = data
        if self.db.lose_response:  # 저장은 됐는데 응답이 끊긴 상황
            raise RuntimeError("deadline exceeded")


class FakeDb:
    def __init__(self):
        self.store = {"cases": {}, "images": {}, "case_events": {}, "mock_ids": {}, "_ids": itertools.count(1)}
        self.fail_commit = False
        self.lose_response = False

    def collection(self, name):
        return Collection(self.store, name)

    def batch(self):
        return Batch(self)


@pytest.fixture
def db(monkeypatch, tmp_path):
    fake = FakeDb()
    monkeypatch.setattr(cases.firebase_app, "db", lambda: fake)
    monkeypatch.setattr(cases, "data_dir", lambda: tmp_path)
    fake.tmp_path = tmp_path
    return fake


# --- 영상 파일 검사 ---

def test_validate_image_accepts_png_and_jpeg():
    assert cases.validate_image(make_image("PNG"))["format"] == "png"
    info = cases.validate_image(make_image("JPEG", (300, 400)))
    assert (info["format"], info["width"], info["height"]) == ("jpeg", 300, 400)


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "비어 있습니다"),
        (b"not an image", "읽을 수 없습니다"),
        (make_image("GIF"), "지원하지 않는 형식"),
        (make_image("PNG", (100, 600)), "너무 작습니다"),
    ],
)
def test_validate_image_rejects_bad_files(data, message):
    with pytest.raises(cases.CaseError, match=message):
        cases.validate_image(data)


def test_validate_image_rejects_truncated_file():
    data = make_image("PNG")
    with pytest.raises(cases.CaseError):
        cases.validate_image(data[: len(data) // 2])


# --- 등록 ---

def test_register_saves_case_image_event_and_file(db):
    case_id = cases.register_case(REGISTRAR, " MOCK-1 ", "urgent", make_image())
    case = db.store["cases"][case_id]
    assert case["mock_id"] == "MOCK-1" and case["status"] == "received"
    assert case["registrar_uid"] == "reg1" and case["reviewer_uids"] == []
    image = db.store["images"][case["target_image_id"]]
    assert image["case_id"] == case_id and image["format"] == "png"
    assert (db.tmp_path / image["storage_path"]).read_bytes() == make_image()  # 원본 그대로 저장
    [event] = db.store["case_events"].values()
    assert event["to_status"] == "received" and event["actor_uid"] == "reg1"


def test_register_only_by_registrar(db):
    with pytest.raises(PermissionError):
        cases.register_case(REVIEWER, "MOCK-1", "urgent", make_image())
    assert db.store["cases"] == {}


def test_register_rejects_duplicate_mock_id(db):
    cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    with pytest.raises(cases.CaseError, match="이미 등록된"):
        cases.register_case(REGISTRAR, "MOCK-1", "routine", make_image())
    assert len(db.store["cases"]) == 1


def test_register_requires_mock_id_and_urgency(db):
    with pytest.raises(cases.CaseError, match="ID를 입력"):
        cases.register_case(REGISTRAR, "  ", "urgent", make_image())
    with pytest.raises(cases.CaseError, match="긴급도"):
        cases.register_case(REGISTRAR, "MOCK-1", None, make_image())


def test_register_removes_file_when_record_fails(db):
    db.fail_commit = True
    with pytest.raises(cases.CaseError, match="저장하지 못했습니다"):
        cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    assert not list(db.tmp_path.rglob("*.png"))  # 파일만 남지 않는다
    assert db.store["cases"] == {}


def test_register_keeps_file_when_saved_but_response_lost(db):
    # 문제 1: Firestore에는 저장됐는데 응답이 끊기면, 파일을 지우지 않고 등록 성공으로 본다
    db.lose_response = True
    case_id = cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    image = db.store["images"][db.store["cases"][case_id]["target_image_id"]]
    assert (db.tmp_path / image["storage_path"]).exists()


def test_register_keeps_file_when_result_cannot_be_checked(db):
    # 저장됐는지 확인조차 안 되면 파일을 남기고, 목록에서 확인하라고 안내한다
    db.fail_commit = True
    db.store["_fail_get"] = True
    with pytest.raises(cases.CaseError, match="확인하지 못했습니다"):
        cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    assert len(list(db.tmp_path.rglob("*.png"))) == 1


def test_register_rejects_duplicate_registered_at_the_same_time(db):
    # 문제 2: 두 사람이 동시에 확인해서 둘 다 "없음"을 본 경우에도 두 번째는 거절된다
    cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    db.store["_hide_queries"] = True
    with pytest.raises(cases.CaseError, match="이미 등록된"):
        cases.register_case(REGISTRAR, "MOCK-1", "routine", make_image())
    db.store["_hide_queries"] = False
    assert len(db.store["cases"]) == 1
    assert len(list(db.tmp_path.rglob("*.png"))) == 1  # 거절된 쪽 파일은 남지 않는다


@pytest.mark.parametrize("bad_id", ["a/b", ".", "..", "__x__", "가" * 70])
def test_register_rejects_mock_id_that_cannot_be_a_key(db, bad_id):
    with pytest.raises(cases.CaseError, match="모의 케이스 ID"):
        cases.register_case(REGISTRAR, bad_id, "urgent", make_image())


def truncated_jpeg():
    buf = io.BytesIO()
    Image.effect_noise((512, 512), 60).save(buf, format="JPEG")
    data = buf.getvalue()
    return data[: int(len(data) * 0.6)]


def test_validate_image_rejects_truncated_jpeg():
    # 문제 3: 뒤가 잘린 JPEG는 verify()만으로는 통과해 버린다
    with pytest.raises(cases.CaseError, match="읽을 수 없습니다"):
        cases.validate_image(truncated_jpeg())


def test_to_gray_explains_unreadable_file():
    # 문제 3: 이미 저장된 손상 파일을 열어도 화면이 깨지지 않고 이유를 안내할 수 있어야 한다
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        viewer.to_gray(truncated_jpeg())


# --- 조회 ---

def seed(db):
    def add(case_id, mock_id, registrar, reviewers, status="received", urgency="routine", day=1):
        db.store["cases"][case_id] = {
            "mock_id": mock_id, "registrar_uid": registrar, "reviewer_uids": reviewers,
            "status": status, "urgency": urgency,
            "registered_at": datetime(2026, 11, day, tzinfo=timezone.utc),
        }
    add("c1", "MOCK-A", "reg1", ["rev1"], day=1)
    add("c2", "MOCK-B", "reg1", [], status="done", urgency="urgent", day=3)
    add("c3", "MOCK-C", "reg2", ["rev1"], day=2)


def test_list_cases_by_role(db):
    seed(db)
    assert [r["id"] for r in cases.list_cases(REGISTRAR)] == ["c2", "c1"]  # 최근 등록 순
    assert [r["id"] for r in cases.list_cases(REVIEWER)] == ["c3", "c1"]
    assert [r["id"] for r in cases.list_cases(MANAGER)] == ["c2", "c3", "c1"]


def test_list_cases_filters(db):
    seed(db)
    assert [r["id"] for r in cases.list_cases(MANAGER, status="done")] == ["c2"]
    assert [r["id"] for r in cases.list_cases(MANAGER, urgency="routine")] == ["c3", "c1"]
    assert [r["id"] for r in cases.list_cases(MANAGER, mock_id_query=" mock-c ")] == ["c3"]


def test_get_case_hides_cases_user_cannot_see(db):
    seed(db)
    assert cases.get_case(REVIEWER, "c3")["mock_id"] == "MOCK-C"
    for user, case_id in [(OTHER_REGISTRAR, "c1"), (REVIEWER, "c2"), (MANAGER, "nope")]:
        with pytest.raises(cases.CaseError, match="찾을 수 없습니다"):
            cases.get_case(user, case_id)


def test_load_image_returns_none_bytes_when_file_missing(db):
    case_id = cases.register_case(REGISTRAR, "MOCK-1", "urgent", make_image())
    image_id = db.store["cases"][case_id]["target_image_id"]
    assert cases.load_image(REGISTRAR, image_id)["bytes"] == make_image()
    (db.tmp_path / db.store["images"][image_id]["storage_path"]).unlink()
    assert cases.load_image(REGISTRAR, image_id)["bytes"] is None
    with pytest.raises(cases.CaseError):
        cases.load_image(OTHER_REGISTRAR, image_id)


def test_format_kst():
    assert cases.format_kst(datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)) == "2026-11-15 00:00"
    assert cases.format_kst(None) == "-"
