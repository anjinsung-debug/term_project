import numpy as np
import pytest

from pacs import config
from pacs.roi import RoiError, crop, roi_stats, validate_roi


def roi(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


# --- 유효성 검사 ---

def test_none_means_no_roi_and_is_allowed():
    assert validate_roi(None, 512, 512) is None


def test_valid_roi_is_returned_as_plain_ints():
    assert validate_roi(roi(np.int64(10), 10, 50, 50), 512, 512) == roi(10, 10, 50, 50)


def test_roi_touching_image_edge_is_allowed():
    assert validate_roi(roi(462, 462, 50, 50), 512, 512) == roi(462, 462, 50, 50)


def test_default_min_size_comes_from_config():
    small = config.ROI_MIN_SIZE - 1
    with pytest.raises(RoiError, match="너무 작습니다"):
        validate_roi(roi(0, 0, small, 50), 512, 512)
    assert validate_roi(roi(0, 0, config.ROI_MIN_SIZE, config.ROI_MIN_SIZE), 512, 512)


@pytest.mark.parametrize("bad", [roi(-1, 0, 50, 50), roi(463, 0, 50, 50), roi(0, 480, 50, 50)])
def test_roi_outside_image_is_rejected(bad):
    with pytest.raises(RoiError, match="범위"):
        validate_roi(bad, 512, 512)


@pytest.mark.parametrize("bad", [{"x": 0, "y": 0, "w": 50}, "0,0,50,50", {}])
def test_missing_or_wrong_shape_is_rejected(bad):
    with pytest.raises(RoiError, match="좌표"):
        validate_roi(bad, 512, 512)


@pytest.mark.parametrize("bad", [roi(0.5, 0, 50, 50), roi(0, 0, "50", 50), roi(True, 0, 50, 50)])
def test_non_integer_coordinates_are_rejected(bad):
    with pytest.raises(RoiError, match="정수"):
        validate_roi(bad, 512, 512)


# --- 잘라내기 ---

def test_crop_returns_copy_of_roi_area():
    image = np.arange(40 * 40, dtype=np.uint16).reshape(40, 40).astype(np.uint8)
    patch = crop(image, roi(2, 3, 12, 15))
    assert patch.shape == (15, 12)  # 세로 h, 가로 w
    assert patch[0, 0] == image[3, 2]  # 왼쪽 위가 (x=2, y=3)
    before = image.copy()
    patch[:] = 0
    assert np.array_equal(image, before)  # 원본은 바뀌지 않는다


def test_crop_rejects_no_roi():
    with pytest.raises(RoiError, match="없어"):
        crop(np.zeros((100, 100), np.uint8), None)


# --- 통계 ---

def test_stats_of_uniform_area():
    image = np.full((100, 100), 80, dtype=np.uint8)
    stats = roi_stats(image, roi(10, 10, 20, 20))
    assert stats["pixels"] == 400
    assert stats["mean"] == 80.0
    assert stats["variance"] == 0.0 and stats["std"] == 0.0
    assert len(stats["histogram"]) == 256
    assert stats["histogram"][80] == 400 and sum(stats["histogram"]) == 400


def test_stats_use_only_pixels_inside_roi():
    image = np.zeros((100, 100), dtype=np.uint8)
    image[:, 50:] = 200
    assert roi_stats(image, roi(60, 0, 20, 20))["mean"] == 200.0


def test_stats_of_half_dark_half_bright_area():
    # 절반은 0, 절반은 200 → 평균 100, 분산 100² = 10000, 표준편차 100
    image = np.zeros((100, 100), dtype=np.uint8)
    image[:, 50:] = 200
    stats = roi_stats(image, roi(40, 0, 20, 20))
    assert stats["mean"] == pytest.approx(100.0)
    assert stats["variance"] == pytest.approx(10000.0)
    assert stats["std"] == pytest.approx(100.0)
    assert stats["histogram"][0] == 200 and stats["histogram"][200] == 200


def test_stats_reject_color_or_float_image():
    with pytest.raises(RoiError, match="흑백"):
        roi_stats(np.zeros((100, 100, 3), np.uint8), roi(0, 0, 20, 20))
    with pytest.raises(RoiError, match="흑백"):
        roi_stats(np.zeros((100, 100), np.float32), roi(0, 0, 20, 20))


def test_stats_reject_invalid_roi():
    with pytest.raises(RoiError, match="범위"):
        roi_stats(np.zeros((100, 100), np.uint8), roi(90, 90, 20, 20))
