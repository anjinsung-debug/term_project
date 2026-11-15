"""겹침 비율 계산과 일치·불일치 판정 (노션 설계 문서 6-2, 담당: 고영민).

판정 규칙 (CLAUDE.md, 2026-11-13 확정):
- 판정은 겹침 비율(IoU)만으로 한다. IoU가 config.IOU_MATCH_THRESHOLD 이상이면 일치.
- 둘 다 "ROI 없음"이면 일치, 한 명만 없으면 불일치.
- ROI 통계 차이와 Canny 경계 특징은 판정에 쓰지 않고 중재 화면의 참고 정보로만 쓴다 (reference_info).
"""
from pacs import config, roi as roi_mod
from pacs.algorithms import canny


def iou(roi_a, roi_b):
    """두 사각형 ROI의 겹침 비율 = 겹친 넓이 / 합친 넓이 (0.0~1.0).

    좌표는 픽셀 단위이고 w, h는 픽셀 개수다. x=0, w=10이면 0~9번 픽셀을 덮는다.
    """
    left = max(roi_a["x"], roi_b["x"])
    top = max(roi_a["y"], roi_b["y"])
    right = min(roi_a["x"] + roi_a["w"], roi_b["x"] + roi_b["w"])
    bottom = min(roi_a["y"] + roi_a["h"], roi_b["y"] + roi_b["h"])

    overlap = max(0, right - left) * max(0, bottom - top)
    union = roi_a["w"] * roi_a["h"] + roi_b["w"] * roi_b["h"] - overlap
    return overlap / union if union else 0.0


def judge(roi_a, roi_b, threshold=None):
    """두 검토자의 ROI를 비교해 {"verdict": "match" 또는 "mismatch", "iou": 값}을 돌려준다.

    ROI가 하나라도 없으면 겹침 비율을 계산할 수 없으므로 iou는 None이다.
    """
    threshold = config.IOU_MATCH_THRESHOLD if threshold is None else threshold
    if roi_a is None and roi_b is None:
        return {"verdict": "match", "iou": None}
    if roi_a is None or roi_b is None:
        return {"verdict": "mismatch", "iou": None}
    value = iou(roi_a, roi_b)
    return {"verdict": "match" if value >= threshold else "mismatch", "iou": round(value, 4)}


def reference_info(image, roi_a, roi_b):
    """중재 화면에 보여줄 참고 정보. 판정에는 쓰지 않는다.

    {"a": ROI A 정보 또는 None, "b": ROI B 정보 또는 None, "diff": 차이 또는 None}
    - 각 ROI 정보: roi.roi_stats 결과 + "edge_ratio"(Canny 기본 설정으로 구한 ROI 안 경계 비율)
    - diff: B - A의 평균·표준편차·경계 비율 차이. ROI가 둘 다 있을 때만 계산한다.
    Canny는 영상 전체에 한 번 적용한 뒤 ROI를 잘라낸다. 잘라낸 뒤 적용하면 ROI 테두리가 경계로 잡히기 때문이다.
    """
    edges = canny.apply(image)

    def info(r):
        if r is None:
            return None
        stats = roi_mod.roi_stats(image, r)
        stats["edge_ratio"] = canny.edge_ratio(roi_mod.crop(edges, r))
        return stats

    a, b = info(roi_a), info(roi_b)
    diff = None
    if a and b:
        diff = {k: round(b[k] - a[k], 4) for k in ("mean", "std", "edge_ratio")}
    return {"a": a, "b": b, "diff": diff}
