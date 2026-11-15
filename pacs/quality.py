"""품질 자동 점검 (노션 설계 문서 6-1, 담당: 안진성).

measure로 지표 4개를 계산하고, check로 기준값(config.QUALITY_THRESHOLDS)과 비교해
통과 / 점검 필요를 판정한다. 기준값을 정한 근거는 config.py의 주석에 있다.
"""
import cv2
import numpy as np

from pacs import config

MEASURE_SIZE = 512  # 지표는 크기를 통일한 뒤 계산한다. 크기가 다르면 선명도·잡음 값이 달라지기 때문이다.


def measure(image):
    """흑백 uint8 영상의 품질 지표 4개를 돌려준다.

    - brightness: 픽셀 평균 (0~255). 낮으면 어둡다
    - contrast: 픽셀 표준편차. 낮으면 뿌옇고 구분이 안 된다
    - noise: 영상에서 3×3 Median 필터 결과를 뺀 나머지의 표준편차. 지글거리는 잡음이 많으면 커진다
    - sharpness: Laplacian(경계 강조)의 분산. 흐리면 작아진다
    """
    if image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("흑백 uint8 영상만 측정할 수 있습니다.")
    img = cv2.resize(image, (MEASURE_SIZE, MEASURE_SIZE), interpolation=cv2.INTER_AREA)
    residual = img.astype(np.float32) - cv2.medianBlur(img, 3).astype(np.float32)
    return {
        "brightness": float(img.mean()),
        "contrast": float(img.std()),
        "noise": float(residual.std()),
        "sharpness": float(cv2.Laplacian(img, cv2.CV_64F).var()),
    }


def check(image):
    """지표를 계산하고 판정한다. Firestore images.quality에 그대로 저장하는 형태로 돌려준다.

    {"brightness", "contrast", "noise", "sharpness", "passed", "reasons", "recommend"}
    - reasons: 미달 지표의 안내 문장 목록 (통과면 빈 목록)
    - recommend: 추천 보정 알고리즘 이름 목록 (중복 없이, 없으면 빈 목록)
    """
    metrics = measure(image)
    failed = []
    for name, (kind, limit) in config.QUALITY_THRESHOLDS.items():
        value = metrics[name]
        if (kind == "min" and value < limit) or (kind == "max" and value > limit):
            failed.append(name)
    recommend = []
    for name in failed:
        algo = config.QUALITY_RECOMMEND.get(name)
        if algo and algo not in recommend:
            recommend.append(algo)
    return {
        **{k: round(v, 2) for k, v in metrics.items()},
        "passed": not failed,
        "reasons": [config.QUALITY_REASONS[name] for name in failed],
        "recommend": recommend,
    }
