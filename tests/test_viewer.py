import base64
import io
import sys
import types

import numpy as np
import pytest
from PIL import Image

from pacs import algorithms, viewer


def decode(fig, trace=0):
    """plotly 그림에 들어간 영상을 다시 배열로 꺼낸다."""
    src = fig.data[trace].source
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("L"))


def test_figure_keeps_original_brightness():
    # 밝기 100~109의 어두운 저대비 영상. 자동으로 밝기를 늘리면 0~255로 바뀌어 버린다.
    img = np.tile(np.arange(100, 110, dtype=np.uint8), (300, 30))
    assert np.array_equal(decode(viewer.figure(img)), img)


def test_figure_draws_saved_rois():
    img = np.zeros((300, 300), dtype=np.uint8)
    fig = viewer.figure(img, rois=[({"x": 10, "y": 20, "w": 30, "h": 40}, "A", "red"), (None, "B", "blue")])
    [shape] = fig.layout.shapes
    assert (shape.x0, shape.y0, shape.x1, shape.y1) == (9.5, 19.5, 39.5, 59.5)


@pytest.mark.parametrize(
    "box, expected",
    [
        ({"x": [9.7, 40.2], "y": [19.6, 60.1]}, {"x": 10, "y": 20, "w": 31, "h": 41}),
        ({"x": [40.2, 9.7], "y": [60.1, 19.6]}, {"x": 10, "y": 20, "w": 31, "h": 41}),  # 거꾸로 그려도 같다
        ({"x": [-50, 20], "y": [-5, 300]}, {"x": 0, "y": 0, "w": 21, "h": 200}),  # 영상 밖은 잘라낸다
        ({"x": [500, 600], "y": [10, 20]}, None),  # 완전히 영상 밖
    ],
)
def test_box_to_roi(box, expected):
    assert viewer.box_to_roi(box, width=300, height=200) == expected


def test_to_gray_converts_color_to_2d_uint8():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(buf, format="PNG")
    gray = viewer.to_gray(buf.getvalue())
    assert gray.shape == (30, 40) and gray.dtype == np.uint8


def test_compare_rejects_different_sizes():
    with pytest.raises(ValueError, match="크기"):
        viewer.compare(np.zeros((10, 10), np.uint8), np.zeros((10, 12), np.uint8), key="k")


def test_available_algorithms_skips_missing_modules(monkeypatch):
    fake = types.ModuleType("pacs.algorithms.median")
    fake.PARAMS, fake.apply = {}, lambda image: image
    monkeypatch.setitem(sys.modules, "pacs.algorithms.median", fake)
    monkeypatch.delitem(sys.modules, "pacs.algorithms.canny", raising=False)
    found = algorithms.available()
    assert found["median"] is fake
    assert "canny" not in found or found["canny"].__name__ == "pacs.algorithms.canny"
