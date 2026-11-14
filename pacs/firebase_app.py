"""Firebase 연결을 한 곳에서 만든다.

앱은 서버에서 서비스 계정 키로 Firebase에 접속한다.
설정 값은 .streamlit/secrets.toml의 [firebase] 항목에서 읽는다 (README "Firebase 설정").
"""
import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore


def _settings():
    try:
        return st.secrets["firebase"]
    except (KeyError, FileNotFoundError) as e:
        raise RuntimeError(
            ".streamlit/secrets.toml에 [firebase] 설정이 없습니다. README의 'Firebase 설정'을 따라 만들어 주세요."
        ) from e


def web_api_key():
    key = _settings().get("web_api_key", "")
    if not key:
        raise RuntimeError("secrets.toml의 web_api_key가 비어 있습니다.")
    return key


@st.cache_resource
def db():
    """Firestore 클라이언트. 앱 전체에서 하나만 만들어 재사용한다."""
    if not firebase_admin._apps:
        path = _settings().get("service_account_file", "")
        try:
            cred = credentials.Certificate(path)
        except (FileNotFoundError, ValueError) as e:
            raise RuntimeError(
                f"서비스 계정 키 파일을 읽을 수 없습니다: {path}. secrets.toml의 service_account_file을 확인해 주세요."
            ) from e
        firebase_admin.initialize_app(cred)
    return firestore.client()
