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
| `pacs/firebase_app.py` | Firebase 연결 (Firestore 클라이언트, 웹 API 키) |
| `pacs/auth.py` | 로그인, 로그아웃, 역할 확인, 권한 검사(`require_role`) |
| `scripts/create_user.py` | 테스트 계정 만들기와 역할 지정 |
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

- 알고리즘 3종은 같은 형태로 만듭니다. 그래야 뷰어에서 같은 방식으로 부를 수 있습니다.
  - 함수: `apply(image, **params) -> image`
  - `image`는 흑백 2차원 `numpy.uint8` 배열입니다. 결과도 같은 형태입니다.
  - 받은 `image`를 고치지 않고 새 배열을 돌려줍니다. 원본을 보존하기 위해서입니다.
  - 설정값이 잘못되면 `ValueError`를 내고, 메시지에 이유를 한글로 적습니다. 화면에 그대로 안내합니다.
  - 모듈마다 `PARAMS`에 조절할 설정값의 범위를 적습니다. 뷰어가 이것을 보고 슬라이더를 만듭니다.
    예: `PARAMS = {"clip_limit": {"min": 1.0, "max": 10.0, "default": 2.0, "step": 0.5}}`
- ROI는 원본 영상의 픽셀 좌표로 주고받습니다. 형태는 `{"x": 정수, "y": 정수, "w": 정수, "h": 정수}`이고, `x`, `y`는 왼쪽 위 모서리입니다. "ROI 없음"은 `None`입니다.
- 뷰어는 `pacs/viewer.py` 하나만 둡니다. 검토·중재·케이스 상세 화면은 이것을 불러 씁니다. 뷰어는 사용자가 선택한 ROI를 위 형태로 돌려줍니다.
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

팀이 Firebase 프로젝트 `term-project-1c322` 하나를 함께 씁니다. 로그인은 Firebase Authentication(이메일/비밀번호), 데이터는 Cloud Firestore에 저장합니다.

각자 컴퓨터에서 한 번만 설정합니다.

1. 팀장에게 Firebase 프로젝트 초대를 받습니다. Google 계정 이메일을 알려주면 됩니다.
2. [Firebase 콘솔](https://console.firebase.google.com)에서 프로젝트를 열고, 톱니바퀴 → 프로젝트 설정 → 서비스 계정 → **새 비공개 키 생성**으로 키 파일(JSON)을 내려받습니다.
3. 키 파일을 **프로젝트 폴더 밖**에 둡니다. 예: `C:/keys/pacs-firebase.json`
4. `.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사합니다.
5. `secrets.toml`의 `service_account_file`에 키 파일의 경로를 적습니다. Windows에서도 경로 구분은 `/`로 씁니다.
6. 프로젝트 설정 → 일반 → 내 앱의 웹 앱에서 `apiKey` 값을 복사해 `web_api_key`에 넣습니다.

주의할 점입니다.

- `secrets.toml`과 키 파일은 저장소에 올리지 않습니다. `.gitignore`에 등록되어 있습니다.
- 키 파일과 키 값을 메신저 공개 채널이나 노션에 올리지 않습니다.
- 팀 전체가 같은 데이터베이스를 씁니다. 다른 사람이 만든 테스트 데이터를 지우지 않습니다.
- Firestore 보안 규칙은 모든 직접 접근을 막아 둡니다. 앱은 서버에서 서비스 계정으로 접속하고, 권한은 데이터를 읽고 쓰는 함수 안에서 검사합니다.

## 테스트 계정 만들기

로그인하려면 Firebase Authentication 계정과 Firestore `users/{uid}`의 역할이 모두 있어야 합니다. 역할이 없는 계정은 로그인할 수 없습니다.

```bash
python scripts/create_user.py registrar@pacs.test registrar 등록담당
```

- 역할은 `registrar`(등록), `reviewer`(검토), `manager`(관리) 중 하나입니다.
- 비밀번호는 실행 중에 입력합니다. 화면에 표시되지 않습니다.
- 이미 있는 계정에 다시 실행하면 비밀번호는 그대로 두고 역할만 바꿉니다.
- 계정 정보와 비밀번호는 저장소나 노션에 적지 않고 LMS 제출란에만 적습니다.

시연에는 등록 1개, 검토 2개(검토자 A, B), 관리 1개, 모두 4개가 필요합니다.

## 코드에서 권한 검사하기

권한 검사는 화면에서 버튼을 숨기는 것만으로 끝내지 않고, 데이터를 읽고 쓰는 함수 맨 앞에서 합니다.

```python
from pacs.auth import require_role

def assign_reviewers(user, case_id, reviewer_uids):
    require_role(user, "manager")  # 관리 담당자가 아니면 PermissionError
    ...
```

화면 파일은 맨 앞에서 `user = auth.require_login()`을 부릅니다. 로그인하지 않았으면 로그인 화면만 보여주고 멈춥니다.

## 영상 파일 저장

영상 파일(원본, 처리 결과)은 Firestore에 넣지 않고 폴더에 저장합니다. Firestore에는 파일의 위치만 적습니다. Firebase Storage는 유료 요금제가 필요해 쓰지 않습니다.

- 저장 폴더는 `secrets.toml`의 `data_dir`로 정합니다. 기본값은 프로젝트 폴더 안의 `data`이고, 저장소에는 올라가지 않습니다.
- 배포 서버(JCloud)에서는 서버를 다시 시작해도 지워지지 않는 폴더를 지정합니다.
- 개발 중에는 각자 컴퓨터에 파일이 따로 저장됩니다. 다른 사람이 등록한 케이스는 기록만 있고 영상 파일이 없을 수 있습니다. 이 경우 화면에 오류 대신 안내 문구를 보여줍니다.

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
