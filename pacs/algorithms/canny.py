"""Canny 경계 검출 (담당: 고영민).

목적: 영상에서 밝기가 급하게 바뀌는 경계(뼈·장기 윤곽 등)를 선으로 뽑아, 구조물의 윤곽을 확인한다.
블라인드 이중 검토의 중재 화면에서는 두 검토자 ROI 안의 경계 비율을 참고 정보로 보여준다.

원리 (OpenCV cv2.Canny):
1. Sobel 필터로 픽셀마다 밝기 변화의 세기(기울기)와 방향을 구한다.
2. 경계 방향을 따라 가장 센 픽셀만 남겨 선을 1픽셀 두께로 만든다(비최대 억제).
3. 두 임계값으로 거른다(이력 임계값).
   - 기울기가 높은 임계값 이상이면 확실한 경계로 남긴다.
   - 낮은 임계값 미만이면 버린다.
   - 그 사이는 확실한 경계와 이어져 있을 때만 남긴다. 그래서 약한 경계도 끊기지 않고 이어진다.

설정값:
- low_threshold: 낮출수록 약한 경계까지 이어서 남긴다. 너무 낮으면 잡음도 경계로 잡힌다.
- high_threshold: 높일수록 확실한 경계만 시작점이 된다. 너무 높으면 흐린 경계가 사라진다.

한계: 잡음을 먼저 줄이지 않으므로 잡음이 많은 영상에서는 가짜 경계가 많이 생긴다.
결과는 경계 0/255의 흑백 영상이며, 진단 정보가 아니라 교육용 참고 결과다.
"""
import cv2
import numpy as np

VERSION = "1"

PARAMS = {
    "low_threshold": {
        "label": "낮은 임계값",
        "min": 0, "max": 255, "default": 50, "step": 5,
        "help": "낮출수록 약한 경계까지 이어서 남깁니다. 너무 낮으면 잡음도 경계로 잡힙니다.",
    },
    "high_threshold": {
        "label": "높은 임계값",
        "min": 0, "max": 255, "default": 150, "step": 5,
        "help": "이 값 이상인 확실한 경계에서 선을 시작합니다. 너무 높으면 흐린 경계가 사라집니다.",
    },
}


def _check_threshold(name, value):
    spec = PARAMS[name]
    if isinstance(value, bool) or int(value) != value or not spec["min"] <= value <= spec["max"]:
        raise ValueError(f"{spec['label']}은 {spec['min']}~{spec['max']} 사이의 정수여야 합니다 (입력: {value}).")
    return int(value)


def apply(
    image,
    low_threshold=PARAMS["low_threshold"]["default"],
    high_threshold=PARAMS["high_threshold"]["default"],
):
    """흑백 uint8 영상의 경계를 뽑은 새 영상을 돌려준다. 경계는 255, 나머지는 0이다. 입력 영상은 바꾸지 않는다."""
    if not isinstance(image, np.ndarray) or image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("Canny는 흑백 uint8 영상에만 적용할 수 있습니다.")
    low = _check_threshold("low_threshold", low_threshold)
    high = _check_threshold("high_threshold", high_threshold)
    if low >= high:
        raise ValueError(f"낮은 임계값({low})은 높은 임계값({high})보다 작아야 합니다.")
    return cv2.Canny(image, low, high)  # OpenCV는 새 배열을 돌려준다


def edge_ratio(edges):
    """경계 영상(apply의 결과)에서 경계 픽셀이 차지하는 비율 (0.0~1.0)."""
    if edges.size == 0:
        return 0.0
    return round(float(np.count_nonzero(edges)) / edges.size, 6)  # 흉부 X-ray는 경계가 0.1% 안팎이라 소수 6자리까지 남긴다
