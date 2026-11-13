# 교육용 웹 PACS 프로토타입

긴급도와 영상 품질에 따라 검토 순서를 정하고, 두 검토자의 블라인드 이중 검토에서 ROI 불일치를 자동 감지해 중재까지 관리하는 교육용 웹 PACS입니다.

> 공개 영상과 모의 케이스만 사용합니다. 모든 수치는 교육용 결과이며 진단에 사용할 수 없습니다.

- 기술 스택: Python, Streamlit, Firebase Authentication, Cloud Firestore, JCloud
- 지원 영상: 흉부 X-ray (PNG, JPEG)

## 폴더 구조

파일마다 담당자를 한 명씩 정했습니다. 다른 사람이 담당하는 파일을 고쳐야 할 때는 먼저 담당자에게 알립니다. 아직 없는 파일은 담당자가 작업을 시작할 때 만듭니다.

### 기본 틀 (안진성)

| 경로 | 내용 |
|---|---|
| `app.py` | 시작점, 로그인 확인, 역할별 메뉴 |
| `pacs/config.py` | 팀이 합의한 값과 기준값. 바꿀 때는 팀에 알리고 PR로 반영 |
| `pacs/auth.py` | 로그인, 로그아웃, 역할 확인 |
| `pacs/cases.py` | 케이스와 영상의 등록·조회·검색 (권한 검사 포함) |
| `pacs/workflow.py` | 상태 전이 표와 전이 실행, 변경 기록 |
| `pacs/processing.py` | 알고리즘 실행과 처리 이력 저장 |
| `pacs/viewer.py` | 뷰어 (확대·이동·초기화, 원본과 결과 비교, ROI 선택) |
| `pages/register.py` | 케이스 등록 화면 |
| `pages/case_detail.py` | 케이스 상세 화면 |
| `firestore.rules` | Firestore 보안 규칙 |

### 품질 자동 점검 (안진성)

| 경로 | 내용 |
|---|---|
| `pacs/quality.py` | 품질 지표 계산과 판정 |
| `pacs/algorithms/clahe.py` | CLAHE |

### 블라인드 이중 검토와 ROI 불일치 감지 (고영민)

| 경로 | 내용 |
|---|---|
| `pacs/reviews.py` | 검토 결과 읽기·쓰기, 블라인드 규칙, 제출, 중재 확정 |
| `pacs/comparison.py` | 겹침 비율 계산과 일치·불일치 판정 |
| `pacs/roi.py` | ROI 유효성 검사, 평균·분산·히스토그램 |
| `pacs/algorithms/canny.py` | Canny |
| `pages/review.py` | 검토 화면 |
| `pages/arbitration.py` | 중재 화면 |

### 검토 우선순위 (이시은)

| 경로 | 내용 |
|---|---|
| `pacs/priority.py` | 기한 계산, 정렬, 기한 초과 판정 |
| `pacs/algorithms/median.py` | Median 필터 |
| `pages/worklist.py` | 작업 목록 화면 |

### 공통

| 경로 | 내용 |
|---|---|
| `tests/test_모듈이름.py` | pytest 자동화 테스트. 각 모듈의 담당자가 작성 |
| `.streamlit/secrets.toml.example` | 비밀 값 양식 |
| `.github/pull_request_template.md` | PR 양식 |
| `CLAUDE.md` | 프로젝트 규칙 |

### 서로 맞춰야 하는 부분

- 알고리즘 3종은 같은 형태로 만듭니다. 영상과 설정값을 받아 결과 영상을 돌려주는 형태여야 뷰어에서 같은 방식으로 부를 수 있습니다.
- 뷰어는 `pacs/viewer.py` 하나만 둡니다. 검토·중재·케이스 상세 화면은 이것을 불러 씁니다.
- 작업 목록 화면은 `pacs/cases.py`의 케이스 목록 조회 함수를 씁니다. 함수 형태는 안진성과 이시은이 먼저 맞춥니다.
- 품질 점검의 선명도 지표가 Canny를 쓸 경우 `pacs/algorithms/canny.py`를 불러 씁니다.

## 설치

Python 3.14에서 확인했습니다.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

macOS와 Linux에서는 두 번째 명령 대신 `source .venv/bin/activate`를 씁니다.

## 로컬 실행

```bash
streamlit run app.py
```

## 테스트

```bash
pytest
```

## Firebase 설정

작성 예정입니다. Firebase 프로젝트를 만든 뒤 채웁니다.

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사해 값을 넣습니다. `secrets.toml`과 서비스 계정 키 파일은 저장소에 올리지 않습니다.

## 시연 데이터 준비

작성 예정입니다.

## JCloud 배포와 복구

작성 예정입니다.

## 협업 규칙

- Issue를 먼저 만들고, 작업 브랜치에서 개발한 뒤 `main`으로 PR을 보냅니다.
- 작성자가 아닌 팀원 1명 이상이 리뷰한 뒤 병합합니다. `main`에 직접 커밋하지 않습니다.
- 커밋 메시지에는 무엇을 왜 바꿨는지 적습니다.
- AI나 외부 코드를 쓴 부분은 PR에 출처와 직접 수정·검증한 내용을 적습니다.

## 데이터 출처

- NIH ChestX-ray14, NIH Clinical Center 제공: https://nihcc.app.box.com/v/ChestXray-NIHCC
- Xiaosong Wang, Yifan Peng, Le Lu, Zhiyong Lu, Mohammadhadi Bagheri, Ronald Summers. "ChestX-ray8: Hospital-scale Chest X-ray Database and Benchmarks." IEEE CVPR, pp. 3462-3471, 2017.
- 품질 미달 영상은 위 원본에 밝기 저하, 잡음, 흐림을 넣어 직접 가공한 것입니다.
