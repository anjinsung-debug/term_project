"""케이스 메모와 리포트 (notes 컬렉션, 노션 4-1).

- 검토 메모는 여기가 아니라 reviews.memo에 둔다. notes는 일반 메모(memo)와 리포트(report)에만 쓴다.
- 메모는 케이스를 볼 수 있는 사람 누구나 쓴다. 리포트는 관리 담당자가 완료된 케이스에만 쓴다.
- 블라인드 규칙: 검토 담당은 두 검토가 모두 제출되기 전(comparisons 문서가 생기기 전)에는
  다른 검토자의 메모를 볼 수 없다. 등록·관리 담당의 메모와 재검토 전 회차의 메모는 언제든 보인다.
- 고칠 수 있는 사람은 쓴 사람뿐이고, 고치기 전 내용은 edit_history에 남는다.
"""
import hashlib
import json
from datetime import datetime, timezone

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

from pacs import config, firebase_app
from pacs.workflow import current_round
from pacs.auth import require_role
from pacs.cases import CaseError, format_kst, get_case


class NoteError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메모 저장 실패."""


def note_id_for(case_id, uid, note_type, body):
    """같은 사람이 같은 케이스에 같은 내용을 쓰면 같은 ID가 나온다. 버튼을 여러 번 눌러도 기록은 하나다."""
    # ponytail: 내용으로 ID를 만들어서, 같은 문장을 일부러 두 번 남기는 것도 하나로 합쳐진다.
    key = json.dumps([case_id, uid, note_type, body], ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def _clean(body):
    body = (body or "").strip()
    if not body:
        raise NoteError("내용을 입력해 주세요.")
    if len(body) > config.NOTE_MAX_LENGTH:
        raise NoteError(f"{config.NOTE_MAX_LENGTH}자 이하로 써 주세요.")
    return body


def add(user, case_id, body, note_type="memo"):
    """메모나 리포트를 저장한다. (메모 ID, 새로 만들었는지)를 돌려준다."""
    case = get_case(user, case_id)  # 역할·담당 범위 확인
    if note_type not in config.NOTE_TYPES:
        raise NoteError("알 수 없는 메모 종류입니다.")
    if note_type == "report":
        require_role(user, "manager")
        if case.get("status") != "done":
            raise NoteError("리포트는 완료된 케이스에만 쓸 수 있습니다.")
    body = _clean(body)
    note_id = note_id_for(case_id, user["uid"], note_type, body)
    record = {
        "case_id": case_id,
        "image_id": case.get("target_image_id"),
        "type": note_type,
        "body": body,
        "author_uid": user["uid"],
        "round": current_round(case),  # 쓴 때의 검토 회차 (재검토 뒤 블라인드 판단에 씀)
        "created_at": datetime.now(timezone.utc),
        "edited_at": None,
        "edit_history": [],
    }
    try:
        firebase_app.db().collection("notes").document(note_id).create(record)
    except AlreadyExists:
        return note_id, False
    return note_id, True


def edit(user, note_id, body):
    """본인이 쓴 메모를 고친다. 고치기 전 내용과 시각을 edit_history에 남긴다. 바뀐 게 없으면 False."""
    ref = firebase_app.db().collection("notes").document(note_id)
    snap = ref.get()
    note = snap.to_dict() if snap.exists else None
    if note is None or not _visible(user, get_case(user, note["case_id"]), note):
        raise CaseError("메모를 찾을 수 없습니다.")
    if note["author_uid"] != user["uid"]:
        raise PermissionError("본인이 쓴 메모만 고칠 수 있습니다.")
    body = _clean(body)
    if body == note["body"]:
        return False
    # ponytail: 읽고 덧붙여 쓰므로 두 곳에서 동시에 고치면 기록 하나가 빠질 수 있다. 필요하면 트랜잭션으로 바꾼다.
    history = note.get("edit_history") or []
    history.append({"body": note["body"], "edited_at": note.get("edited_at") or note["created_at"]})
    ref.update({"body": body, "edited_at": datetime.now(timezone.utc), "edit_history": history})
    return True


def _visible(user, case, note, compared=None):
    """블라인드 규칙. compared는 두 검토가 모두 제출됐는지(모르면 None → 직접 확인)."""
    if user["role"] != "reviewer" or note["author_uid"] == user["uid"]:
        return True
    if note["author_uid"] not in (case.get("reviewer_uids") or []):
        return True  # 등록·관리 담당의 메모
    if (note.get("round") or 1) < current_round(case):
        return True  # 이전 회차의 메모. 그 회차는 두 검토가 모두 제출된 뒤 닫혔다
    if compared is None:
        compared = _compared(case["id"])
    return compared


def _compared(case_id):
    # 판정 기록(comparisons)은 두 번째 검토가 제출될 때 처음 생긴다 (pacs/reviews.py).
    return firebase_app.db().collection("comparisons").document(case_id).get().exists


def list_notes(user, case_id):
    """볼 수 있는 메모·리포트를 오래된 순으로 돌려준다."""
    case = get_case(user, case_id)
    query = firebase_app.db().collection("notes").where(filter=FieldFilter("case_id", "==", case_id))
    rows = [{"id": d.id, **d.to_dict()} for d in query.stream()]
    compared = _compared(case_id) if user["role"] == "reviewer" else True
    rows = [r for r in rows if _visible(user, case, r, compared)]
    rows.sort(key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc))
    return rows


CHOICE_LABELS = {"a": "검토자 A의 ROI", "b": "검토자 B의 ROI", "custom": "관리 담당이 새로 그린 ROI", "none": "ROI 없음"}


def report_draft(case, comparison, logs, names):
    """리포트 초안. 판정·중재 결과와 저장된 처리 이력(알고리즘·설정값·실행자·시간)을 정리한다.

    names는 {UID: 표시 이름}. 관리 담당이 고쳐서 저장한다.
    """
    lines = [
        f"모의 케이스 {case['mock_id']} · {config.LABELS[case['urgency']]} · {config.LABELS[case['status']]}",
        f"완료 시각: {format_kst(case.get('completed_at'))}",
    ]
    if comparison:
        lines.append(
            f"자동 판정: {config.LABELS[comparison['verdict']]} "
            f"(겹침 비율 {comparison['iou']:.2f}, 기준 {comparison['iou_threshold']})"
        )
        arb = comparison.get("arbitration")
        if arb:
            lines.append(
                f"중재: {CHOICE_LABELS.get(arb['choice'], arb['choice'])} · {names.get(arb.get('decided_by'), '-')} · 사유: {arb.get('reason') or '-'}"
            )
    lines.append("처리 이력:" if logs else "처리 이력: 없음")
    for log in logs:
        lines.append(
            f"- {config.LABELS.get(log['algorithm'], log['algorithm'])} v{log['algorithm_version']} "
            f"{log['params']} · {names.get(log.get('executed_by'), '-')} · {format_kst(log.get('executed_at'))}"
        )
    lines.append("교육용 결과이며 진단에 사용할 수 없습니다.")
    return "\n".join(lines)
