# 교육용 웹 PACS 프로토타입

영상의 품질을 자동 점검한 후 계산된 기한 순으로 작업 목록을 표시하며 두 검토자의 ROI가 불일치하면 관리자가 중재하는 교육용 웹 PACS입니다.

> 공개 영상과 모의 케이스만 사용합니다. 모든 수치는 교육용 결과이며 진단에 사용할 수 없습니다.

- 기술 스택: Python, Streamlit, Firebase Authentication, Cloud Firestore, JCloud
- 지원 영상: 흉부 X-ray (PNG, JPEG, DICOM DX·CR)

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
| `pacs/notes.py` | 케이스 메모와 리포트 (작성·고치기·고친 기록, 검토자 사이 블라인드) |
| `pacs/processing.py` | 알고리즘 실행과 처리 이력 저장 |
| `pacs/viewer.py` | 뷰어 (확대·이동·초기화, 원본과 결과 비교, ROI 선택) |
| `pacs/dicom.py` | DICOM 흉부 X-ray 읽기와 8비트 변환 |
| `pacs/algorithms/__init__.py` | 만들어진 알고리즘 모듈을 찾아 목록으로 돌려줌 (`algorithms.available()`) |
| `pages/register.py` | 케이스 등록 화면 |
| `pages/case_detail.py` | 케이스 상세 화면 |
| `firestore.rules` | Firestore 보안 규칙 |

### 품질 자동 점검 (안진성)

| 경로 | 내용 |
|---|---|
| `pacs/quality.py` | 품질 지표 계산과 판정 |
| `scripts/prepare_samples.py` | 시연·실험용 영상 고르기와 가공본 만들기 |
| `scripts/fetch_dicom_samples.py` | 시연용 DICOM 흉부 X-ray 받기 (LIDC-IDRI) |
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
  - 모듈마다 `VERSION = "1"`처럼 버전 문자열을 둡니다. 처리 이력(`processing_logs.algorithm_version`)에 저장해, 결과가 어느 버전으로 만들어졌는지 추적합니다. 알고리즘 동작을 바꾸면 숫자를 올립니다.
  - 예시는 `pacs/algorithms/clahe.py`를 참고하세요.
  - 모듈마다 `PARAMS`에 조절할 설정값의 범위를 적습니다. 뷰어가 이것을 보고 슬라이더를 만듭니다.
    예: `PARAMS = {"clip_limit": {"min": 1.0, "max": 10.0, "default": 2.0, "step": 0.5}}`
- ROI는 원본 영상의 픽셀 좌표로 주고받습니다. 형태는 `{"x": 정수, "y": 정수, "w": 정수, "h": 정수}`이고, `x`, `y`는 왼쪽 위 모서리입니다. "ROI 없음"은 `None`입니다.
- 뷰어는 `pacs/viewer.py` 하나만 둡니다. 검토·중재·케이스 상세 화면은 이것을 불러 씁니다.
  - `viewer.to_gray(파일바이트)`: 흑백 `numpy.uint8` 배열로 바꾸기 (컬러도 흑백으로, DICOM도 8비트로). 영상을 다루는 코드는 이 함수만 거치면 PNG와 DICOM을 구분할 필요가 없습니다
  - `viewer.show(image, key, select_roi=True)`: 영상을 보여주고 사용자가 그린 ROI를 위 형태로 돌려줌. 그리지 않았으면 `None`
  - `viewer.show(image, key, rois=[(roi, "검토자 A", "red"), (roi, "검토자 B", "blue")])`: 저장된 ROI를 겹쳐 그리기 (중재 화면용)
  - `viewer.compare(original, processed, key)`: 원본과 처리 결과를 나란히. 확대·이동이 두 영상에 함께 적용
  - `viewer.param_controls(module.PARAMS, key)`: `PARAMS`로 슬라이더를 만들고 고른 설정값을 돌려줌. `PARAMS` 항목에 `"label"`(한글 이름), `"help"`(설명)를 넣으면 화면에 보입니다
  - 영상은 밝기 0~255로 고정해 그립니다. 원본 밝기가 그대로 보여야 처리 결과와 비교할 수 있기 때문입니다.
