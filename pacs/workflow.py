"""상태 전이 표와 전이 실행, 변경 기록.

- 기준은 노션 설계 문서 3장 "상태 전이표"다. 표에 없는 전이는 거절한다.
- 권한 검사는 전이 함수 안에서 한다 (역할, 담당 범위, 현재 상태, 조건).
- 상태 변경과 case_events 기록은 Firestore 트랜잭션 하나로 저장한다. 둘 중 하나만 저장되는 일은 없다.
- 트랜잭션 안에서 현재 상태를 다시 읽으므로, 버튼을 두 번 눌러도 두 번째는 "지금 상태에서는 할 수 없습니다"로 거절된다.
"""
from collections import namedtuple
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from pacs import config, firebase_app
from pacs.auth import require_role
from pacs.cases import CaseError, can_view, get_case

# 시스템이 자동으로 바꾸는 전이(두 검토 제출 후 판정)에 쓰는 실행 주체.
# 화면에서 로그인한 사용자는 이 역할을 가질 수 없다 (auth.check_role이 config.ROLES만 허용).
SYSTEM = {"uid": "system", "role": "system", "name": "시스템"}

Transition = namedtuple("Transition", "from_status to_status role needs_reason")

# 동작: (현재 상태, 다음 상태, 실행 주체, 사유 필수 여부). 노션 3장과 같은 순서다.
# 동작 이름은 case_events.action에 그대로 저장된다.
TRANSITIONS = {
    "register": Transition(None, "received", "registrar", False),  # cases.register_case가 기록한다
    "assign": Transition("received", "assigned", "manager", False),
    "start_review": Transition("assigned", "in_review", "reviewer", False),
    "auto_match": Transition("in_review", "done", "system", False),
    "auto_mismatch": Transition("in_review", "arbitration", "system", False),
    "arbitrate": Transition("arbitration", "done", "manager", False),
    "request_revision": Transition("in_review", "revision_requested", "reviewer", True),
    "revision_done": Transition("revision_requested", "in_review", "registrar", False),
    "reopen": Transition("done", "in_review", "manager", True),
}


class TransitionError(Exception):
    """허용되지 않은 전이. 메시지는 화면에 그대로 보여준다."""


def _check_actor(user, case, t):
    if t.role == "system":
        if not user or user.get("role") != "system":
            raise PermissionError("시스템이 자동으로 처리하는 단계입니다.")
        return
    require_role(user, t.role)
    # 등록 담당은 본인이 등록한 케이스, 검토 담당은 본인에게 배정된 케이스만.
    # 없는 케이스와 같은 오류를 내서 남의 케이스가 있는지 알려주지 않는다 (cases.get_case와 같은 방식).
    if not can_view(user, case):
        raise CaseError("케이스를 찾을 수 없습니다.")


def plan(user, case, action, *, reason=None, reviewer_uids=None, now=None):
    """전이를 검사하고 (케이스에 바꿀 값, case_events에 남길 기록)을 돌려준다. 저장은 하지 않는다.

    case는 Firestore 케이스 문서에 "id"를 더한 딕셔너리다.
    """
    t = TRANSITIONS.get(action)
    if t is None or t.from_status is None:
        raise TransitionError("알 수 없는 동작입니다.")
    _check_actor(user, case, t)

    status = case.get("status")
    if status != t.from_status:
        raise TransitionError(
            f"지금 상태({config.LABELS.get(status, status)})에서는 "
            f"'{config.LABELS[action]}'을(를) 할 수 없습니다. 화면을 새로 고쳐 주세요."
        )
    reason = (reason or "").strip() or None
    if t.needs_reason and not reason:
        raise TransitionError("사유를 입력해 주세요.")

    now = now or datetime.now(timezone.utc)
    updates = {"status": t.to_status, "updated_at": now}
    if action == "assign":
        uids = [u for u in (reviewer_uids or []) if u]
        if len(uids) != 2 or uids[0] == uids[1]:
            raise TransitionError("서로 다른 검토 담당자 2명을 지정해 주세요.")
        updates["reviewer_uids"] = uids
    if t.to_status == "done":
        updates["completed_at"] = now
    if t.from_status == "done":
        updates["completed_at"] = None  # 재검토로 다시 열리면 완료 목록에서 빠진다
    if action == "auto_mismatch":
        updates["flags.mismatch"] = True  # 다른 flags 값은 그대로 둔다

    event = {
        "case_id": case["id"],
        "action": action,
        "from_status": status,
        "to_status": t.to_status,
        "actor_uid": user["uid"],
        "reason": reason,
        "at": now,
    }
    return updates, event


