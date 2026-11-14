"""테스트 계정을 만들거나 역할을 바꾼다.

Firebase Authentication에 계정을 만들고, Firestore users/{uid}에 역할을 적는다.
비밀번호는 화면에 표시하지 않고 입력받는다. 계정 정보는 저장소에 적지 않고 LMS 제출란에만 적는다.

사용법 (프로젝트 폴더에서):
    python scripts/create_user.py 이메일 역할 [표시이름]
    역할: registrar(등록), reviewer(검토), manager(관리)

이미 있는 계정이면 비밀번호는 그대로 두고 역할과 표시 이름만 바꾼다.
"""
import getpass
import sys
import tomllib
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials, firestore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pacs import config  # noqa: E402


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    email, role = sys.argv[1], sys.argv[2]
    name = sys.argv[3] if len(sys.argv) == 4 else email
    if role not in config.ROLES:
        sys.exit(f"역할은 {', '.join(config.ROLES)} 중 하나여야 합니다.")

    secrets = tomllib.loads(Path(".streamlit/secrets.toml").read_text(encoding="utf-8"))
    firebase_admin.initialize_app(credentials.Certificate(secrets["firebase"]["service_account_file"]))

    try:
        user = auth.get_user_by_email(email)
        print(f"이미 있는 계정입니다. 역할만 {role}(으)로 바꿉니다.")
    except auth.UserNotFoundError:
        password = getpass.getpass("비밀번호 (6자 이상, 화면에 표시되지 않음): ")
        if len(password) < 6:
            sys.exit("비밀번호는 6자 이상이어야 합니다.")
        user = auth.create_user(email=email, password=password, display_name=name)
        print("계정을 만들었습니다.")

    firestore.client().collection("users").document(user.uid).set(
        {
            "email": email,
            "display_name": name,
            "role": role,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    print(f"{email} → {config.LABELS[role]}")


if __name__ == "__main__":
    main()
