"""케이스와 영상의 등록·조회.

- 권한 검사는 각 함수 맨 앞에서 require_role로 한다.
- 영상 파일은 data_dir 폴더에, 파일 위치와 정보는 Firestore에 저장한다 (README "영상 파일 저장").
- 파일 저장과 Firestore 기록이 어긋나지 않게, 기록이 실패하면 방금 저장한 파일을 지운다.
- 필드 이름은 노션 설계 문서 4-1을 따른다.
"""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
from google.cloud.firestore_v1.base_query import FieldFilter
from PIL import Image, UnidentifiedImageError

from pacs import config, firebase_app
from pacs.auth import require_role


KST = timezone(timedelta(hours=9))


class CaseError(Exception):
    """사용자에게 그대로 보여줄 수 있는 등록·조회 실패."""


def format_kst(dt):
    """저장은 UTC, 화면은 한국 시간으로 보여준다."""
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M") if dt else "-"


def data_dir():
    try:
        return Path(st.secrets.get("storage", {}).get("data_dir", "data"))
    except FileNotFoundError:
        return Path("data")


def validate_image(data):
    """올린 파일이 지원하는 영상인지 확인하고 {"format", "width", "height", "size_bytes"}를 돌려준다."""
    if not data:
        raise CaseError("파일이 비어 있습니다.")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise CaseError(f"파일이 너무 큽니다. {config.MAX_UPLOAD_MB}MB 이하만 올릴 수 있습니다.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # 파일이 깨졌는지 확인
        with Image.open(io.BytesIO(data)) as img:  # verify 뒤에는 다시 열어야 크기를 읽을 수 있다
            fmt, (width, height) = (img.format or "").lower(), img.size
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise CaseError("영상 파일을 읽을 수 없습니다. 파일이 손상되었거나 영상이 아닙니다.") from e
    if fmt not in config.SUPPORTED_FORMATS:
        raise CaseError(f"지원하지 않는 형식입니다({fmt or '알 수 없음'}). PNG 또는 JPEG만 올릴 수 있습니다.")
    if min(width, height) < config.MIN_IMAGE_SIDE:
        raise CaseError(
            f"영상이 너무 작습니다({width}×{height}). 가로·세로 모두 {config.MIN_IMAGE_SIDE}픽셀 이상이어야 합니다."
        )
    return {"format": fmt, "width": width, "height": height, "size_bytes": len(data)}


def register_case(user, mock_id, urgency, image_data):
    """케이스 1건과 영상 1장을 등록하고 케이스 ID를 돌려준다. 등록 담당자만 할 수 있다."""
    require_role(user, "registrar")
    mock_id = mock_id.strip()
    if not mock_id:
        raise CaseError("모의 케이스 ID를 입력해 주세요.")
    if urgency not in config.URGENCIES:
        raise CaseError("긴급도를 선택해 주세요.")
    info = validate_image(image_data)

    db = firebase_app.db()
    cases = db.collection("cases")
    # 같은 모의 ID가 있으면 거절한다. 등록 버튼을 두 번 눌러 같은 케이스가 두 번 생기는 것도 이것으로 막는다.
    if cases.where(filter=FieldFilter("mock_id", "==", mock_id)).limit(1).get():
        raise CaseError(f"이미 등록된 모의 케이스 ID입니다: {mock_id}")

    case_ref = cases.document()
    image_ref = db.collection("images").document()
    event_ref = db.collection("case_events").document()
    now = datetime.now(timezone.utc)

    # 1) 파일을 먼저 저장한다. 원본 바이트를 그대로 쓰고 변환하지 않는다.
    rel_path = f"originals/{case_ref.id}/{image_ref.id}.{config.FILE_EXTENSIONS[info['format']]}"
    file_path = data_dir() / rel_path
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(image_data)
    except OSError as e:
        raise CaseError("영상 파일을 저장하지 못했습니다. 저장 폴더를 확인해 주세요.") from e

    # 2) 케이스, 영상, 상태 기록을 한 번에 저장한다. 셋 중 하나만 저장되는 일은 없다.
    batch = db.batch()
    batch.set(case_ref, {
        "mock_id": mock_id,
        "exam_type": "chest_xray",
        "urgency": urgency,
        "status": "received",
        "registrar_uid": user["uid"],
        "reviewer_uids": [],
        "target_image_id": image_ref.id,
        "flags": {"quality_check": False, "mismatch": False},
        "registered_at": now,
        "updated_at": now,
        "completed_at": None,
    })
    batch.set(image_ref, {
        "case_id": case_ref.id,
        "storage_path": rel_path,
        "format": info["format"],
        "width": info["width"],
        "height": info["height"],
        "size_bytes": info["size_bytes"],
        "uploaded_by": user["uid"],
        "uploaded_at": now,
        "quality": None,  # 품질 자동 점검(pacs/quality.py)을 만든 뒤 채운다
        "proceed_reason": None,
    })
    batch.set(event_ref, {
        "case_id": case_ref.id,
        "action": "register",
        "from_status": None,
        "to_status": "received",
        "actor_uid": user["uid"],
        "reason": None,
        "at": now,
    })
    try:
        batch.commit()
    except Exception as e:
        # 3) 기록이 실패하면 방금 저장한 파일을 지워 파일만 남는 일을 막는다.
        file_path.unlink(missing_ok=True)
        raise CaseError("케이스를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.") from e
    return case_ref.id


def list_cases(user, status=None, urgency=None, mock_id_query=""):
    """볼 수 있는 케이스 목록을 최근 등록 순으로 돌려준다. 각 항목에 "id"가 들어 있다.

    - 등록 담당자: 본인이 등록한 케이스
    - 검토 담당자: 본인에게 배정된 케이스
    - 관리 담당자: 전체
    """
    require_role(user, *config.ROLES)
    query = firebase_app.db().collection("cases")
    if user["role"] == "registrar":
        query = query.where(filter=FieldFilter("registrar_uid", "==", user["uid"]))
    elif user["role"] == "reviewer":
        query = query.where(filter=FieldFilter("reviewer_uids", "array_contains", user["uid"]))

    rows = [{"id": d.id, **d.to_dict()} for d in query.stream()]
    # 검색·필터와 정렬은 가져온 뒤 파이썬에서 한다.
    # ponytail: 전체를 가져와 거른다. 케이스가 수천 건이 되면 Firestore 색인과 쿼리 조건으로 옮긴다.
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if urgency:
        rows = [r for r in rows if r.get("urgency") == urgency]
    if mock_id_query.strip():
        q = mock_id_query.strip().lower()
        rows = [r for r in rows if q in r.get("mock_id", "").lower()]
    rows.sort(key=lambda r: r.get("registered_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def can_view(user, case):
    role = user.get("role")
    if role == "manager":
        return True
    if role == "registrar":
        return case.get("registrar_uid") == user["uid"]
    if role == "reviewer":
        return user["uid"] in case.get("reviewer_uids", [])
    return False


def get_case(user, case_id):
    """케이스 1건을 돌려준다. 볼 권한이 없거나 없는 케이스면 같은 오류를 낸다."""
    require_role(user, *config.ROLES)
    doc = firebase_app.db().collection("cases").document(case_id).get()
    case = doc.to_dict() if doc.exists else None
    # 없는 케이스와 권한 없는 케이스를 구분하지 않는다. 남의 케이스 ID가 있는지 알려주지 않기 위해서다.
    if not case or not can_view(user, case):
        raise CaseError("케이스를 찾을 수 없습니다.")
    return {"id": doc.id, **case}


def load_image(user, image_id):
    """영상 정보와 파일 바이트를 돌려준다. 파일이 없으면 bytes는 None이다."""
    require_role(user, *config.ROLES)
    doc = firebase_app.db().collection("images").document(image_id).get()
    if not doc.exists:
        raise CaseError("영상을 찾을 수 없습니다.")
    image = {"id": doc.id, **doc.to_dict()}
    get_case(user, image["case_id"])  # 영상이 속한 케이스를 볼 권한이 있는지 확인
    path = data_dir() / image["storage_path"]
    # 개발 중에는 다른 사람이 등록한 영상 파일이 내 컴퓨터에 없을 수 있다.
    image["bytes"] = path.read_bytes() if path.exists() else None
    return image