def apply(transaction, user, case_id, action, *, reason=None, reviewer_uids=None):
    """트랜잭션 안에서 전이를 실행하고 새 상태를 돌려준다.

    다른 기록과 함께 한 번에 저장해야 할 때 쓴다. 예: 중재 확정 의견(comparisons)과 상태 변경.
    Firestore 트랜잭션은 읽기를 모두 마친 뒤에 써야 하므로, 부르는 쪽도 읽기를 먼저 끝내고 이 함수를 부른다.
    """
    db = firebase_app.db()
    case_ref = db.collection("cases").document(case_id)
    snap = case_ref.get(transaction=transaction)
    if not snap.exists:
        raise CaseError("케이스를 찾을 수 없습니다.")
    updates, event = plan(
        user, {"id": case_id, **snap.to_dict()}, action, reason=reason, reviewer_uids=reviewer_uids
    )
    if action == "assign":
        for uid in updates["reviewer_uids"]:
            account = db.collection("users").document(uid).get(transaction=transaction).to_dict() or {}
            if account.get("role") != "reviewer":
                raise TransitionError("검토 담당자 계정만 배정할 수 있습니다.")

    transaction.update(case_ref, updates)
    transaction.set(db.collection("case_events").document(), event)
    return updates["status"]


def transition(user, case_id, action, *, reason=None, reviewer_uids=None):
    """전이 하나를 실행하고 새 상태를 돌려준다. 화면에서는 이 함수를 부른다."""

    @firestore.transactional
    def run(transaction):
        return apply(transaction, user, case_id, action, reason=reason, reviewer_uids=reviewer_uids)

    try:
        return run(firebase_app.db().transaction())
    except (TransitionError, CaseError, PermissionError):
        raise
    except Exception as e:
        # 트랜잭션이라 일부만 저장되지는 않는다. 다시 시도하면 된다.
        raise TransitionError("상태를 바꾸지 못했습니다. 잠시 후 다시 시도해 주세요.") from e


def allowed_actions(user, case):
    """지금 이 사용자가 이 케이스에서 할 수 있는 동작 목록. 화면에서 버튼을 고를 때 쓴다.

    화면 표시용일 뿐이고, 실제 검사는 transition()이 다시 한다.
    """
    result = []
    for action, t in TRANSITIONS.items():
        if t.role == "system" or t.from_status != case.get("status"):
            continue
        if user and user.get("role") == t.role and can_view(user, case):
            result.append(action)
    return result


# --- 화면에서 쓰는 조회 ---

def list_events(user, case_id):
    """케이스의 상태 변경 기록(case_events)을 오래된 순으로 돌려준다. 케이스를 볼 수 있는 사람만."""
    get_case(user, case_id)  # 역할·담당 범위 확인
    query = firebase_app.db().collection("case_events").where(filter=FieldFilter("case_id", "==", case_id))
    rows = [{"id": d.id, **d.to_dict()} for d in query.stream()]
    rows.sort(key=lambda r: r.get("at") or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def reviewer_accounts(user):
    """배정할 수 있는 검토 담당자 목록 [{"uid", "name"}]. 관리 담당자만."""
    require_role(user, "manager")
    query = firebase_app.db().collection("users").where(filter=FieldFilter("role", "==", "reviewer"))
    rows = [{"uid": d.id, "name": _name(d.to_dict())} for d in query.stream()]
    return sorted(rows, key=lambda r: r["name"])


def display_names(user, uids):
    """{uid: 화면에 보일 이름}. 배정된 검토자와 기록의 실행자를 보여줄 때 쓴다."""
    require_role(user, *config.ROLES)
    users = firebase_app.db().collection("users")
    names = {}
    for uid in set(uids) - {None}:
        if uid == SYSTEM["uid"]:
            names[uid] = SYSTEM["name"]
            continue
        doc = users.document(uid).get()
        names[uid] = _name(doc.to_dict() or {}) if doc.exists else uid
    return names


def _name(account):
    return account.get("display_name") or account.get("email") or "(이름 없음)"
