"""ROI 유효성 검사와 통계 (노션 설계 문서 6-2, 담당: 고영민).

ROI 규칙 (CLAUDE.md, 2026-11-13 확정):
- 영상당 1개, 사각형, 원본 영상의 픽셀 좌표 {"x", "y", "w", "h"}. x, y는 왼쪽 위 모서리다.
- 최소 크기(config.ROI_MIN_SIZE) 미만이면 거부하고 이유를 안내한다.
- "ROI 없음"(None) 제출을 허용한다.
"""
import numpy as np

from pacs import config


class RoiError(ValueError):
    """ROI가 규칙에 맞지 않을 때. 메시지는 화면에 그대로 보여준다."""


def validate_roi(roi, image_width, image_height, min_size=None):
    """ROI가 영상 안에 있고 최소 크기 이상인지 검사해, 정수 좌표로 정리한 ROI를 돌려준다.

    None은 "ROI 없음" 제출이므로 그대로 돌려준다. 문제가 있으면 RoiError를 낸다.
    """
    if roi is None:
        return None
    min_size = config.ROI_MIN_SIZE if min_size is None else min_size

    try:
        values = [roi[k] for k in ("x", "y", "w", "h")]
    except (KeyError, TypeError) as e:
        raise RoiError("ROI 좌표(x, y, w, h)가 올바르지 않습니다.") from e
    # 4.5처럼 소수가 들어오면 잘라서 쓰지 않고 거부한다. 뷰어는 항상 정수를 준다.
    if not all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in values):
        raise RoiError("ROI 좌표(x, y, w, h)는 정수여야 합니다.")
    x, y, w, h = (int(v) for v in values)

    if w < min_size or h < min_size:
        raise RoiError(f"ROI가 너무 작습니다({w}×{h}). 가로·세로 {min_size}픽셀 이상으로 그려 주세요.")
    if x < 0 or y < 0 or x + w > image_width or y + h > image_height:
        raise RoiError("ROI가 영상 범위를 벗어났습니다.")
    return {"x": x, "y": y, "w": w, "h": h}


def crop(image, roi):
    """영상에서 ROI 부분을 잘라낸다. 원본을 바꾸지 않도록 복사본을 돌려준다."""
    roi = validate_roi(roi, image.shape[1], image.shape[0])
    if roi is None:
        raise RoiError("ROI가 없어 영역을 잘라낼 수 없습니다.")
    return image[roi["y"]:roi["y"] + roi["h"], roi["x"]:roi["x"] + roi["w"]].copy()


def roi_stats(image, roi):
    """흑백 uint8 영상에서 ROI 안 픽셀의 통계를 돌려준다.

    {"pixels", "mean", "variance", "std", "histogram"}
    - histogram: 밝기 0~255 각 값의 픽셀 수 (256칸 목록). Firestore에 그대로 저장할 수 있다.
    """
    if not isinstance(image, np.ndarray) or image.ndim != 2 or image.dtype != np.uint8:
        raise RoiError("흑백 uint8 영상만 통계를 계산할 수 있습니다.")
    patch = crop(image, roi)
    histogram = np.bincount(patch.ravel(), minlength=256)
    return {
        "pixels": int(patch.size),
        "mean": round(float(patch.mean()), 2),
        "variance": round(float(patch.var()), 2),
        "std": round(float(patch.std()), 2),
        "histogram": histogram.tolist(),
    }
