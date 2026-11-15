import io
from datetime import datetime, timezone

import numpy as np
import pytest
from PIL import Image

from pacs import cases, processing
from pacs.cases import CaseError

REV_A = {"uid": "revA", "role": "reviewer"}
REV_B = {"uid": "revB", "role": "reviewer"}
REV_OTHER = {"uid": "revC", "role": "reviewer"}
REGISTRAR = {"uid": "reg1", "role": "registrar"}
MANAGER = {"uid": "man1", "role": "manager"}


# --- Firestore를 흉내 내는 최소한의 가짜 객체 ---

class Snap:
    def __init__(self, doc_id, data):
        self.id, self._data, self.exists = doc_id, data, data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, db, name, doc_id):
        self.db, self.name, self.id = db, name, doc_id

    def get(self):
        if self.db.fail_get:
            raise RuntimeError("network down")
        return Snap(self.id, self.db.store[self.name].get(self.id))

    def set(self, data):
        self.db.set_calls.append(data.get("status"))
        if self.db.fail_set:
            raise RuntimeError("network down")
        self.db.store[self.name][self.id] = dict(data)
        if self.db.lose_response:  # 저장은 됐는데 응답이 끊긴 상황
            raise RuntimeError("deadline exceeded")


class Query:
    def __init__(self, db, name, filters=()):
        self.db, self.name, self.filters = db, name, filters

    def where(self, filter):
        return Query(self.db, self.name, self.filters + (filter,))

    def stream(self):
        return [
            Snap(i, d) for i, d in self.db.store[self.name].items()
            if all(d.get(f.field_path) == f.value for f in self.filters)
        ]

    def document(self, doc_id):
        return Ref(self.db, self.name, doc_id)


class FakeDb:
    def __init__(self):
        self.store = {"cases": {}, "images": {}, "processing_logs": {}}
        self.fail_get = self.fail_set = self.lose_response = False
        self.set_calls = []

    def collection(self, name):
        return Query(self, name)


def png(array):
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
    return buf.getvalue()


ORIGINAL = (np.arange(256 * 256, dtype=np.uint32).reshape(256, 256) % 200 + 20).astype(np.uint8)
ROI = {"x": 10, "y": 20, "w": 30, "h": 40}


