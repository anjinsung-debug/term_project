"""Canny 비교 실험과 불일치 자동 감지 효과 측정 (Issue #52, 담당: 고영민).

Firebase 없이 내 컴퓨터에서 돌아간다. 결과는 results/experiment_review/ 에 저장된다 (저장소에는 올리지 않는다).

    python scripts/experiment_review.py 흉부X-ray.png [다른영상.png ...]

1. Canny 비교: 영상마다 원본·어둡게·대비 낮게·잡음·흐림 5가지로 만들고(prepare_samples.py와 같은 가공),
   임계값 3쌍으로 Canny를 적용해 경계 비율을 표로, 결과 영상을 한 장의 비교 그림으로 저장한다.
2. 불일치 감지: 답을 아는 ROI 쌍(같은 병변을 조금 다르게 / 크게 어긋나게 / 한 명만 ROI 없음 등)을 섞어 만든 뒤
   comparison.judge로 판정해, 겹침 기준(0.3~0.6)별로 잡아낸 불일치·놓친 불일치·잘못 울린 경고를 센다.
3. 수동 대조 비교용 시트: 같은 ROI 쌍을 "메모 글"로만 적은 표를 만든다. 사람이 이 표만 보고 일치/불일치를 고르며
   시간을 재면, 자동 감지와 누락 건수·시간을 비교할 수 있다.
"""
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pacs import comparison  # noqa: E402
from pacs.algorithms import canny  # noqa: E402
from prepare_samples import DEGRADATIONS, degrade, write_png  # noqa: E402

SEED = 2026
OUT = Path("results/experiment_review")
THRESHOLD_PAIRS = [(25, 75), (50, 150), (100, 200)]  # 가운데가 기본값
VARIANTS = ["original"] + list(DEGRADATIONS)
VARIANT_LABELS = {"original": "원본", "dark": "어둡게", "lowcontrast": "대비 낮게", "noise": "잡음", "blur": "흐림"}
IOU_THRESHOLDS = [0.3, 0.4, 0.5, 0.6]
PAIRS_PER_KIND = 20

# 불일치 감지 실험의 ROI 쌍 종류. expected: 사람이 보기에 맞는 판정 (None은 경계 사례라 정답을 정하지 않음)
PAIR_KINDS = {
    "same_small": ("같은 병변, 거의 같게 (이동 5% 이하, 크기 ±5%)", "match"),
    "same_diff": ("같은 병변, 조금 다르게 (이동 10~15%, 크기 ±15%)", "match"),
    "borderline": ("경계 사례: 절반쯤 겹침 (이동 25~35%)", None),
    "shifted": ("크게 어긋남 (이동 50~80%)", "mismatch"),
    "elsewhere": ("다른 곳을 봄 (겹치지 않음)", "mismatch"),
    "one_none": ("한 명만 'ROI 없음'", "mismatch"),
    "both_none": ("둘 다 'ROI 없음'", "match"),
}


