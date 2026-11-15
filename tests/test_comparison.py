import numpy as np
import pytest

from pacs import config
from pacs.comparison import iou, judge, reference_info


def roi(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


# --- 겹침 비율 ---

def test_iou_of_same_roi_is_one():
    assert iou(roi(0, 0, 100, 100), roi(0, 0, 100, 100)) == 1.0


def test_iou_of_separate_rois_is_zero():
    assert iou(roi(0, 0, 50, 50), roi(100, 100, 50, 50)) == 0.0


def test_iou_of_rois_sharing_only_an_edge_is_zero():
    # x=0, w=50은 0~49번 픽셀, x=50은 50번부터라 겹치는 픽셀이 없다
    assert iou(roi(0, 0, 50, 50), roi(50, 0, 50, 50)) == 0.0


def test_iou_of_partial_overlap():
    # 겹친 부분 70×55 = 3850, 합친 넓이 4800 + 4800 - 3850 = 5750
    assert iou(roi(100, 120, 80, 60), roi(110, 125, 80, 60)) == pytest.approx(3850 / 5750)


def test_iou_when_one_roi_is_inside_the_other():
    assert iou(roi(0, 0, 100, 100), roi(0, 0, 50, 50)) == pytest.approx(0.25)


def test_iou_is_symmetric():
    a, b = roi(10, 20, 60, 40), roi(30, 10, 50, 70)
    assert iou(a, b) == iou(b, a)


# --- 판정 ---

def test_judge_match_when_iou_reaches_threshold():
    result = judge(roi(100, 120, 80, 60), roi(110, 125, 80, 60))  # IoU 약 0.67
    assert result == {"verdict": "match", "iou": 0.6696}


def test_judge_mismatch_when_iou_below_threshold():
    assert judge(roi(100, 120, 80, 60), roi(300, 200, 60, 60)) == {"verdict": "mismatch", "iou": 0.0}


def test_judge_iou_equal_to_threshold_is_match():
    # IoU가 정확히 0.25 → 기준 0.25면 일치 (이상이면 일치)
    assert judge(roi(0, 0, 100, 100), roi(0, 0, 50, 50), threshold=0.25)["verdict"] == "match"


def test_judge_uses_threshold_from_config(monkeypatch):
    a, b = roi(0, 0, 100, 100), roi(0, 0, 50, 50)  # IoU 0.25
    assert judge(a, b)["verdict"] == "mismatch"
    monkeypatch.setattr(config, "IOU_MATCH_THRESHOLD", 0.2)
    assert judge(a, b)["verdict"] == "match"


def test_judge_both_no_roi_is_match():
    assert judge(None, None) == {"verdict": "match", "iou": None}


def test_judge_one_no_roi_is_mismatch():
    assert judge(roi(0, 0, 20, 20), None) == {"verdict": "mismatch", "iou": None}
    assert judge(None, roi(0, 0, 20, 20)) == {"verdict": "mismatch", "iou": None}


# --- 중재 화면 참고 정보 ---

def two_area_image():
    """왼쪽 절반은 밝기 50, 오른쪽 절반은 200. 가운데(x=100)에 세로 경계가 하나 있다."""
    image = np.full((200, 200), 50, dtype=np.uint8)
    image[:, 100:] = 200
    return image


def test_reference_info_reports_stats_edges_and_difference():
    image = two_area_image()
    a, b = roi(10, 10, 40, 40), roi(80, 10, 40, 40)  # A는 어두운 평평한 곳, B는 경계를 가로지름
    info = reference_info(image, a, b)
    assert info["a"]["mean"] == 50.0 and info["a"]["edge_ratio"] == 0.0
    assert info["b"]["mean"] == pytest.approx(125.0) and info["b"]["edge_ratio"] > 0
    assert info["diff"]["mean"] == pytest.approx(75.0)
    assert info["diff"]["edge_ratio"] == info["b"]["edge_ratio"]


def test_reference_info_does_not_count_roi_border_as_edge():
    # 평평한 곳의 ROI는 경계 비율이 0이어야 한다 (ROI를 잘라낸 뒤 Canny를 적용하면 테두리가 잡힐 수 있음)
    info = reference_info(two_area_image(), roi(120, 50, 50, 50), None)
    assert info["a"]["edge_ratio"] == 0.0


def test_reference_info_with_missing_roi_has_no_difference():
    info = reference_info(two_area_image(), None, roi(10, 10, 20, 20))
    assert info["a"] is None and info["b"]["mean"] == 50.0
    assert info["diff"] is None
