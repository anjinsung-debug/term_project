"""로그인, 로그아웃, 역할 확인.

- 로그인은 Firebase Authentication(이메일/비밀번호)으로 확인한다.
- 역할은 Firestore의 users/{uid}.role에서 읽는다. 역할이 없는 계정은 로그인시키지 않는다.
- 권한 검사는 화면이 아니라 데이터를 읽고 쓰는 함수 안에서 require_role로 한다 (CLAUDE.md 3장).
"""
import requests
import streamlit as st

from pacs import config, firebase_app

SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"

# Firebase가 돌려주는 오류 코드를 사용자에게 보여줄 문장으로 바꾼다.
_ERROR_MESSAGES = {
    "INVALID_LOGIN_CREDENTIALS": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_PASSWORD": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "EMAIL_NOT_FOUND": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_EMAIL": "이메일 형식이 올바르지 않습니다.",
    "MISSING_PASSWORD": "비밀번호를 입력해 주세요.",
    "USER_DISABLED": "사용이 중지된 계정입니다. 관리 담당자에게 문의해 주세요.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
}

SESSION_KEY = "user"


class AuthError(Exception):
    """로그인 실패. 메시지는 화면에 그대로 보여준다."""


def error_message(code):
    # Firebase는 "TOO_MANY_ATTEMPTS_TRY_LATER : 설명"처럼 뒤에 설명을 붙이기도 한다.
    return _ERROR_MESSAGES.get(code.split(" ")[0], "로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.")


def check_role(role):
    """users 문서의 역할 값이 정해진 값인지 확인하고 그대로 돌려준다."""
    if role not in config.ROLES:
        raise AuthError("역할이 지정되지 않은 계정입니다. 관리 담당자에게 문의해 주세요.")
    return role


def sign_in(email, password):
    """이메일과 비밀번호를 확인하고 {"uid", "email", "role", "name"}을 돌려준다."""
    email = email.strip()
    if not email or not password:
        raise AuthError("이메일과 비밀번호를 모두 입력해 주세요.")
    try:
        r = requests.post(
            SIGN_IN_URL,
            params={"key": firebase_app.web_api_key()},
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
    except requests.RequestException as e:
        raise AuthError("로그인 서버에 연결하지 못했습니다. 네트워크를 확인해 주세요.") from e
    body = r.json()
    if r.status_code != 200:
        raise AuthError(error_message(body.get("error", {}).get("message", "")))

    uid = body["localId"]
    doc = firebase_app.db().collection("users").document(uid).get()
    data = doc.to_dict() or {}
    return {
        "uid": uid,
        "email": body.get("email", email),
        "role": check_role(data.get("role")),
        "name": data.get("display_name") or email,
    }


def require_role(user, *roles):
    """데이터를 읽고 쓰는 함수 맨 앞에서 부른다. 권한이 없으면 PermissionError."""
    if not user:
        raise PermissionError("로그인이 필요합니다.")
    if user.get("role") not in roles:
        allowed = ", ".join(config.LABELS[r] for r in roles)
        raise PermissionError(f"{allowed}만 할 수 있는 작업입니다.")


# --- 화면에서 쓰는 함수 ---

def current_user():
    return st.session_state.get(SESSION_KEY)


def logout():
    st.session_state.pop(SESSION_KEY, None)


def login_form():
    """로그인 화면을 그린다. 로그인에 성공하면 화면을 다시 그린다."""
    st.subheader("로그인")
    with st.form("login"):
        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        try:
            st.session_state[SESSION_KEY] = sign_in(email, password)
        except (AuthError, RuntimeError) as e:
            st.error(str(e))
        else:
            st.rerun()


def require_login():
    """화면 맨 앞에서 부른다. 로그인하지 않았으면 로그인 화면만 보여주고 멈춘다."""
    user = current_user()
    if user is None:
        login_form()
        st.stop()
    return user
