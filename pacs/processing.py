"""알고리즘 실행과 처리 이력 저장 (담당: 안진성).

- 원본은 바꾸지 않는다. 결과는 results/{영상ID}/{처리이력ID}.png에 따로 저장한다.
- 처리 이력(processing_logs)에는 영상 ID, 알고리즘·버전, 설정값, ROI, 결과 위치, 특징값, 실행자, 시간을 남긴다.
- 같은 사람이 같은 영상·알고리즘·버전·설정값·ROI로 다시 실행하면 새 기록을 만들지 않고 기존 기록을 돌려준다.
  처리 이력 ID를 이 값들로 만들기 때문이다. 버튼을 여러 번 눌러도 기록은 하나다.
- 파일과 기록이 어긋나지 않게 한다. 파일 저장이 실패하면 status "failed"로 기록을 남기고,
  기록 저장이 실패하면 실제로 저장됐는지 확인한 뒤 저장되지 않았을 때만 결과 파일을 지운다 (cases.register_case와 같은 방식).
- 검토 담당자는 본인이 실행한 기록만 볼 수 있다. 처리 이력에는 ROI가 들어 있어,
  상대 검토자의 기록을 보면 블라인드 규칙이 깨지기 때문이다.
"""
import hashlib
import io
import json
from datetime import datetime, timezone

from google.cloud.firestore_v1.base_query import FieldFilter
from PIL import Image

from pacs import algorithms, firebase_app, quality, roi as roi_mod, viewer
from pacs.auth import require_role
from pacs.cases import CaseError, data_dir, get_case, load_image

# 처리 결과를 저장할 수 있는 상태. 검토자가 영상처리를 하는 단계는 "검토 중"이다 (노션 2·3장).
PROCESS_STATUSES = ("in_review",)


class ProcessingError(Exception):
    """사용자에게 그대로 보여줄 수 있는 처리 실패."""


