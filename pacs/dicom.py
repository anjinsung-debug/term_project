"""DICOM 흉부 X-ray 읽기 (담당: 안진성).

원본 .dcm 파일은 받은 그대로 저장하고, 화면·품질 점검·영상처리에는 이 모듈이 만든 8비트 흑백 영상을 쓴다.
그래서 viewer.to_gray()만 거치면 나머지 코드(quality, algorithms, roi, processing)는 PNG와 똑같이 동작한다.

8비트로 바꾸는 순서:
1. 모달리티 변환 (RescaleSlope/Intercept)
2. 밝기 분포의 하위·상위 일부를 잘라 0~255로 펼친다 (config.DICOM_WINDOW_PERCENTILES).
   파일에 들어 있는 WindowCenter/Width는 쓰지 않는다. LIDC-IDRI 흉부 X-ray에는 CT 폐 설정 같은 값(-600/1600)이
   들어 있어, 그대로 적용하면 영상 전체가 하얗게 날아갔다 (2026-11-17 확인).
3. MONOCHROME1(밝을수록 값이 작음)이면 반전해 MONOCHROME2처럼 보이게 한다.

개인정보: 태그는 모달리티·크기·픽셀 간격만 읽는다. 환자 이름 등은 저장하거나 화면에 보여주지 않는다.
"""
import io

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut

from pacs import config


def is_dicom(data):
    """DICOM 파일 표시(128바이트 뒤의 "DICM")가 있는지 본다."""
    return len(data) > 132 and data[128:132] == b"DICM"


def read(data):
    """DICOM 바이트를 (흑백 uint8 영상, 정보)로 돌려준다. 문제가 있으면 이유를 담은 ValueError.

    정보: {"modality", "width", "height", "pixel_spacing"}. pixel_spacing은 [행 간격, 열 간격] mm 또는 None.
    """
    try:
        ds = pydicom.dcmread(io.BytesIO(data))
    except (InvalidDicomError, EOFError, OSError, ValueError) as e:
        raise ValueError("DICOM 파일을 읽을 수 없습니다. 파일이 손상되었을 수 있습니다.") from e

    modality = str(getattr(ds, "Modality", "") or "")
    if modality not in config.DICOM_MODALITIES:
        allowed = ", ".join(config.DICOM_MODALITIES)
        raise ValueError(f"흉부 X-ray DICOM({allowed})만 올릴 수 있습니다 (이 파일: {modality or '알 수 없음'}).")
    if "PixelData" not in ds:
        raise ValueError("영상 데이터가 없는 DICOM 파일입니다.")
    if int(getattr(ds, "SamplesPerPixel", 1)) != 1 or int(getattr(ds, "NumberOfFrames", 1) or 1) != 1:
        raise ValueError("흑백 단일 영상 DICOM만 올릴 수 있습니다.")
    try:
        pixels = apply_modality_lut(ds.pixel_array, ds).astype(np.float32)
    except Exception as e:  # 압축 형식을 풀 라이브러리가 없거나 데이터가 깨진 경우
        raise ValueError(
            "DICOM 영상 데이터를 풀 수 없습니다. 압축되지 않은 DICOM을 올려 주세요 "
            f"(이 파일: {ds.file_meta.get('TransferSyntaxUID', '알 수 없음')})."
        ) from e

    lo, hi = np.percentile(pixels, config.DICOM_WINDOW_PERCENTILES)
    if hi <= lo:
        raise ValueError("영상 밝기 값이 한 가지뿐이라 표시할 수 없습니다.")
    image = (np.clip((pixels - lo) / (hi - lo), 0, 1) * 255).round().astype(np.uint8)
    if ds.get("PhotometricInterpretation") == "MONOCHROME1":
        image = 255 - image

    spacing = ds.get("PixelSpacing") or ds.get("ImagerPixelSpacing")
    info = {
        "modality": modality,
        "width": int(ds.Columns),
        "height": int(ds.Rows),
        "pixel_spacing": [float(v) for v in spacing] if spacing else None,
    }
    return image, info
