import cv2
import numpy as np
import pytest

from pacs import config, quality


def chest_like(seed=0):
    """흉부 X-ray처럼 밝기·대비·경계가 있는 512×512 시험 영상 (정상 품질)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:512, 0:512]
    img = np.full((512, 512), 170.0)
    for cx in (170, 340):  # 어두운 폐 두 개
        img[((xx - cx) ** 2 / 90**2 + (yy - 260) ** 2 / 170**2) < 1] = 60
    for y in range(80, 460, 40):  # 갈비뼈처럼 가는 밝은 선
        img[y:y + 6, 60:452] += 50
    img += rng.normal(0, 1.5, img.shape)  # 아주 약한 잡음
    return np.clip(img, 0, 255).astype(np.uint8)


def test_normal_image_passes():
    result = quality.check(chest_like())
    assert result["passed"], result
    assert result["reasons"] == [] and result["recommend"] == []


@pytest.mark.parametrize(
    "make, reason, recommend",
    [
        (lambda img: (img * 0.45).astype(np.uint8), "어둡습니다", "clahe"),
        (lambda img: (img.mean() + (img - img.mean()) * 0.2).astype(np.uint8), "대비가 낮습니다", "clahe"),
        (lambda img: np.clip(img + np.random.default_rng(1).normal(0, 20, img.shape), 0, 255).astype(np.uint8),
         "잡음이 많습니다", "median"),
        (lambda img: cv2.GaussianBlur(img, (15, 15), 4), "흐립니다", None),
    ],
)
def test_degraded_images_are_flagged_with_reason(make, reason, recommend):
    result = quality.check(make(chest_like()))
    assert not result["passed"]
    assert any(reason in r for r in result["reasons"]), result["reasons"]
    if recommend:
        assert recommend in result["recommend"]


def test_check_returns_fields_for_firestore():
    result = quality.check(chest_like())
    assert set(result) == {"brightness", "contrast", "noise", "sharpness", "passed", "reasons", "recommend"}


def test_recommend_has_no_duplicates():
    # 밝기와 대비가 함께 낮아도 CLAHE는 한 번만 추천한다
    dark_flat = np.full((512, 512), 30, np.uint8)
    dark_flat[200:300, 200:300] = 45
    result = quality.check(dark_flat)
    assert result["recommend"].count("clahe") == 1


def test_measure_rejects_color_or_non_uint8():
    with pytest.raises(ValueError):
        quality.measure(np.zeros((10, 10, 3), np.uint8))
    with pytest.raises(ValueError):
        quality.measure(np.zeros((10, 10), np.float32))


def test_thresholds_cover_all_metrics():
    assert set(config.QUALITY_THRESHOLDS) == set(config.QUALITY_REASONS) == {
        "brightness", "contrast", "noise", "sharpness"}
