# 교육용 웹 PACS 프로토타입

긴급도와 영상 품질에 따라 검토 순서를 정하고, 두 검토자의 블라인드 이중 검토에서 ROI 불일치를 자동 감지해 중재까지 관리하는 교육용 웹 PACS입니다.

> 공개 영상과 모의 케이스만 사용합니다. 모든 수치는 교육용 결과이며 진단에 사용할 수 없습니다.

- 기술 스택: Python, Streamlit, Firebase Authentication, Cloud Firestore, JCloud
- 지원 영상: 흉부 X-ray (PNG, JPEG)

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `app.py` | Streamlit 앱 시작점 |
| `pacs/config.py` | 팀이 합의한 값과 기준값 (역할, 상태, 긴급도, 기준값) |
| `tests/` | pytest 자동화 테스트 |
| `.streamlit/secrets.toml.example` | 비밀 값 양식 |
| `.github/pull_request_template.md` | PR 양식 |
| `CLAUDE.md` | 프로젝트 규칙 |

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