- 알고리즘 모듈을 `pacs/algorithms/<이름>.py`로 만들면 `algorithms.available()`에 자동으로 들어오고, 케이스 상세 화면의 "처리 결과 비교"에 나타납니다.
- 처리 결과 저장은 `pacs/processing.py`를 씁니다.
  - `processing.run(알고리즘, image, params)`: 저장하지 않고 결과만 돌려줍니다 (미리 보기). 잘못된 설정은 `ProcessingError`.
  - `processing.save(user, case_id, 알고리즘, params, roi=None)`: 결과 파일(`results/{영상ID}/{처리이력ID}.png`)과 `processing_logs` 기록을 저장하고 `(처리이력ID, 새로 만들었는지)`를 돌려줍니다. 본인에게 배정된 "검토 중" 케이스에서 검토 담당자만 할 수 있습니다.
  - 같은 사람이 같은 설정·ROI로 다시 저장하면 기록을 새로 만들지 않고 기존 ID를 돌려줍니다. 검토 제출 때 `reviews.processing_log_ids`에 이 ID를 넣으면 됩니다.
  - `processing.list_logs(user, case_id)`, `processing.load_result(user, log_id)`: 검토 담당자는 본인 기록만 받습니다. 처리 이력에 ROI가 있어 블라인드 규칙을 지키기 위해서입니다.
  - `processing.features(original, result, roi)`: 전체 품질 지표 전후와 ROI 통계(평균·분산·히스토그램) 전후. 저장되는 `features`와 같은 형태입니다.
- 작업 목록 화면은 `pacs/cases.py`의 `list_cases(user, status=None, urgency=None, mock_id_query="")`를 씁니다. 역할에 맞는 케이스만 돌려주고(등록 담당: 본인 등록, 검토 담당: 본인 배정, 관리 담당: 전체), 각 항목은 Firestore 필드에 문서 ID `"id"`를 더한 딕셔너리입니다. 케이스 1건은 `get_case(user, case_id)`, 영상은 `load_image(user, image_id)`(파일 포함) 또는 `get_image(user, image_id)`(기록만)로 가져옵니다. 품질 "점검 필요" 표시는 각 항목의 `flags.quality_check`를 보면 됩니다.
- 케이스 상태는 `pacs/workflow.py`로만 바꿉니다. `cases` 문서의 `status`를 직접 고치지 않습니다.
  - `workflow.transition(user, case_id, 동작, reason=None, reviewer_uids=None)`: 전이 하나를 실행하고 새 상태를 돌려줍니다. 역할, 담당 범위, 현재 상태, 사유를 검사하고 `case_events` 기록과 `completed_at`을 함께 저장합니다.
  - 동작 이름은 `workflow.TRANSITIONS`에 있습니다 (`assign`, `start_review`, `auto_match`, `auto_mismatch`, `arbitrate`, `request_revision`, `revision_done`, `reopen`). 화면 이름은 `config.LABELS`입니다.
  - 두 검토 제출 후 자동 판정(`auto_match`, `auto_mismatch`)은 사용자 대신 `workflow.SYSTEM`을 넘깁니다.
  - 다른 기록과 한 번에 저장해야 하면(예: 중재 의견과 `arbitrate`) 직접 만든 Firestore 트랜잭션 안에서 `workflow.apply(transaction, user, case_id, 동작, ...)`를 부릅니다. 읽기를 모두 끝낸 뒤에 부릅니다.
  - 실패하면 `TransitionError`, `PermissionError`, `CaseError`를 냅니다. 메시지를 화면에 그대로 보여주면 됩니다.
  - 버튼을 고를 때는 `workflow.allowed_actions(user, case)`를 씁니다.
  - 케이스 상세 화면의 "업무 진행"에 배정·검토 시작·보완 요청·보완 완료·재검토 버튼이 있습니다. 중재 확정(`arbitrate`)은 의견과 함께 저장해야 해서 중재 화면에서 합니다.
  - `workflow.list_events(user, case_id)`: 상태 변경 기록(오래된 순). `workflow.reviewer_accounts(user)`: 배정할 검토 담당자 목록(관리 담당자만). `workflow.display_names(user, uids)`: UID를 화면 이름으로.
