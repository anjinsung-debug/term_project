"""Median (담당: 이시은).

목적: 주변 픽셀의 중앙값으로 픽셀을 바꾸어 점 형태의 잡음을 줄인다.
품질 점검에서 잡음 미달이면 추천하되, 적용은 검토자가 선택한다.

원리:
- 각 픽셀 주변의 kernel_size × kernel_size 영역을 살펴본다.
- 영역 안 밝기 값을 정렬하여 가운데 값(중앙값)을 구한다.
- 중심 픽셀을 중앙값으로 바꾼다. 평균값을 사용하는 필터와 다르다.
- 영상 가장자리는 가장자리 픽셀을 반복하여 처리한다(OpenCV 기본 동작).

설정값:
- kernel_size: 주변 영역의 한 변 길이. 3, 5, 7, 9 중 선택한다.
  클수록 넓은 영역을 사용하지만, 작은 구조와 경계도 사라질 수 있다.

한계: 점 잡음에 유용하지만 모든 잡음에 효과적인 것은 아니다.
결과는 원본과 같은 크기의 흑백 uint8 영상이며, 교육용 처리 결과다.
"""
import cv2
import numpy as np

VERSION = "1"

PARAMS = {
    "kernel_size": {
        "label": "필터 크기 (kernel size)",
        "min": 3, "max": 9, "default": 3, "step": 2,
        "help": "주변 영역의 한 변 길이입니다. 클수록 작은 구조와 경계가 사라질 수 있습니다.",
    },
}


def apply(image, kernel_size=PARAMS["kernel_size"]["default"]):
    """흑백 uint8 영상에 Median 필터를 적용한 새 배열을 반환한다. 원본은 바꾸지 않는다."""
    if not isinstance(image, np.ndarray) or image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("Median 필터는 흑백 uint8 영상에만 적용할 수 있습니다.")
    if image.size == 0:
        raise ValueError("빈 영상에는 Median 필터를 적용할 수 없습니다.")

    spec = PARAMS["kernel_size"]
    if (
        isinstance(kernel_size, (bool, np.bool_))
        or not isinstance(kernel_size, (int, np.integer))
        or not spec["min"] <= kernel_size <= spec["max"]
        or kernel_size % 2 == 0
    ):
        raise ValueError(
            f"필터 크기는 {spec['min']}~{spec['max']} 사이의 홀수 정수여야 합니다 "
            f"(입력: {kernel_size})."
        )

    return cv2.medianBlur(image, int(kernel_size))