@pytest.fixture
def db(monkeypatch, tmp_path):
    fake = FakeDb()
    monkeypatch.setattr(cases.firebase_app, "db", lambda: fake)
    monkeypatch.setattr(cases, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(processing, "data_dir", lambda: tmp_path)
    fake.store["cases"]["c1"] = {
        "status": "in_review", "registrar_uid": "reg1", "reviewer_uids": ["revA", "revB"], "target_image_id": "i1",
    }
    fake.store["images"]["i1"] = {
        "case_id": "c1", "storage_path": "originals/c1/i1.png", "quality": {"recommend": ["clahe"]},
    }
    (tmp_path / "originals/c1").mkdir(parents=True)
    (tmp_path / "originals/c1/i1.png").write_bytes(png(ORIGINAL))
    fake.tmp_path = tmp_path
    return fake


def logs(db):
    return db.store["processing_logs"]


# --- 저장 ---

def test_save_writes_result_file_and_full_log(db):
    log_id, created = processing.save(REV_A, "c1", "clahe", {"clip_limit": 2.0, "tile_grid_size": 8}, ROI)
    assert created
    log = logs(db)[log_id]
    assert log["status"] == "saved"
    assert (log["case_id"], log["image_id"], log["algorithm"], log["executed_by"]) == ("c1", "i1", "clahe", "revA")
    assert log["algorithm_version"] == "1" and log["params"] == {"clip_limit": 2.0, "tile_grid_size": 8}
    assert log["roi"] == ROI and log["recommended"] is True
    assert set(log["features"]) == {"before", "after", "roi_before", "roi_after"}
    assert log["features"]["roi_before"]["pixels"] == 30 * 40
    assert isinstance(log["executed_at"], datetime)
    # 결과 파일이 저장되고, 원본은 그대로다
    result = np.asarray(Image.open(db.tmp_path / log["result_path"]))
    assert log["result_path"] == f"results/i1/{log_id}.png"
    assert result.shape == ORIGINAL.shape and not np.array_equal(result, ORIGINAL)
    assert (db.tmp_path / "originals/c1/i1.png").read_bytes() == png(ORIGINAL)


def test_save_without_roi(db):
    log_id, _ = processing.save(REV_A, "c1", "canny", {"low_threshold": 50, "high_threshold": 150})
    log = logs(db)[log_id]
    assert log["roi"] is None and log["recommended"] is False
    assert set(log["features"]) == {"before", "after"}


def test_same_run_twice_makes_one_log(db):
    params = {"clip_limit": 2.0, "tile_grid_size": 8}
    first = processing.save(REV_A, "c1", "clahe", params, ROI)
    second = processing.save(REV_A, "c1", "clahe", params, ROI)
    assert first == (first[0], True) and second == (first[0], False)
    assert len(logs(db)) == 1
    # 설정값이나 실행자가 다르면 다른 기록이다
    processing.save(REV_A, "c1", "clahe", {"clip_limit": 3.0, "tile_grid_size": 8}, ROI)
    processing.save(REV_B, "c1", "clahe", params, ROI)
    assert len(logs(db)) == 3


# --- 거절 ---

@pytest.mark.parametrize("user", [REGISTRAR, MANAGER, None])
def test_only_reviewers_save(db, user):
    with pytest.raises(PermissionError):
        processing.save(user, "c1", "clahe", {})
    assert logs(db) == {}


def test_unassigned_reviewer_cannot_save(db):
    with pytest.raises(CaseError, match="찾을 수 없습니다"):
        processing.save(REV_OTHER, "c1", "clahe", {})


@pytest.mark.parametrize("status", ["received", "assigned", "arbitration", "done", "revision_requested"])
def test_save_only_while_in_review(db, status):
    db.store["cases"]["c1"]["status"] = status
    with pytest.raises(processing.ProcessingError, match="검토 중"):
        processing.save(REV_A, "c1", "clahe", {})


@pytest.mark.parametrize("algorithm, params, roi, message", [
    ("nope", {}, None, "사용할 수 없는"),
    ("clahe", {"clip_limit": 99.0}, None, "대비 제한"),
    ("clahe", {"bogus": 1}, None, "설정값이 올바르지"),
    ("clahe", {}, {"x": 0, "y": 0, "w": 3, "h": 3}, "너무 작습니다"),
    ("clahe", {}, {"x": 250, "y": 0, "w": 20, "h": 20}, "벗어났습니다"),
])
def test_bad_input_is_explained_and_not_saved(db, algorithm, params, roi, message):
    with pytest.raises(processing.ProcessingError, match=message):
        processing.save(REV_A, "c1", algorithm, params, roi)
    assert logs(db) == {}
    assert not (db.tmp_path / "results").exists()


def test_missing_original_file(db):
    (db.tmp_path / "originals/c1/i1.png").unlink()
    with pytest.raises(processing.ProcessingError, match="원본 영상 파일이 없어"):
        processing.save(REV_A, "c1", "clahe", {})


# --- 파일과 기록이 어긋나지 않게 ---

def test_record_failure_removes_result_file(db):
    db.fail_set = True
    with pytest.raises(processing.ProcessingError, match="저장하지 못했습니다"):
        processing.save(REV_A, "c1", "clahe", {})
    assert list((db.tmp_path / "results/i1").iterdir()) == []


def test_keeps_file_when_saved_but_response_lost(db):
    db.lose_response = True
    log_id, created = processing.save(REV_A, "c1", "clahe", {})
    assert created and (db.tmp_path / logs(db)[log_id]["result_path"]).exists()


def test_file_failure_is_recorded_as_failed(db, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(processing.Image.Image, "save", broken)
    with pytest.raises(processing.ProcessingError, match="파일을 저장하지 못했습니다"):
        processing.save(REV_A, "c1", "clahe", {})
    (log,) = logs(db).values()
    assert log["status"] == "failed" and log["result_path"] is None
    # 다시 시도해 성공하면 같은 기록이 saved로 바뀐다
    monkeypatch.undo()
    monkeypatch.setattr(cases.firebase_app, "db", lambda: db)
    monkeypatch.setattr(cases, "data_dir", lambda: db.tmp_path)
    monkeypatch.setattr(processing, "data_dir", lambda: db.tmp_path)
    processing.save(REV_A, "c1", "clahe", {})
    (log,) = logs(db).values()
    assert log["status"] == "saved"


# --- 조회 ---

def test_reviewers_see_only_their_own_logs(db):
    a, _ = processing.save(REV_A, "c1", "clahe", {}, ROI)
    b, _ = processing.save(REV_B, "c1", "clahe", {}, {"x": 100, "y": 100, "w": 20, "h": 20})
    assert [r["id"] for r in processing.list_logs(REV_A, "c1")] == [a]
    assert {r["id"] for r in processing.list_logs(MANAGER, "c1")} == {a, b}
    assert processing.load_result(REV_A, a)["bytes"]
    with pytest.raises(CaseError):
        processing.load_result(REV_A, b)  # 상대 검토자의 ROI가 보이면 블라인드 규칙이 깨진다
    with pytest.raises(CaseError):
        processing.list_logs(REV_OTHER, "c1")


def test_list_logs_newest_first(db):
    for i, day in enumerate([1, 3, 2]):
        logs(db)[f"l{i}"] = {"case_id": "c1", "executed_by": "revA", "executed_at": datetime(2026, 11, day, tzinfo=timezone.utc)}
    assert [r["id"] for r in processing.list_logs(MANAGER, "c1")] == ["l1", "l2", "l0"]


def test_load_result_without_file(db):
    log_id, _ = processing.save(REV_A, "c1", "clahe", {})
    (db.tmp_path / logs(db)[log_id]["result_path"]).unlink()
    assert processing.load_result(MANAGER, log_id)["bytes"] is None
    with pytest.raises(CaseError):
        processing.load_result(MANAGER, "nope")


def test_log_id_is_stable():
    a = processing.log_id_for("i1", "u", "clahe", "1", {"b": 1, "a": 2}, ROI)
    assert a == processing.log_id_for("i1", "u", "clahe", "1", {"a": 2, "b": 1}, dict(reversed(list(ROI.items()))))
    assert a != processing.log_id_for("i1", "u", "clahe", "2", {"a": 2, "b": 1}, ROI)