def read_gray(path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        sys.exit(f"영상을 읽지 못했습니다: {path}")
    return img


# --- 1. Canny 비교 ---

def canny_experiment(paths, rng):
    rows, tiles = [], []
    for path in paths:
        base = read_gray(path)
        for variant in VARIANTS:
            img = base if variant == "original" else degrade(base, variant, rng)
            row_tiles = [img]
            for low, high in THRESHOLD_PAIRS:
                edges = canny.apply(img, low_threshold=low, high_threshold=high)
                rows.append({
                    "image": Path(path).name, "variant": VARIANT_LABELS[variant],
                    "low": low, "high": high, "edge_ratio_pct": round(canny.edge_ratio(edges) * 100, 3),
                })
                row_tiles.append(edges)
            tiles.append(row_tiles)
    return rows, tiles


def save_grid(tiles, path, size=256):
    """행 = 영상 가공, 열 = 원본 영상 + 임계값별 Canny 결과."""
    pad = 4
    h = len(tiles) * (size + pad)
    w = len(tiles[0]) * (size + pad)
    grid = np.full((h, w), 255, np.uint8)
    for r, row in enumerate(tiles):
        for c, tile in enumerate(row):
            if c > 0:  # 경계선은 1픽셀이라 줄이면 사라진다. 보기용 그림에서만 두껍게 한다 (경계 비율 계산과는 무관)
                k = max(1, round(max(tile.shape) / size))
                tile = cv2.dilate(tile, np.ones((k, k), np.uint8))
            small = cv2.resize(tile, (size, size), interpolation=cv2.INTER_AREA)
            grid[r * (size + pad):r * (size + pad) + size, c * (size + pad):c * (size + pad) + size] = small
    write_png(path, grid)


# --- 2. 불일치 감지 ---

def make_pairs(width, height, rng):
    """답을 아는 ROI 쌍을 종류별로 만든다. 기준 ROI는 영상 안에서 병변 크기쯤(가로·세로의 15~25%)으로 고른다."""
    pairs = []

    def base_roi():
        w = int(width * rng.uniform(0.15, 0.25))
        h = int(height * rng.uniform(0.15, 0.25))
        x = int(rng.uniform(0.1, 0.9) * (width - w))
        y = int(rng.uniform(0.1, 0.9) * (height - h))
        return {"x": x, "y": y, "w": w, "h": h}

    def moved(r, shift_lo, shift_hi, scale):
        """r을 크기 대비 shift 비율만큼 무작위 방향으로 옮기고 크기를 scale배 안에서 바꾼다. 영상 밖으로 나가면 안으로 당긴다."""
        angle = rng.uniform(0, 2 * np.pi)
        dist = rng.uniform(shift_lo, shift_hi)
        w = max(10, int(r["w"] * rng.uniform(1 - scale, 1 + scale)))
        h = max(10, int(r["h"] * rng.uniform(1 - scale, 1 + scale)))
        x = int(r["x"] + np.cos(angle) * dist * r["w"])
        y = int(r["y"] + np.sin(angle) * dist * r["h"])
        x = min(max(0, x), width - w)
        y = min(max(0, y), height - h)
        return {"x": x, "y": y, "w": w, "h": h}

    for kind in PAIR_KINDS:
        for _ in range(PAIRS_PER_KIND):
            a = base_roi()
            if kind == "same_small":
                b = moved(a, 0, 0.05, 0.05)
            elif kind == "same_diff":
                b = moved(a, 0.10, 0.15, 0.15)
            elif kind == "borderline":
                b = moved(a, 0.25, 0.35, 0.10)
            elif kind == "shifted":
                b = moved(a, 0.50, 0.80, 0.10)
            elif kind == "elsewhere":
                while True:
                    b = base_roi()
                    if comparison.iou(a, b) == 0:
                        break
            elif kind == "one_none":
                a, b = (a, None) if rng.random() < 0.5 else (None, a)
            else:
                a = b = None
            pairs.append({"kind": kind, "roi_a": a, "roi_b": b})
    order = rng.permutation(len(pairs))  # 종류를 섞어서 순서로 답을 알 수 없게 한다
    return [pairs[i] for i in order]


def detection_experiment(pairs):
    per_pair, summary = [], []
    for i, p in enumerate(pairs, 1):
        iou = comparison.judge(p["roi_a"], p["roi_b"])["iou"]
        per_pair.append({"no": i, "kind": PAIR_KINDS[p["kind"]][0], "expected": PAIR_KINDS[p["kind"]][1] or "-",
                         "iou": "-" if iou is None else iou})
    for t in IOU_THRESHOLDS:
        tp = fn = fp = tn = 0
        border = {"match": 0, "mismatch": 0}
        for p in pairs:
            verdict = comparison.judge(p["roi_a"], p["roi_b"], threshold=t)["verdict"]
            expected = PAIR_KINDS[p["kind"]][1]
            if expected is None:
                border[verdict] += 1
            elif expected == "mismatch":
                tp += verdict == "mismatch"
                fn += verdict == "match"
            else:
                fp += verdict == "mismatch"
                tn += verdict == "match"
        summary.append({
            "threshold": t,
            "mismatch_total": tp + fn, "caught": tp, "missed": fn,
            "match_total": fp + tn, "false_alarm": fp,
            "detection_rate_pct": round(100 * tp / (tp + fn), 1),
            "false_alarm_rate_pct": round(100 * fp / (fp + tn), 1),
            "borderline_to_arbitration": f"{border['mismatch']}/{sum(border.values())}",
        })
    return per_pair, summary


def iou_ranges(pairs):
    rows = []
    for kind, (label, expected) in PAIR_KINDS.items():
        vals = [comparison.iou(p["roi_a"], p["roi_b"]) for p in pairs
                if p["kind"] == kind and p["roi_a"] and p["roi_b"]]
        rows.append({"kind": label, "expected": expected or "-",
                     "iou_min": round(min(vals), 3) if vals else "-",
                     "iou_mean": round(float(np.mean(vals)), 3) if vals else "-",
                     "iou_max": round(max(vals), 3) if vals else "-"})
    return rows


# --- 3. 수동 대조 시트 ---

def roi_memo(r):
    if r is None:
        return "이상 소견 없음"
    return f"x {r['x']}~{r['x'] + r['w']}, y {r['y']}~{r['y'] + r['h']} 부위 음영"


def manual_sheet(pairs, n=20):
    """사람이 메모만 보고 판단할 시트. 정답 열은 따로 저장해 채점에만 쓴다."""
    sheet, answers = [], []
    for i, p in enumerate(pairs[:n], 1):
        sheet.append({"no": i, "검토자A 메모": roi_memo(p["roi_a"]), "검토자B 메모": roi_memo(p["roi_b"]),
                      "내 판단(일치/불일치)": "", "걸린 시간(초)": ""})
        auto = comparison.judge(p["roi_a"], p["roi_b"])
        answers.append({"no": i, "자동 판정": "일치" if auto["verdict"] == "match" else "불일치",
                        "IoU": "-" if auto["iou"] is None else auto["iou"]})
    return sheet, answers


# --- 저장 ---

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글이 깨지지 않게 BOM
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def md_table(rows):
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    paths = sys.argv[1:]
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    canny_rows, tiles = canny_experiment(paths, rng)
    write_csv(OUT / "1_canny_edge_ratio.csv", canny_rows)
    save_grid(tiles, OUT / "1_canny_grid.png")

    h, w = read_gray(paths[0]).shape
    pairs = make_pairs(w, h, rng)
    per_pair, summary = detection_experiment(pairs)
    ranges = iou_ranges(pairs)
    write_csv(OUT / "2_pairs.csv", per_pair)
    write_csv(OUT / "2_detection_by_threshold.csv", summary)
    write_csv(OUT / "2_iou_by_kind.csv", ranges)

    sheet, answers = manual_sheet(pairs)
    write_csv(OUT / "3_manual_sheet.csv", sheet)
    write_csv(OUT / "3_manual_answers.csv", answers)

    report = [
        "# 실험 결과 (scripts/experiment_review.py, seed 2026)",
        "", "## 1. Canny 경계 비율(%) — 행: 영상 가공, 열: (낮은, 높은) 임계값", "",
        md_table(pivot(canny_rows)),
        "", "비교 그림: 1_canny_grid.png (행 = 원본·어둡게·대비 낮게·잡음·흐림, 열 = 영상 · 25/75 · 50/150 · 100/200)",
        "", f"## 2. 불일치 감지 — ROI 쌍 {len(pairs)}개 (종류별 {PAIRS_PER_KIND}개, 섞어서 판정)", "",
        "### 종류별 IoU 범위", "", md_table(ranges),
        "", "### 겹침 기준별 결과", "", md_table(summary),
        "", "## 3. 수동 대조", "",
        "3_manual_sheet.csv를 열어 메모만 보고 20쌍의 일치/불일치를 고르고 시간을 잰 뒤, 3_manual_answers.csv(자동 판정)와 비교한다.",
    ]
    (OUT / "results.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\n저장한 곳: {OUT.resolve()}")


def pivot(canny_rows):
    """긴 표를 (영상·가공) × 임계값 표로 바꾼다."""
    table = {}
    for r in canny_rows:
        key = (r["image"], r["variant"])
        table.setdefault(key, {"영상": r["image"], "가공": r["variant"]})[f"{r['low']}/{r['high']}"] = r["edge_ratio_pct"]
    return list(table.values())


if __name__ == "__main__":
    main()
