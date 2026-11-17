"""시연용 흉부 X-ray DICOM을 TCIA의 LIDC-IDRI 컬렉션에서 받는다 (담당: 안진성).

LIDC-IDRI는 CC BY 3.0 공개 자료라 계정 없이 받을 수 있다. 흉부 X-ray는 DX 237명, CR 53명이다 (2026-11-17 확인).
환자 ID 순으로 정해진 수만큼 골라서, 누가 실행해도 같은 파일이 나온다.

    python scripts/fetch_dicom_samples.py            # DX 8명, CR 2명
    python scripts/fetch_dicom_samples.py --dx 5 --cr 0

결과는 data/samples_dicom/에 저장되고 저장소에는 올라가지 않는다 (data/는 .gitignore).
- 환자당 첫 번째 영상 1장만 쓴다.
- TCIA가 함께 주는 LICENSE와, 고른 파일 목록 manifest.csv를 남긴다.
"""
import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path

import requests

API = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
COLLECTION = "LIDC-IDRI"
OUT = Path(__file__).resolve().parent.parent / "data" / "samples_dicom"


def pick_series(modality, count):
    r = requests.get(f"{API}/getSeries", params={"Collection": COLLECTION, "Modality": modality}, timeout=60)
    r.raise_for_status()
    series = sorted(r.json(), key=lambda s: (s["PatientID"], s["SeriesInstanceUID"]))
    picked, seen = [], set()
    for s in series:
        if s["PatientID"] not in seen:  # 환자당 1개
            seen.add(s["PatientID"])
            picked.append(s)
        if len(picked) == count:
            break
    return picked


def download(series):
    r = requests.get(f"{API}/getImage", params={"SeriesInstanceUID": series["SeriesInstanceUID"]}, timeout=300)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".dcm"))
        license_text = z.read("LICENSE") if "LICENSE" in z.namelist() else None
        return z.read(names[0]), license_text


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dx", type=int, default=8, help="DX(디지털 X-ray) 환자 수")
    parser.add_argument("--cr", type=int, default=2, help="CR(컴퓨터 방사선) 환자 수")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for modality, count in (("DX", args.dx), ("CR", args.cr)):
        for s in pick_series(modality, count):
            name = f"{s['PatientID']}_{modality}.dcm"
            data, license_text = download(s)
            (OUT / name).write_bytes(data)
            if license_text and not (OUT / "LICENSE").exists():
                (OUT / "LICENSE").write_bytes(license_text)
            rows.append({"file": name, "patient_id": s["PatientID"], "modality": modality,
                         "series_uid": s["SeriesInstanceUID"], "size_bytes": len(data)})
            print(f"{name}  {len(data) / 1e6:.1f} MB")

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["file"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)}장을 {OUT}에 저장했습니다. 출처: LIDC-IDRI (TCIA), CC BY 3.0")


if __name__ == "__main__":
    sys.exit(main())
