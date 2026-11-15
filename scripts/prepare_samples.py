"""시연·실험용 흉부 X-ray를 NIH 샘플 묶음에서 고르고, 품질을 떨어뜨린 가공본을 만든다.

같은 샘플 묶음과 같은 난수 값이면 누가 실행해도 같은 영상이 나온다.

준비: Kaggle "Random Sample of NIH Chest X-ray Dataset"을 내려받아 압축을 푼다.
    https://www.kaggle.com/datasets/nih-chest-xrays/sample

사용법 (프로젝트 폴더에서):
    python scripts/prepare_samples.py 압축을_푼_폴더 [저장할_폴더]

    압축을 푼 폴더: sample_labels.csv와 sample/images/가 있는 폴더
    저장할 폴더: 기본값 data/samples (저장소에 올라가지 않는다)

고르는 기준 (README "시연 데이터 준비"):
    A. 기준 영상 20장: PA 촬영, 1024×1024 흑백. 성별 × 나이대(40세 미만, 40~59, 60 이상)를
       고르게 섞고 환자당 1장. 품질 기준값을 정하는 "정상 품질" 분포에 쓴다.
    B. 촬영 조건이 다른 영상 5장: AP 촬영 후보 중 대비(표준편차)가 가장 낮은 5장. 환자당 1장.
    C. 가공본 8장: A에서 2장씩 골라 어둡게·대비 낮게·잡음·흐림을 넣는다. 답을 아는 영상이다.
진단 결과(Finding Labels)는 고르는 데 쓰지 않는다. 이 시스템은 진단을 하지 않는다.
"""
import csv
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pacs import quality  # noqa: E402

SEED = 2026
N_BASE, N_AP = 20, 5
AP_CANDIDATES = 300  # B 묶음은 AP 후보 300장의 대비를 재서 고른다

# 가공 방법과 세기. 숫자는 품질 미달이 눈으로도 분명히 보이는 정도로 정했다.
DEGRADATIONS = {
    "dark": "밝기를 0.45배로",
    "lowcontrast": "평균을 중심으로 대비를 0.35배로",
    "noise": "표준편차 20의 가우시안 잡음",
    "blur": "커널 15, 시그마 4의 가우시안 흐림",
}


def degrade(img, kind, rng):
    f = img.astype(np.float32)
    if kind == "dark":
        out = f * 0.45
    elif kind == "lowcontrast":
        out = f.mean() + (f - f.mean()) * 0.35
    elif kind == "noise":
        out = f + rng.normal(0, 20, img.shape)
    elif kind == "blur":
        return cv2.GaussianBlur(img, (15, 15), 4)
    else:
        raise ValueError(kind)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def age_band(age):
    """"060Y" 같은 연 단위 나이만 나이대로 나눈다. 일·월 단위("001D", "006M")는 None으로 빼낸다."""
    if not age.endswith("Y") or not age[:-1].isdigit():
        return None
    years = int(age[:-1])
    return "<40" if years < 40 else "40-59" if years < 60 else "60+"


def read_gray(path):
    """1024×1024 흑백 영상만 돌려준다. 컬러·다른 크기는 None.

    cv2.imread는 Windows에서 한글이 든 경로를 읽지 못해, 바이트로 읽은 뒤 푼다.
    """
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    return img if img is not None and img.ndim == 2 and img.shape == (1024, 1024) else None


def write_png(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise OSError(f"PNG로 저장하지 못했습니다: {path}")
    buf.tofile(str(path))


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) == 3 else Path("data/samples")
    images = source / "sample" / "images"
    rows = list(csv.DictReader(open(source / "sample_labels.csv", encoding="utf-8")))
    rng = random.Random(SEED)
    rng.shuffle(rows)

    # A: PA, 성별 × 나이대 6칸을 돌아가며 한 장씩. 같은 환자는 한 번만.
    strata = {}
    for r in rows:
        if r["View Position"] == "PA" and age_band(r["Patient Age"]):
            strata.setdefault((r["Patient Gender"], age_band(r["Patient Age"])), []).append(r)
    base, patients = [], set()
    keys = sorted(strata)
    while len(base) < N_BASE and any(strata.values()):
        for key in keys:
            while strata[key] and len(base) < N_BASE:
                r = strata[key].pop()
                if r["Patient ID"] not in patients and read_gray(images / r["Image Index"]) is not None:
                    base.append(r)
                    patients.add(r["Patient ID"])
                    break

    # B: AP 후보 중 대비가 가장 낮은 5장
    candidates = []
    for r in rows:
        if r["View Position"] == "AP" and r["Patient ID"] not in patients:
            img = read_gray(images / r["Image Index"])
            if img is not None:
                candidates.append((quality.measure(img)["contrast"], r))
            if len(candidates) >= AP_CANDIDATES:
                break
    ap = []
    for _, r in sorted(candidates, key=lambda c: c[0]):
        if r["Patient ID"] not in patients:
            ap.append(r)
            patients.add(r["Patient ID"])
        if len(ap) == N_AP:
            break

    out.mkdir(parents=True, exist_ok=True)
    manifest = []

    def record(name, group, r, degradation=""):
        manifest.append({
            "file": name, "group": group, "source_image": r["Image Index"],
            "view": r["View Position"], "age": r["Patient Age"], "gender": r["Patient Gender"],
            "degradation": degradation,
        })

    for group, chosen in (("A", base), ("B", ap)):
        for r in chosen:
            shutil.copyfile(images / r["Image Index"], out / r["Image Index"])  # 원본 그대로 복사
            record(r["Image Index"], group, r)

    np_rng = np.random.default_rng(SEED)
    for i, kind in enumerate(DEGRADATIONS):
        for r in base[i * 2:i * 2 + 2]:
            name = r["Image Index"].replace(".png", f"__{kind}.png")
            write_png(out / name, degrade(read_gray(images / r["Image Index"]), kind, np_rng))
            record(name, "C", r, f"{kind}: {DEGRADATIONS[kind]}")

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
    counts = {g: sum(m["group"] == g for m in manifest) for g in "ABC"}
    print(f"{out}에 저장했습니다: A {counts['A']}장, B {counts['B']}장, C {counts['C']}장, manifest.csv")


if __name__ == "__main__":
    main()
