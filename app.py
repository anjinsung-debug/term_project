import streamlit as st

from pacs import auth, config

st.set_page_config(page_title="교육용 웹 PACS", layout="wide")

st.title("교육용 웹 PACS 프로토타입")
st.caption(
    "공개 영상과 모의 케이스만 사용합니다. "
    "모든 수치는 교육용 결과이며 진단에 사용할 수 없습니다."
)

user = auth.require_login()

with st.sidebar:
    st.write(f"**{user['name']}**")
    st.write(config.LABELS[user["role"]])
    if st.button("로그아웃"):
        auth.logout()
        st.rerun()
    st.caption(
        "영상 출처: [NIH ChestX-ray14](https://nihcc.app.box.com/v/ChestXray-NIHCC), "
        "NIH Clinical Center 제공 (Wang et al., CVPR 2017). 일부 영상은 품질 점검을 위해 가공했습니다."
    )


def home():
    st.info("왼쪽 메뉴에서 작업을 선택해 주세요.")


# 역할별 메뉴. 메뉴를 숨기는 것과 별개로, 각 화면과 데이터 함수가 다시 권한을 검사한다.
menu = [st.Page(home, title="홈", default=True)]
if user["role"] == "registrar":
    menu.append(st.Page("pages/register.py", title="케이스 등록"))
menu.append(st.Page("pages/case_detail.py", title="케이스 상세"))

st.navigation(menu).run()
