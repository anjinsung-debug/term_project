import pytest

from pacs import auth


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeDb:
    def __init__(self, users):
        self.users = users

    def collection(self, name):
        assert name == "users"
        return self

    def document(self, uid):
        self.uid = uid
        return self

    def get(self):
        return FakeDoc(self.users.get(self.uid))


@pytest.fixture
def firebase(monkeypatch):
    """Firebase에 접속하지 않도록 로그인 응답과 users 문서를 바꿔 끼운다."""
    state = {"response": None, "users": {}}
    monkeypatch.setattr(auth.firebase_app, "web_api_key", lambda: "test-key")
    monkeypatch.setattr(auth.firebase_app, "db", lambda: FakeDb(state["users"]))
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: state["response"])
    return state


def test_sign_in_returns_user_with_role(firebase):
    firebase["response"] = FakeResponse(200, {"localId": "u1", "email": "r@pacs.test"})
    firebase["users"]["u1"] = {"role": "reviewer", "display_name": "검토자 A"}
    user = auth.sign_in(" r@pacs.test ", "pw")
    assert user == {"uid": "u1", "email": "r@pacs.test", "role": "reviewer", "name": "검토자 A"}


def test_sign_in_wrong_password_shows_korean_message(firebase):
    firebase["response"] = FakeResponse(400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}})
    with pytest.raises(auth.AuthError, match="올바르지 않습니다"):
        auth.sign_in("r@pacs.test", "wrong")


def test_sign_in_rejects_account_without_role(firebase):
    firebase["response"] = FakeResponse(200, {"localId": "u2", "email": "x@pacs.test"})
    with pytest.raises(auth.AuthError, match="역할이 지정되지 않은"):
        auth.sign_in("x@pacs.test", "pw")


def test_sign_in_rejects_unknown_role(firebase):
    firebase["response"] = FakeResponse(200, {"localId": "u3", "email": "x@pacs.test"})
    firebase["users"]["u3"] = {"role": "admin"}
    with pytest.raises(auth.AuthError):
        auth.sign_in("x@pacs.test", "pw")


def test_sign_in_requires_both_fields(firebase):
    with pytest.raises(auth.AuthError, match="모두 입력"):
        auth.sign_in("  ", "pw")


def test_error_message_ignores_extra_description():
    assert "잠시 후" in auth.error_message("TOO_MANY_ATTEMPTS_TRY_LATER : Access disabled")
    assert "잠시 후" in auth.error_message("SOMETHING_NEW")


def test_require_role():
    auth.require_role({"role": "manager"}, "manager")
    with pytest.raises(PermissionError, match="관리 담당자만"):
        auth.require_role({"role": "reviewer"}, "manager")
    with pytest.raises(PermissionError, match="로그인이 필요"):
        auth.require_role(None, "manager")
