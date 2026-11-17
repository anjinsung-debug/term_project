import io

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import ExplicitVRLittleEndian, JPEGBaseline8Bit, generate_uid

from pacs import cases, dicom, quality, viewer


def make_dicom(pixels=None, modality="DX", photometric="MONOCHROME2", spacing=(0.143, 0.143),
               syntax=ExplicitVRLittleEndian, slope=1, intercept=0):
    """시험용 DICOM 바이트. 기본은 512×512, 14비트 값이 들어 있는 흉부 X-ray(DX) 모양."""
    if pixels is None:
        yy, xx = np.mgrid[0:512, 0:512]
        pixels = (2000 + 10 * xx + 5 * yy).astype(np.uint16)  # 2000~9655 사이의 밝기 기울기
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"  # Digital X-Ray Image Storage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = syntax
    ds = FileDataset("test.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Modality = modality
    ds.PatientName = ""
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 14, 13, 0
    ds.RescaleSlope, ds.RescaleIntercept = slope, intercept
    ds.WindowCenter, ds.WindowWidth = -600, 1600  # LIDC-IDRI처럼 맞지 않는 window 값
    if spacing:
        ds.PixelSpacing = list(spacing)
    if syntax.is_compressed:  # 압축 형식은 조각으로 감싸야 저장된다. 내용은 풀 수 없는 가짜 JPEG
        ds.PixelData = encapsulate([b"\xff\xd8broken\xff\xd9"])
    else:
        ds.PixelData = pixels.tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def test_is_dicom():
    assert dicom.is_dicom(make_dicom())
    assert not dicom.is_dicom(b"\x89PNG" + b"\0" * 200)
    assert not dicom.is_dicom(b"")


def test_read_spreads_to_8bit_and_ignores_bad_window():
    image, info = dicom.read(make_dicom())
    assert image.dtype == np.uint8 and image.shape == (512, 512)
    # 파일의 window(-600/1600)를 쓰면 전부 255가 된다. 백분위로 펼쳐서 어두운 곳부터 밝은 곳까지 나온다.
    assert image.min() == 0 and image.max() == 255 and 100 < image.mean() < 155
    assert info == {"modality": "DX", "width": 512, "height": 512, "pixel_spacing": [0.143, 0.143]}


def test_monochrome1_is_inverted():
    normal, _ = dicom.read(make_dicom())
    inverted, _ = dicom.read(make_dicom(photometric="MONOCHROME1"))
    assert np.array_equal(inverted, 255 - normal)


def test_rescale_is_applied_before_windowing():
    a, _ = dicom.read(make_dicom())
    b, _ = dicom.read(make_dicom(slope=2, intercept=-1000))  # 선형 변환은 백분위 펼치기 뒤에 결과가 같아야 한다
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 1


def test_missing_spacing_is_none():
    assert dicom.read(make_dicom(spacing=None))[1]["pixel_spacing"] is None


@pytest.mark.parametrize("data, message", [
    (make_dicom(modality="CT"), "흉부 X-ray DICOM"),
    (make_dicom(pixels=np.full((300, 300), 500, np.uint16)), "한 가지뿐"),
    (b"\0" * 128 + b"DICM" + b"broken", "읽을 수 없습니다|흉부 X-ray DICOM"),  # 태그가 없어 모달리티도 없음
])
def test_read_rejects_with_reason(data, message):
    with pytest.raises(ValueError, match=message):
        dicom.read(data)


def test_compressed_dicom_without_decoder_is_explained():
    data = make_dicom(syntax=JPEGBaseline8Bit)  # 깨진 JPEG 압축 데이터 → 풀 수 없음
    with pytest.raises(ValueError, match="풀 수 없습니다|읽을 수 없습니다"):
        dicom.read(data)


def test_validate_image_and_to_gray_accept_dicom():
    data = make_dicom()
    info = cases.validate_image(data)
    assert (info["format"], info["width"], info["height"], info["modality"]) == ("dicom", 512, 512, "DX")
    gray = viewer.to_gray(data)
    assert gray.dtype == np.uint8 and gray.shape == (512, 512)
    assert set(quality.check(gray)) >= {"brightness", "passed"}  # 품질 점검도 PNG와 같은 경로로 동작


def test_validate_image_rejects_bad_dicom_as_case_error():
    with pytest.raises(cases.CaseError, match="흉부 X-ray DICOM"):
        cases.validate_image(make_dicom(modality="MR"))
    with pytest.raises(cases.CaseError, match="너무 작습니다"):
        yy, xx = np.mgrid[0:100, 0:100]
        cases.validate_image(make_dicom(pixels=(xx * 20 + yy).astype(np.uint16)))


def test_png_has_no_dicom_fields():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (300, 300), 128).save(buf, format="PNG")
    info = cases.validate_image(buf.getvalue())
    assert info["modality"] is None and info["pixel_spacing"] is None
