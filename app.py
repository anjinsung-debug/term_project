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

st.info("기본 틀을 준비하고 있습니다. 역할별 메뉴가 여기에 들어갑니다.")
