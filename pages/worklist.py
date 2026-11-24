""" 권한별 작업 목록, 선택 정렬(기한, 접수 시각, 긴급도), 완료 목록

필수 연결: 최신 priority.py와 cases.format_kst(dt, *, with_seconds=False).
"""
import logging
from datetime import datetime, timezone

import streamlit as st

from pacs import auth, cases, config, priority

import pandas as pd


user = auth.require_login()
try:
    auth.require_role(user, *config.ROLES)
except PermissionError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("작업 목록")

st.caption("교육용 모의 케이스 · 모든 시각은 한국 시간(KST)입니다.")
scope = {
    "registrar": "본인이 등록한 케이스",
    "reviewer": "본인에게 배정된 케이스",
    "manager": "전체 케이스",
}
st.caption(f"조회 범위: {scope[user['role']]}")

with st.form("worklist_filters"):
    mock_id_query = st.text_input("모의 케이스 ID 검색")
    urgency = st.selectbox(
        "긴급도", [None, *config.URGENCIES],
        format_func=lambda value: "전체" if value is None else config.LABELS[value],
    )
    st.form_submit_button("조회 / 새로고침")

# 권한별 조회 범위는 데이터 접근 함수 안에서도 검사한다.
try:
    rows = cases.list_cases(user, urgency=urgency, mock_id_query=mock_id_query)
except (PermissionError, cases.CaseError) as exc:
    st.error(str(exc))
    st.stop()
except Exception:
    logging.getLogger(__name__).exception("작업 목록 조회 실패")
    st.error("작업 목록을 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.")
    st.stop()

# 화면 전체에서 같은 now 사용한다. 
# 기한 계산과 표시 모두 UTC 기준으로 한다. KST로 변환은 화면 표시용이다.
now = datetime.now(timezone.utc)


def format_time(value):
    if not priority.valid_time(value):
        return "-"
    return cases.format_kst(value, with_seconds=True)


st.caption(
    f"조회 기준 시각: {format_time(now)} · "
    "조회/새로고침 또는 정렬 기준 변경 시 갱신됩니다."
)


def base_row(case):
    # 모의 ID를 화면의 주 식별자로 사용하고, 점검 필요만 표시한다.
    flags = case.get("flags") or {}
    return {
        "모의 케이스 ID": case.get("mock_id") or "-",
        "긴급도": config.LABELS.get(case.get("urgency"), "확인 필요"),
        "상태": config.LABELS.get(case.get("status"), "확인 필요"),
        "품질": "점검 필요" if flags.get("quality_check") is True else "",
    }
def style_urgency(value):
    """긴급도 셀에만 배경색과 글자색을 지정한다."""
    styles = {
        "긴급": "background-color: #FEE2E2; color: #991B1B;",
        "응급": "background-color: #FFEDD5; color: #9A3412;",
        "일반": "background-color: #DCFCE7; color: #166534;",
    }
    return styles.get(value, "")



# priority는 기한 계산 실패 시 None을 반환한다.
# 계산 불가 미완료도 목록에 남기고, 상태 오류만 별도로 안내한다.
valid_pending, valid_done, invalid = [], [], []
for case in rows:
    if case.get("status") not in config.STATUSES:
        invalid.append({
            **base_row(case),
            "케이스 ID": case["id"],
            "확인 사유": "상태 값이 올바르지 않습니다.",
        })
    elif case["status"] == "done":
        valid_done.append(case)
    else:
        valid_pending.append(case)

# form 밖에서 정렬을 선택하고 pending을 반드시 생성한다.
sort_labels = {
    "due_at": "기한순",
    "registered_at": "접수 시각순",
    "urgency": "긴급도순",
}
sort_by = st.selectbox(
    "미완료 목록 정렬 기준",
    options=list(sort_labels),
    format_func=lambda value: sort_labels[value],
    index=0,
    key="worklist_sort",
)
pending = priority.sort_pending_cases(valid_pending, sort_by=sort_by)
completed = priority.sort_completed_cases(valid_done)