- 검토·판정·중재 기록은 `pacs/reviews.py`로만 읽고 씁니다. 블라인드 규칙을 이 모듈의 함수가 지키기 때문입니다.
  - `reviews.save_draft(user, case_id, roi, memo, processing_log_ids=None)`: 제출 전 저장. "검토 중"이고 본인에게 배정된 케이스에서 검토 담당만. 여러 번 저장해도 `reviews/{케이스ID_검토자UID}` 문서 하나를 덮어씁니다.
  - `reviews.submit(user, case_id, roi, memo, processing_log_ids=None)`: 제출. 두 번째 제출이면 겹침 비율로 판정해 `comparisons/{케이스ID}`를 저장하고 `auto_match`(완료) 또는 `auto_mismatch`(중재 중)를 같은 트랜잭션에서 실행합니다. `{"status", "verdict", "iou"}`를 돌려줍니다. 제출한 뒤에는 고칠 수 없습니다.
  - `processing_log_ids`에는 `processing.save`가 돌려준 ID 중 본인이 이 영상에 저장한 것만 넣을 수 있습니다.
  - `reviews.get_review(user, case_id, reviewer_uid)`, `reviews.list_reviews(user, case_id)`: 검토 담당은 두 사람 모두 제출하기 전에는 본인 검토만 받습니다(다른 사람 것은 `PermissionError`). 관리 담당은 언제든 받습니다.
  - `reviews.get_comparison(user, case_id)`: 판정·중재 기록. 두 검토가 모두 제출되기 전에는 `None`.
  - `reviews.arbitrate(user, case_id, choice, reason, custom_roi=None)`: 관리 담당이 최종 ROI(`"a"`, `"b"`, `"custom"`, `"none"`)와 사유를 저장하고 `arbitrate`(완료)를 같은 트랜잭션에서 실행합니다.
  - 실패하면 `ReviewError`, `TransitionError`, `PermissionError`, `CaseError`를 냅니다. 메시지를 화면에 그대로 보여주면 됩니다.
- 화면을 새로 만들면 `app.py`의 역할별 메뉴(`menu`)에 추가합니다. 화면 파일 맨 앞에서는 `auth.require_login()`을 부르고, 역할이 맞지 않으면 안내 후 멈춥니다.
- 시각은 UTC로 저장하고, 화면에는 `cases.format_kst(시각)`으로 한국 시간을 보여줍니다.
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
- 원본은 `originals/{케이스ID}/{영상ID}.png`, `.jpg`, `.dcm`에 올린 파일 그대로 저장합니다. 형식을 바꾸지 않습니다.
- 등록할 때는 파일을 먼저 저장하고, 모의 ID 표시·케이스·영상·상태 기록을 한 번에 저장합니다.
  - 기록 저장에서 오류가 나면 **실제로 저장됐는지 확인한 뒤** 저장되지 않았을 때만 파일을 지웁니다. 응답만 끊기고 저장은 된 경우 원본을 지우지 않기 위해서입니다. 확인조차 안 되면 파일을 남기고 목록에서 확인하라고 안내합니다.
  - 같은 모의 ID는 `mock_ids/{모의ID}` 문서를 `create`로 만들어 막습니다. 문서가 이미 있으면 저장 전체가 실패하므로, 두 사람이 동시에 등록해도 한 명만 성공합니다. 그래서 모의 ID는 문서 ID에 쓸 수 있게 영문·숫자로 시작하고 영문·숫자·`-`·`_`로 40자 이내여야 합니다.
  - 영상 파일은 등록할 때 끝까지 풀어 봅니다. 뒤가 잘린 JPEG처럼 손상된 파일은 등록 단계에서 거부합니다. 이미 저장된 파일이 손상돼 있으면 상세 화면은 오류 대신 안내를 보여줍니다.
