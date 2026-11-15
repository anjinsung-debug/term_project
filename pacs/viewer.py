"""영상 뷰어. 검토·중재·케이스 상세 화면이 이 모듈을 불러 쓴다.

- 확대·축소, 이동, 화면 초기화는 plotly 차트의 기본 도구를 쓴다 (오른쪽 위 도구 모음).
- ROI는 "Box Select"로 네모를 그려 고르고, 원본 픽셀 좌표 {"x", "y", "w", "h"}로 돌려준다.
- 밝기는 0~255로 고정해 그린다. plotly 기본값은 밝기를 자동으로 늘려 보여주기 때문에
  어두운 원본이 정상처럼 보여 원본과 처리 결과 비교가 왜곡된다.
"""
import io
import math

import numpy as np
import plotly.express as px
import streamlit as st
from PIL import Image, UnidentifiedImageError

# 도구 모음: 확대(zoom), 이동(pan), 확대·축소 버튼, 초기화(reset)만 남긴다.
_CHART_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "toImage", "autoScale2d"],
}
# 영상만 있는 차트에는 plotly가 선택 버튼을 넣지 않으므로 ROI를 고를 때는 직접 추가한다.
_SELECT_CONFIG = {**_CHART_CONFIG, "modeBarButtonsToAdd": ["select2d"]}


def to_gray(data):
    """파일 바이트를 흑백 2차원 uint8 배열로 바꾼다. 컬러 영상도 흑백으로 바꿔 다룬다.

    파일이 손상되어 풀 수 없으면 이유를 담은 ValueError를 낸다. 화면은 이것을 안내로 보여준다.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            return np.asarray(img.convert("L"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ValueError("영상 파일을 읽을 수 없습니다. 파일이 손상되었을 수 있습니다.") from e


def _layout(fig, height):
    fig.update_layout(
        dragmode="zoom",
        height=height,
        margin=dict(l=0, r=0, t=30, b=0),
        coloraxis_showscale=False,
    )
    fig.update_xaxes(showticklabels=False)
    fig.update_yaxes(showticklabels=False)
    return fig


def figure(image, rois=(), height=600):
    """영상 1장을 그린 plotly 그림. rois는 (roi, 이름, 색) 목록으로, 저장된 ROI를 겹쳐 그린다."""
    fig = px.imshow(image, binary_string=True, zmin=0, zmax=255)
    for roi, label, color in rois:
        if roi is None:
            continue
        fig.add_shape(
            type="rect",
            x0=roi["x"] - 0.5, y0=roi["y"] - 0.5,
            x1=roi["x"] + roi["w"] - 0.5, y1=roi["y"] + roi["h"] - 0.5,
            line=dict(color=color, width=2),
            label=dict(text=label, textposition="top left", font=dict(color=color)),
        )
    return _layout(fig, height)


def box_to_roi(box, width, height):
    """plotly 박스 선택 결과를 원본 픽셀 좌표 ROI로 바꾼다. 영상 밖은 잘라낸다. 넓이가 없으면 None."""
    xs, ys = box["x"], box["y"]
    # 픽셀 i는 화면에서 i-0.5 ~ i+0.5를 차지한다. 네모가 걸친 픽셀을 모두 포함한다.
    x0 = max(0, math.floor(min(xs) + 0.5))
    y0 = max(0, math.floor(min(ys) + 0.5))
    x1 = min(width, math.ceil(max(xs) + 0.5))
    y1 = min(height, math.ceil(max(ys) + 0.5))
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def show(image, key, rois=(), select_roi=False, height=600):
    """영상을 보여준다. select_roi=True이면 사용자가 고른 ROI를 돌려주고, 고르지 않았으면 None."""
    fig = figure(image, rois, height)
    if not select_roi:
        st.plotly_chart(fig, key=key, config=_CHART_CONFIG, use_container_width=True)
        return None
    st.caption(
        "영상 위를 끌어서 관심 영역(ROI)을 네모로 그려 주세요. 다시 그리면 바뀝니다. "
        "확대·이동은 오른쪽 위 도구 모음의 Zoom·Pan, 처음 화면으로는 Reset axes를 누르세요."
    )
    fig.update_layout(dragmode="select")  # 처음부터 네모 그리기 상태로 시작
    event = st.plotly_chart(
        fig, key=key, config=_SELECT_CONFIG, use_container_width=True,
        on_select="rerun", selection_mode="box",
    )
    boxes = (event.selection.get("box") or []) if event else []
    if not boxes:
        return None
    return box_to_roi(boxes[-1], image.shape[1], image.shape[0])


def compare(original, processed, key, height=500):
    """원본과 처리 결과를 나란히 보여준다. 확대·이동이 두 영상에 함께 적용된다."""
    if original.shape != processed.shape:
        raise ValueError("원본과 처리 결과의 크기가 다릅니다.")
    fig = px.imshow(
        np.stack([original, processed]), facet_col=0, binary_string=True, zmin=0, zmax=255,
    )
    for annotation, title in zip(fig.layout.annotations, ["원본", "처리 결과"]):
        annotation.text = title
    st.plotly_chart(_layout(fig, height), key=key, config=_CHART_CONFIG, use_container_width=True)


def param_controls(params, key):
    """알고리즘 모듈의 PARAMS로 슬라이더를 만들고, 고른 설정값을 돌려준다."""
    values = {}
    for name, spec in params.items():
        values[name] = st.slider(
            spec.get("label", name),
            min_value=spec["min"],
            max_value=spec["max"],
            value=spec["default"],
            step=spec["step"],
            key=f"{key}_{name}",
            help=spec.get("help"),
        )
    return values
