"""케이스 기한 계산과 정렬. DB 저장이나 화면 출력은 하지 않는다."""
from datetime import datetime, timedelta, timezone
from pacs import config
MAX_TIME = datetime.max.replace(tzinfo=timezone.utc)

def valid_time(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None

def calculate_due_at(case):
    registered_at = case.get('registered_at')
    target = config.TARGET_TIME.get(case.get('urgency'))
    if not valid_time(registered_at) or target is None:
        return None
    try:
        return registered_at.astimezone(timezone.utc) + target
    except OverflowError:
        return None

def is_overdue(case, now):
    if not valid_time(now):
        raise ValueError('현재 시각에는 시간대 정보가 필요합니다.')
    status = case.get('status')
    if status not in config.STATUSES or status == 'done':
        return False
    due_at = calculate_due_at(case)
    return due_at is not None and now > due_at

def sort_pending_cases(rows, sort_by='due_at'):
    if sort_by not in ('due_at', 'registered_at', 'urgency'):
        raise ValueError('지원하지 않는 정렬 방식입니다.')
    pending = [case for case in rows if case.get('status') in config.STATUSES and case['status'] != 'done']
    def sort_key(case):
        due_at = calculate_due_at(case)
        registered_at = case.get('registered_at')
        case_id = case['id']
        invalid = due_at is None
        if invalid:
            registered_at = MAX_TIME
            due_at = MAX_TIME
        else:
            registered_at = registered_at.astimezone(timezone.utc)
        if sort_by == 'due_at':
            return invalid, due_at, registered_at, case_id
        if sort_by == 'registered_at':
            return invalid, registered_at, due_at, case_id
        target = timedelta.max if invalid else config.TARGET_TIME[case['urgency']]
        return invalid, target, registered_at, case_id
    return sorted(pending, key=sort_key)

def sort_completed_cases(rows):
    completed = [case for case in rows if case.get('status') == 'done']
    valid = [case for case in completed if valid_time(case.get('completed_at'))]
    missing = [case for case in completed if not valid_time(case.get('completed_at'))]
    valid = sorted(valid, key=lambda case: case['id'])
    valid = sorted(valid, key=lambda case: case['completed_at'], reverse=True)
    missing = sorted(missing, key=lambda case: case['id'])
    return valid + missing