def log_id_for(image_id, uid, algorithm, version, params, roi):
    """같은 실행이면 같은 ID가 나온다. 중복 기록을 막는 데 쓴다."""
    key = json.dumps([image_id, uid, algorithm, version, params, roi], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def features(original, result, roi=None):
    """처리 전후 비교에 쓸 특징값. Firestore에 그대로 저장할 수 있는 형태다.

    - before / after: 영상 전체의 품질 지표 4개 (quality.measure)
    - roi_before / roi_after: ROI 안의 픽셀 수·평균·분산·표준편차·히스토그램 (ROI가 있을 때만)
    """
    out = {
        "before": {k: round(v, 2) for k, v in quality.measure(original).items()},
        "after": {k: round(v, 2) for k, v in quality.measure(result).items()},
    }
    if roi is not None:
        out["roi_before"] = roi_mod.roi_stats(original, roi)
        out["roi_after"] = roi_mod.roi_stats(result, roi)
    return out


def run(algorithm, image, params):
    """알고리즘을 실행해 결과 영상을 돌려준다. 저장은 하지 않는다 (미리 보기용)."""
    module = algorithms.available().get(algorithm)
    if module is None:
        raise ProcessingError("사용할 수 없는 알고리즘입니다.")
    try:
        result = module.apply(image, **params)
    except TypeError as e:  # PARAMS에 없는 설정값 이름
        raise ProcessingError("알고리즘 설정값이 올바르지 않습니다.") from e
    except ValueError as e:  # 알고리즘이 이유를 한글로 적어 둔다 (README "서로 맞춰야 하는 부분")
        raise ProcessingError(str(e)) from e
    if result.shape != image.shape or result is image:
        raise ProcessingError("알고리즘 결과가 올바르지 않습니다.")
    return result


def save(user, case_id, algorithm, params, roi=None):
    """알고리즘을 실행하고 결과 파일과 처리 이력을 저장한다. (처리 이력 ID, 새로 만들었는지)를 돌려준다.

    본인에게 배정된 "검토 중" 케이스에서 검토 담당자만 할 수 있다.
    """
    require_role(user, "reviewer")
    case = get_case(user, case_id)  # 배정되지 않은 케이스는 "찾을 수 없습니다"
    if case.get("status") not in PROCESS_STATUSES:
        raise ProcessingError("검토 중인 케이스에서만 처리 결과를 저장할 수 있습니다.")
    image = load_image(user, case["target_image_id"])
    if image["bytes"] is None:
        raise ProcessingError("이 컴퓨터에 원본 영상 파일이 없어 처리할 수 없습니다.")
    original = viewer.to_gray(image["bytes"])
    try:
        roi = roi_mod.validate_roi(roi, original.shape[1], original.shape[0])
    except roi_mod.RoiError as e:
        raise ProcessingError(str(e)) from e

    module = algorithms.available().get(algorithm)
    if module is None:
        raise ProcessingError("사용할 수 없는 알고리즘입니다.")
    log_id = log_id_for(image["id"], user["uid"], algorithm, module.VERSION, params, roi)
    db = firebase_app.db()
    log_ref = db.collection("processing_logs").document(log_id)
    rel_path = f"results/{image['id']}/{log_id}.png"
    file_path = data_dir() / rel_path

    existing = log_ref.get()
    if existing.exists and existing.to_dict().get("status") == "saved" and file_path.exists():
        return log_id, False  # 같은 실행이 이미 저장돼 있다

    result = run(algorithm, original, params)
    record = {
        "case_id": case_id,
        "image_id": image["id"],
        "algorithm": algorithm,
        "algorithm_version": module.VERSION,
        "params": params,
        "roi": roi,
        "result_path": rel_path,
        "features": features(original, result, roi),
        "recommended": algorithm in ((image.get("quality") or {}).get("recommend") or []),
        "status": "saved",
        "executed_by": user["uid"],
        "executed_at": datetime.now(timezone.utc),
    }

    # 1) 결과 파일을 먼저 저장한다.
    try:
        buf = io.BytesIO()
        Image.fromarray(result).save(buf, format="PNG")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(buf.getvalue())
    except OSError as e:
        # 실패도 기록으로 남긴다. 기록 저장까지 실패하면 남길 방법이 없으니 안내만 한다.
        try:
            log_ref.set({**record, "status": "failed", "result_path": None})
        except Exception:
            pass
        raise ProcessingError("처리 결과 파일을 저장하지 못했습니다. 저장 폴더를 확인해 주세요.") from e

    # 2) 기록을 저장한다.
    try:
        log_ref.set(record)
    except Exception as e:
        # 응답만 끊기고 저장은 됐을 수 있다. 저장되지 않은 것이 확실할 때만 파일을 지운다.
        try:
            saved = log_ref.get().exists
        except Exception:
            saved = None
        if saved:
            return log_id, True
        if saved is False:
            file_path.unlink(missing_ok=True)
            raise ProcessingError("처리 이력을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.") from e
        raise ProcessingError(
            "저장 결과를 확인하지 못했습니다. 잠시 후 처리 이력에서 저장됐는지 확인해 주세요."
        ) from e
    return log_id, True


def _visible(user, log):
    return user["role"] != "reviewer" or log.get("executed_by") == user["uid"]


def list_logs(user, case_id):
    """케이스의 처리 이력을 최근 순으로 돌려준다. 검토 담당자에게는 본인 기록만 돌려준다."""
    get_case(user, case_id)  # 볼 수 있는 케이스인지 확인 (역할·담당 범위)
    query = firebase_app.db().collection("processing_logs").where(filter=FieldFilter("case_id", "==", case_id))
    if user["role"] == "reviewer":
        query = query.where(filter=FieldFilter("executed_by", "==", user["uid"]))
    rows = [{"id": d.id, **d.to_dict()} for d in query.stream()]
    rows = [r for r in rows if _visible(user, r)]  # 쿼리가 바뀌어도 블라인드 규칙은 지킨다
    rows.sort(key=lambda r: r.get("executed_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


def load_result(user, log_id):
    """처리 이력 1건과 결과 파일 바이트를 돌려준다. 파일이 없으면 bytes는 None이다."""
    doc = firebase_app.db().collection("processing_logs").document(log_id).get()
    log = {"id": doc.id, **doc.to_dict()} if doc.exists else None
    if log is None:
        raise CaseError("처리 이력을 찾을 수 없습니다.")
    get_case(user, log["case_id"])  # 케이스를 볼 권한 확인
    if not _visible(user, log):
        raise CaseError("처리 이력을 찾을 수 없습니다.")
    path = data_dir() / log["result_path"] if log.get("result_path") else None
    log["bytes"] = path.read_bytes() if path and path.exists() else None
    return log