- 처리 결과는 `results/{영상ID}/{처리이력ID}.png`에 PNG로 저장합니다. 원본은 고치지 않습니다.
  - 결과 파일을 먼저 저장하고 기록을 저장합니다. 파일 저장이 실패하면 `status: "failed"`로 기록을 남기고, 기록 저장이 실패하면 저장되지 않은 것을 확인한 뒤에만 결과 파일을 지웁니다.
- 받는 파일: PNG, JPEG, DICOM, 가로·세로 256픽셀 이상, 20MB 이하. 손상된 파일과 다른 형식은 이유와 함께 거부합니다.
- DICOM은 흉부 X-ray(Modality DX·CR), 흑백 단일 영상, 압축되지 않은 것만 받습니다. `images`에 `modality`와 `pixel_spacing`(mm, 없으면 비움)을 함께 저장합니다.
  - 화면·품질 점검·영상처리에는 `pacs/dicom.py`가 만든 8비트 영상을 씁니다. 순서: 모달리티 변환 → 밝기 분포의 0.5~99.5% 구간을 0~255로 펼치기 → MONOCHROME1이면 반전.
  - 파일의 WindowCenter/Width는 쓰지 않습니다. LIDC-IDRI 흉부 X-ray에는 CT 폐 설정 같은 값(-600/1600)이 들어 있어, 그대로 쓰면 영상이 하얗게 날아갔습니다.
  - 환자 이름 등 DICOM 태그는 저장하거나 화면에 보여주지 않습니다.
  - 비식별 공개 자료만 받습니다. 등록할 때 `PatientIdentityRemoved`가 `YES`가 아니거나 환자 이름·생년월일이 있으면 거부합니다 (`dicom.check_deidentified`). LIDC-IDRI는 모두 통과합니다.
  - `viewer.to_gray()`는 결과를 최근 8장까지 기억합니다(`st.cache_data`). 슬라이더를 움직여 화면이 다시 그려질 때 같은 파일을 다시 풀지 않습니다. 17MB CR 기준 0.3초 → 0.04초.
- 배포 서버(JCloud)에서는 서버를 다시 시작해도 지워지지 않는 폴더를 지정합니다.
- 개발 중에는 각자 컴퓨터에 파일이 따로 저장됩니다. 다른 사람이 등록한 케이스는 기록만 있고 영상 파일이 없을 수 있습니다. 이 경우 화면에 오류 대신 안내 문구를 보여줍니다.

## 시연 데이터 준비

시연과 알고리즘 실험에 사용할 흉부 X-ray 33장을 스크립트로 준비합니다. 같은 샘플 묶음을 사용하면 누구나 같은 파일을 얻을 수 있습니다.