# 선택한 정렬 기준에 따라 안내 문구와 열 순서를 바꾼다.
sort_descriptions = {
    "due_at": "기한이 이른 순 · 같은 기한이면 접수 시각 → 문서 ID순",
    "registered_at": "접수 시각이 이른 순 · 같은 접수 시각이면 기한 → 문서 ID순",
    "urgency": "긴급 → 응급 → 일반 · 같은 긴급도이면 접수 시각 → 문서 ID순",
}
column_orders = {
    "due_at": ["모의 케이스 ID", "기한", "긴급도", "접수 시각"],
    "registered_at": ["모의 케이스 ID", "접수 시각", "기한", "긴급도"],
    "urgency": ["모의 케이스 ID", "긴급도", "기한", "접수 시각"],
}
# 기한 초과·업무 상태도 확인할 수 있게 두고, 품질은 마지막에 표시한다.
pending_columns = column_orders[sort_by] + ["기한 상태", "상태", "품질"]

pending_tab = st.container() 

with pending_tab:
    st.markdown(f"진행 중인 케이스 ({len(pending)})") 
    st.caption(sort_descriptions[sort_by])
    if not pending:
        st.info("조회 조건에 맞는 미완료 케이스가 없습니다.")
    else:
        display = []
        has_unknown_deadline = False
        for case in pending:
            due_at = priority.calculate_due_at(case)
            # None을 먼저 검사하여 '기한 내'로 오표시하지 않는다.
            if due_at is None:
                deadline_status = "기한 계산 불가"
                has_unknown_deadline = True
            elif priority.is_overdue(case, now):
                deadline_status = "기한 초과"
            else:
                deadline_status = "기한 내"

            row = {
                **base_row(case),
                "접수 시각": format_time(case.get("registered_at")),
                "기한": format_time(due_at),
                "기한 상태": deadline_status,
            }
            display.append({column: row[column] for column in pending_columns})
        df = pd.DataFrame(display)

        styled_df = df.style.map(style_urgency, subset=["긴급도"],)
        st.dataframe(styled_df, hide_index=True, use_container_width=True,
                     column_config={
                            "품질": st.column_config.TextColumn(
                                "품질",
                                 help=("빈칸은 '점검필요'표시가 없다는 뜻이며, "
                                        "품질 통과를 보장하지 않습니다."),
                            ),
                         }
    )
        if has_unknown_deadline:
            st.warning("기한 계산 불가 항목은 마지막에 표시했습니다. 접수 시각과 긴급도를 확인해 주세요.")


with st.expander(
    f":blue[완료 케이스 보기 ({len(completed)})]",
    expanded=False,
):
    st.caption("완료 시각 최신순 · 같은 완료 시각이면 문서 ID순 · 시각 확인 불가 항목은 마지막")
    if not completed:
        st.info("조회 조건에 맞는 완료 케이스가 없습니다.")
    else:
        # None뿐 아니라 문자열·시간대 없는 완료 시각도 안전하게 표시한다.
        display = []
        for case in completed:
            row = base_row(case)
            display.append({
                "모의 케이스 ID": row["모의 케이스 ID"],
                "완료 시각": format_time(case.get("completed_at")),
                "긴급도": row["긴급도"],
                "상태": row["상태"],
                "품질": row["품질"],
            })
        st.dataframe(display, hide_index=True, use_container_width=True,
                     column_config={
                         "품질": st.column_config.TextColumn(
                             "품질",
                             help=("빈칸은 '점검필요'표시가 없다는 뜻이며, "
                                   "품질 통과를 보장하지 않습니다."),
                         ),
                     }
        )
        if any(not priority.valid_time(case.get("completed_at")) for case in completed):
            st.warning("완료 시각이 없거나 올바르지 않은 기록이 있습니다. 관리 담당자에게 확인해 주세요.")

if invalid:
    st.warning("상태 값 확인이 필요한 케이스는 정렬 목록과 별도로 표시합니다.")
    st.dataframe(invalid, hide_index=True, use_container_width=True)


st.page_link("pages/case_detail.py", label="케이스 상세 화면으로 이동")
