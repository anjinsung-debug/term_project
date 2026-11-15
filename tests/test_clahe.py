import numpy as np
import pytest

from pacs import algorithms
from pacs.algorithms import clahe


def low_contrast(seed=0):
    """밝기 100~130에 몰린 저대비 영상. 왼쪽과 오른쪽 밝기가 조금 다르다."""
    rng = np.random.default_rng(seed)
    img = np.full((256, 256), 110.0)
    img[:, 128:] = 120
    img[100:150, 60:200] += 8
    img += rng.normal(0, 2, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_returns_new_uint8_image_of_same_shape_and_keeps_input():
    img = low_contrast()
    before = img.copy()
    out = clahe.apply(img)
    assert out.shape == img.shape and out.dtype == np.uint8
    assert out is not img
    assert np.array_equal(img, before)  # 원본을 바꾸지 않는다


def test_increases_contrast_of_low_contrast_image():
    img = low_contrast()
    # 기본 설정(clip 2.0)에서 표준편차가 약 1.5배가 된다 (5.9 → 9.0)
    assert clahe.apply(img).std() > img.std() * 1.3


def test_larger_clip_limit_gives_stronger_contrast():
    img = low_contrast()
    weak, strong = clahe.apply(img, clip_limit=1.0), clahe.apply(img, clip_limit=8.0)
    assert strong.std() > weak.std()


def test_defaults_come_from_params():
    img = low_contrast()
    defaults = {k: v["default"] for k, v in clahe.PARAMS.items()}
    assert np.array_equal(clahe.apply(img), clahe.apply(img, **defaults))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"clip_limit": 0.5}, "대비 제한"),
        ({"clip_limit": 11}, "대비 제한"),
        ({"tile_grid_size": 1}, "격자 크기"),
        ({"tile_grid_size": 4.5}, "격자 크기"),
    ],
)
def test_rejects_out_of_range_params(kwargs, message):
    with pytest.raises(ValueError, match=message):
        clahe.apply(low_contrast(), **kwargs)


def test_rejects_color_or_float_image():
    with pytest.raises(ValueError, match="흑백"):
        clahe.apply(np.zeros((10, 10, 3), np.uint8))
    with pytest.raises(ValueError, match="흑백"):
        clahe.apply(np.zeros((10, 10), np.float32))


def test_params_follow_viewer_contract():
    for spec in clahe.PARAMS.values():
        assert {"min", "max", "default", "step", "label"} <= set(spec)
        assert spec["min"] <= spec["default"] <= spec["max"]


def test_shows_up_in_available_algorithms():
    assert algorithms.available()["clahe"] is clahe
