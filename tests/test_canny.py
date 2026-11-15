import numpy as np
import pytest

from pacs import algorithms
from pacs.algorithms import canny


def step_image():
    """왼쪽 절반 60, 오른쪽 절반 180. x=128에 세로 경계가 하나 있다."""
    image = np.full((256, 256), 60, dtype=np.uint8)
    image[:, 128:] = 180
    return image


def noisy_image(seed=0):
    """밝기 120 근처에 잡음이 섞인 영상. 진짜 경계는 없다."""
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(120, 12, (256, 256)), 0, 255).astype(np.uint8)


def test_returns_new_binary_uint8_image_and_keeps_input():
    image = step_image()
    before = image.copy()
    edges = canny.apply(image)
    assert edges.shape == image.shape and edges.dtype == np.uint8
    assert edges is not image
    assert set(np.unique(edges)) <= {0, 255}
    assert np.array_equal(image, before)  # 원본을 바꾸지 않는다


def test_finds_the_boundary_and_nothing_in_flat_areas():
    edges = canny.apply(step_image())
    columns = np.flatnonzero(edges.any(axis=0))
    assert set(columns) <= {127, 128}  # 경계는 밝기가 바뀌는 자리에만 생긴다
    assert edges[:, 127:129].any(axis=1).all()  # 위에서 아래까지 끊기지 않는다


def test_flat_image_has_no_edges():
    assert not canny.apply(np.full((64, 64), 100, np.uint8)).any()


def test_higher_thresholds_keep_fewer_noise_edges():
    image = noisy_image()
    loose = canny.apply(image, low_threshold=20, high_threshold=60)
    strict = canny.apply(image, low_threshold=100, high_threshold=250)
    assert np.count_nonzero(strict) < np.count_nonzero(loose)


def test_defaults_come_from_params():
    image = noisy_image()
    defaults = {k: v["default"] for k, v in canny.PARAMS.items()}
    assert np.array_equal(canny.apply(image), canny.apply(image, **defaults))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"low_threshold": -5}, "낮은 임계값"),
        ({"high_threshold": 300}, "높은 임계값"),
        ({"low_threshold": 12.5}, "낮은 임계값"),
        ({"low_threshold": 150, "high_threshold": 150}, "작아야"),
        ({"low_threshold": 200, "high_threshold": 100}, "작아야"),
    ],
)
def test_rejects_invalid_thresholds(kwargs, message):
    with pytest.raises(ValueError, match=message):
        canny.apply(step_image(), **kwargs)


def test_rejects_color_or_float_image():
    with pytest.raises(ValueError, match="흑백"):
        canny.apply(np.zeros((10, 10, 3), np.uint8))
    with pytest.raises(ValueError, match="흑백"):
        canny.apply(np.zeros((10, 10), np.float32))


def test_edge_ratio():
    edges = np.zeros((10, 10), np.uint8)
    edges[0, :] = 255
    assert canny.edge_ratio(edges) == 0.1
    assert canny.edge_ratio(np.zeros((0, 0), np.uint8)) == 0.0


def test_params_follow_viewer_contract():
    for spec in canny.PARAMS.values():
        assert {"min", "max", "default", "step", "label"} <= set(spec)
        assert spec["min"] <= spec["default"] <= spec["max"]
    assert canny.PARAMS["low_threshold"]["default"] < canny.PARAMS["high_threshold"]["default"]


def test_has_version_for_processing_log():
    assert isinstance(canny.VERSION, str) and canny.VERSION


def test_shows_up_in_available_algorithms():
    assert algorithms.available()["canny"] is canny