1. Kaggle에 로그인한 뒤 [Random Sample of NIH Chest X-ray Dataset](https://www.kaggle.com/datasets/nih-chest-xrays/sample)을 내려받아 압축을 풉니다. 다운로드 용량은 약 2GB입니다.
2. 압축을 푼 폴더 안에 `sample_labels.csv`와 `sample/images/`가 있는지 확인합니다.
3. 프로젝트 폴더에서 아래 명령을 실행합니다. `압축을_푼_폴더`에는 실제 경로를 입력합니다.

```bash
python scripts/prepare_samples.py "압축을_푼_폴더"
```

결과는 `data/samples/`에 저장되며 Git 저장소에는 올라가지 않습니다.

| 묶음 | 장수 | 선정·가공 기준 | 용도 |
|---|---:|---|---|
| A. 기준 영상 | 20장 | PA 촬영, 1024×1024 흑백 영상에서 성별과 나이대가 고르게 분포하도록 환자당 1장 선정 | 정상 품질 영상의 지표 분포를 측정해 품질 기준값 설정 |
| B. AP 영상 | 5장 | AP 촬영 후보 300장 중 대비가 가장 낮은 5장 선정 | 실제 촬영 영상에서 낮은 대비 확인 |
| C. 가공본 | 8장 | A에서 2장씩 골라 밝기 저하, 대비 저하, 잡음 추가, 흐림 적용 | 가공 조건을 아는 영상으로 품질 점검 결과 확인 |

영상 선정에는 진단 결과(`Finding Labels`)를 사용하지 않습니다. 이 시스템은 진단을 수행하지 않습니다. 선정한 파일과 가공 방법은 `data/samples/manifest.csv`에 기록됩니다.

### DICOM 시연 영상

TCIA의 [LIDC-IDRI](https://www.cancerimagingarchive.net/collection/lidc-idri/)에서 흉부 X-ray DICOM 파일을 내려받습니다. 계정 없이 실행할 수 있습니다.

```bash
python scripts/fetch_dicom_samples.py
```

- 기본값은 DX 8명, CR 2명이며 환자당 1장씩 받습니다. 인원은 `--dx`, `--cr` 옵션으로 조절합니다.
- 영상은 `data/samples_dicom/`에 파일 목록인 `manifest.csv`, TCIA의 `LICENSE`와 함께 저장됩니다.

2026-11-17에 받은 DICOM 10장은 모두 등록 검사와 품질 점검을 통과했습니다.

| 지표 | DICOM 10장의 측정 범위 |
|---|---:|
| 밝기 | 137–165 |
| 대비 | 53–73 |
| 잡음 | 2.1–2.8 |
| 선명도 | 102–443 |

품질 기준값은 PNG 기준 영상으로 정했으므로, DICOM에서 **점검 필요**가 표시되면 해당 결과를 별도로 확인합니다.

### 품질 기준값

`pacs/config.py`의 `QUALITY_THRESHOLDS`는 기준 영상 20장의 지표 분포를 측정해 정했습니다.

| 지표 | 점검 필요 조건 | 기준 영상(A) 측정값 | 가공본(C) 측정값 |
|---|---|---|---|
| 밝기(평균) | 90 미만 | 최솟값 102.7 | 밝기 저하 57–59 |
| 대비(표준편차) | 40 미만 | 하위 10% 값 59.1 | 대비 저하 10–22 |
| 잡음(Median 잔차 표준편차) | 5 초과 | 최댓값 3.3 | 잡음 추가 9.6–10.0 |
| 선명도(Laplacian 분산) | 20 미만 | 최솟값 38.5 | 흐림 2.5–4.0 |

**판정 결과** — 가공본 8장과 AP 영상 5장은 모두 **점검 필요**로 판정됐습니다. 기준 영상은 20장 중 19장이 통과했으며, 나머지 1장(`00028539_000.png`)은 육안으로도 대비가 낮았습니다.

#### 등록 시 품질 점검

영상을 처음 등록하거나 다시 올리면 품질 점검 결과를 `images.quality`에 저장합니다. **점검 필요**로 판정되면 `cases.flags.quality_check`가 `True`가 됩니다.

품질 기준에 미달해도 케이스는 등록됩니다. 등록 담당자는 **케이스 등록 → 품질 점검이 필요한 케이스**에서 다음 중 하나를 선택합니다.

| 선택 | 처리 함수 | 처리 결과 |
|---|---|---|
| 다시 올리기 | `cases.replace_image` | 새 영상이 검토 대상(`target_image_id`)이 됩니다. 이전 영상의 기록과 원본 파일은 보존합니다. |
| 사유 입력 후 그대로 진행 | `cases.set_proceed_reason` | 사유를 `images.proceed_reason`에 저장합니다. 검토자가 품질 문제를 확인할 수 있도록 **점검 필요** 표시를 유지합니다. |

두 작업은 **접수** 또는 **보완 요청** 상태에서만 가능합니다. 영상은 자동으로 보정하지 않습니다.

품질 점검 기능을 도입하기 전에 등록한 케이스는 `images.quality`가 비어 있어도 등록 화면에서 **통과**로 표시될 수 있으며 작업화면에는 공백으로 표시됩니다. 영상을 다시 등록하면 품질을 점검합니다.

#### 알려진 한계

- 잡음이 많으면 선명도 지표가 잡음까지 경계로 인식해 값이 크게 올라갑니다. 잡음 가공본의 선명도는 약 2,000이었으며, 잡음 여부는 별도의 잡음 지표로만 판정합니다.
- 지나치게 밝은 영상은 시험하지 않아 밝기 상한을 두지 않았습니다.

### OpenCV로 파일을 읽을 때 주의

Windows에서는 `cv2.imread`와 `cv2.imwrite`가 `바탕 화면`처럼 한글이 포함된 경로에서 파일을 읽거나 쓰는 데 실패할 수 있습니다. `cv2.imread`는 오류 메시지 없이 `None`을 반환할 수 있으므로, 파일을 읽을 때는 바이트로 불러온 뒤 `cv2.imdecode`로 디코딩합니다.

```python
img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
```

## JCloud 배포와 복구

웹 콘솔은 https://jcloud.jedutools.io 입니다 (JEduTools 통합 로그인, 프로젝트 `students`). LMS 11주차 "JCloud 세팅 영상"(2024년 화면)과 메뉴·주소 규칙이 바뀌어, 2026-11-17에 실제로 만들어 보며 확인한 내용으로 적었습니다.

### 접속 주소

인스턴스마다 외부 주소가 따로 정해집니다. 컴퓨팅 → 인스턴스 → 인스턴스 이름 → **세부 정보의 "접속 주소"** 표에서 확인합니다. 내부 IP가 `10.0.0.48`인 경우의 예입니다.

| 인스턴스 안 포트 | 외부 주소 |
|---|---|
| 3000 | `s.jedutools.io:40048` ← **앱 주소** |
| 8080 | `s.jedutools.io:50048` |
| 7777 (SSH) | `s.jedutools.io:10048` |
| 80 / 443 | `s.jedutools.io:20048` / `30048` |

Streamlit 기본 포트 8501은 연결되지 않습니다. 그래서 서버에서는 3000 포트로 띄웁니다.

### 1. 인스턴스 만들기 (웹 콘솔, 한 번만)

컴퓨팅 → 인스턴스 → **인스턴스 생성**에서 이름, 운영체제, 사양, 키 페어만 고릅니다. 네트워크와 보안 그룹(`default`)은 자동으로 정해집니다.

| 항목 | 값 |
|---|---|
| 인스턴스 이름 | 학번 |
| 운영체제 | **`ubuntu.24.04.image`** (22.04는 Python 3.10이라 Streamlit 1.67이 설치되지 않습니다) |
| 사양 | `micro` (2 vCPU, 2GB, 디스크 10GB). 학생이 고를 수 있는 사양은 이것뿐입니다 |
| 키 페어 | 키 페어 생성 후 받은 개인 키 파일을 안전한 곳에 보관. 저장소·메신저·노션에 올리지 않습니다 |

상태가 "활성"이 되면 세부 정보에서 접속 주소를 확인합니다.

### 2. 접속과 비밀 값 올리기 (내 컴퓨터에서)

```bash
ssh -i 키.pem -p 10048 ubuntu@s.jedutools.io
```

서버에서 저장소를 받습니다.

```bash
git clone https://github.com/anjinsung-debug/term_project.git ~/term_project
```

내 컴퓨터에서 서비스 계정 키와 설정 파일을 올립니다. 둘 다 저장소에 없는 파일입니다.

```bash
scp -i 키.pem -P 10048 C:/keys/pacs-firebase.json ubuntu@s.jedutools.io:/home/ubuntu/pacs-firebase.json
```

```bash
scp -i 키.pem -P 10048 .streamlit/secrets.toml ubuntu@s.jedutools.io:/home/ubuntu/term_project/.streamlit/secrets.toml
```

서버의 `secrets.toml`에서 두 줄을 서버 경로로 고칩니다.

```toml
service_account_file = "/home/ubuntu/pacs-firebase.json"
data_dir = "/home/ubuntu/pacs-data"
```

`data_dir`는 저장소 밖 절대 경로로 둡니다. 코드를 다시 받아도 영상 파일이 지워지지 않게 하기 위해서입니다.

### 3. 설치·실행 (서버에서)

```bash
cd ~/term_project && bash deploy/setup.sh
```

`deploy/setup.sh`가 하는 일입니다.

- 비밀 값과 `data_dir`(절대 경로인지) 확인
- `.venv` 만들기, `requirements.txt` 설치
- `deploy/pacs.service`를 systemd 서비스로 등록하고 다시 시작. SSH를 끊거나 서버를 다시 켜도 앱이 계속 떠 있습니다
- 응답을 확인하고 외부 주소와 배포한 커밋을 출력

### 갱신 (main에 새 코드가 들어왔을 때)

```bash
cd ~/term_project && git pull && bash deploy/setup.sh
```

제출 때는 출력된 "배포 커밋"이 LMS에 적는 최종 커밋 SHA와 같은지 확인합니다.

### 상태 확인과 복구

| 상황 | 할 일 |
|---|---|
| 앱이 떠 있는지 | `systemctl status pacs` |
| 오류 원인 보기 | `journalctl -u pacs -n 50` |
| 다시 시작 | `sudo systemctl restart pacs` |
| 서버를 새로 만들어야 할 때 | 1~3단계를 다시 하고, 아래 백업한 영상 폴더를 `data_dir`에 풀기 |

Firestore 기록은 Firebase에 남지만, 영상 파일은 인스턴스 디스크에만 있습니다. 시연 데이터를 등록한 뒤에는 영상 폴더를 내 컴퓨터로 백업해 둡니다.

```bash
ssh -i 키.pem -p 10048 ubuntu@s.jedutools.io "tar czf - -C /home/ubuntu pacs-data" > pacs-data-backup.tar.gz
```

## 협업 규칙

- Issue를 먼저 만들고, 작업 브랜치에서 개발한 뒤 `main`으로 PR을 보냅니다.
- 작성자가 아닌 팀원 1명 이상이 리뷰한 뒤 병합합니다. `main`에 직접 커밋하지 않습니다.
- 커밋 메시지에는 무엇을 왜 바꿨는지 적습니다.
- AI나 외부 코드를 쓴 부분은 PR에 출처와 직접 수정·검증한 내용을 적습니다.

## 데이터 출처

- NIH ChestX-ray14, NIH Clinical Center 제공: https://nihcc.app.box.com/v/ChestXray-NIHCC (이용 제한 없음, 출처 링크·논문 인용·제공자 표기)
- 실제로 받은 곳: Kaggle "Random Sample of NIH Chest X-ray Dataset" (약 5,600장 샘플), 라이선스 CC0: Public Domain
- Xiaosong Wang, Yifan Peng, Le Lu, Zhiyong Lu, Mohammadhadi Bagheri, Ronald Summers. "ChestX-ray8: Hospital-scale Chest X-ray Database and Benchmarks." IEEE CVPR, pp. 3462-3471, 2017.
- 품질 미달 영상은 위 원본에 밝기 저하, 잡음, 흐림을 넣어 직접 가공한 것입니다.
- DICOM 영상: LIDC-IDRI (The Cancer Imaging Archive), 라이선스 CC BY 3.0. 흉부 X-ray(DX·CR)만 사용합니다.
  - Armato III, S. G., McLennan, G., Bidaut, L., et al. "The Lung Image Database Consortium (LIDC) and Image Database Resource Initiative (IDRI): A completed reference database of lung nodules on CT scans." Medical Physics 38(2), pp. 915-931, 2011.
  - 데이터 DOI: https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX
  - Clark, K., Vendt, B., Smith, K., et al. "The Cancer Imaging Archive (TCIA): Maintaining and Operating a Public Information Repository." Journal of Digital Imaging 26(6), pp. 1045-1057, 2013.
  - TCIA 이용 정책에 따라 참여자를 식별하려는 용도로 쓰지 않고, 발표·보고서에 데이터셋과 저장소를 밝힙니다.
