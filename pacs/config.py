"""팀이 합의한 값과 기준값을 한 곳에 모은다.

기준 문서는 노션 설계 문서 4-1(필드 이름), 6-1~6-3(기능별 상세)이다.
값을 바꿀 때는 노션을 먼저 고치고 변경 이력에 남긴다.
"""
from datetime import timedelta

# --- Firestore에 저장하는 정해진 값 (노션 4-1) ---
ROLES = ("registrar", "reviewer", "manager")
URGENCIES = ("emergency", "urgent", "routine")
STATUSES = (
    "received",
    "assigned",
    "in_review",
    "revision_requested",
    "arbitration",
    "done",
)
ALGORITHMS = ("clahe", "median", "canny")
VERDICTS = ("match", "mismatch")
EXAM_TYPES = ("chest_xray",)

# 화면에는 한글로 보여준다.
LABELS = {
    "registrar": "등록 담당자",
    "reviewer": "검토 담당자",
    "manager": "관리 담당자",
    "emergency": "응급",
    "urgent": "긴급",
    "routine": "일반",
    "received": "접수",
    "assigned": "배정됨",
    "in_review": "검토 중",
    "revision_requested": "보완 요청",
    "arbitration": "중재 중",
    "done": "완료",
    "clahe": "CLAHE",
    "median": "Median 필터",
    "canny": "Canny",
    "match": "일치",
    "mismatch": "불일치",
    "chest_xray": "흉부 X-ray",
}

# --- 업로드 (노션 1장) ---
SUPPORTED_FORMATS = ("png", "jpeg")

# --- 품질 자동 점검 (노션 6-1, 담당: 안진성) ---
# 정상 원본 20~30장의 지표 분포를 측정한 뒤 채운다. 임의의 숫자를 넣지 않는다.
QUALITY_THRESHOLDS = None

# --- ROI 불일치 판정 (노션 6-2, 담당: 고영민) ---
# 겹침 비율(IoU)이 이 값 이상이면 일치. 실제로 ROI를 그려 본 뒤 조정할 수 있다.
IOU_MATCH_THRESHOLD = 0.5

# --- 작업 목록 정렬 (노션 6-3, 담당: 이시은) ---
# 기한 = 접수 시각 + 긴급도별 목표 시간. 교육용 모의 값이다.
TARGET_TIME = {
    "urgent": timedelta(hours=1),
    "emergency": timedelta(hours=4),
    "routine": timedelta(hours=24),
}
