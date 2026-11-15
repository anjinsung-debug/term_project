"""CLAHE (Contrast Limited Adaptive Histogram Equalization, 담당: 안진성).

목적: 어둡거나 대비가 낮은 영상의 밝기 분포를 펼쳐 세부 구조가 보이게 한다.
품질 점검에서 밝기·대비 미달이면 이 알고리즘을 추천한다.

원리:
- 영상을 tile_grid_size × tile_grid_size 칸으로 나누고, 칸마다 히스토그램 평활화를 한다.
  영상 전체에 한 번에 하는 일반 평활화와 달리, 부분마다 그 부분의 밝기 분포에 맞춰 펼친다.
- 평활화 전에 히스토그램의 높이를 clip_limit로 자른다(Contrast Limited).
  자르지 않으면 고른 영역의 잡음까지 크게 키우기 때문이다.
- 칸 경계가 보이지 않게 이웃 칸의 결과를 이어 붙인다(쌍선형 보간). OpenCV가 처리한다.

설정값:
- clip_limit: 클수록 대비를 더 강하게 키운다. 너무 크면 잡음도 함께 커진다.
- tile_grid_size: 칸 수. 클수록 더 작은 부분마다 따로 펼친다(국소 대비가 커진다).
"""
import cv2
import numpy as np

VERSION = "1"

PARAMS = {
    "clip_limit": {
        "label": "대비 제한 (clip limit)",
        "min": 1.0, "max": 10.0, "default": 2.0, "step": 0.5,
        "help": "클수록 대비를 강하게 키웁니다. 너무 크면 잡음도 함께 커집니다.",
    },
    "tile_grid_size": {
        "label": "격자 크기 (tile grid size)",
        "min": 2, "max": 16, "default": 8, "step": 1,
        "help": "영상을 가로·세로 몇 칸으로 나눠 따로 펼칠지 정합니다. 클수록 더 작은 부분마다 펼칩니다.",
    },
}


def apply(image, clip_limit=PARAMS["clip_limit"]["default"], tile_grid_size=PARAMS["tile_grid_size"]["default"]):
    """흑백 uint8 영상에 CLAHE를 적용한 새 영상을 돌려준다. 입력 영상은 바꾸지 않는다."""
    if not isinstance(image, np.ndarray) or image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("CLAHE는 흑백 uint8 영상에만 적용할 수 있습니다.")
    spec = PARAMS["clip_limit"]
    if not spec["min"] <= clip_limit <= spec["max"]:
        raise ValueError(f"대비 제한은 {spec['min']}~{spec['max']} 사이여야 합니다 (입력: {clip_limit}).")
    spec = PARAMS["tile_grid_size"]
    if int(tile_grid_size) != tile_grid_size or not spec["min"] <= tile_grid_size <= spec["max"]:
        raise ValueError(f"격자 크기는 {spec['min']}~{spec['max']} 사이의 정수여야 합니다 (입력: {tile_grid_size}).")
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=(int(tile_grid_size), int(tile_grid_size)))
    return clahe.apply(image)  # OpenCV는 새 배열을 돌려준다
