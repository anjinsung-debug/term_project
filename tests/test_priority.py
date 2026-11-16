"""최신 pacs/priority.py 테스트.

대상: 계산 불가 시 None 반환, sort_by 3종을 지원하는 버전.
프로젝트 루트에서: python -m pytest tests/test_priority.py -v
pytest 없이 실행: python -m unittest discover -s tests -p test_priority.py -v
Firebase나 로그인 없이 계산 함수만 테스트한다.
"""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pacs import config, priority

UTC = timezone.utc
KST = timezone(timedelta(hours=9))
# 한국 시간 2026-11-15 10:00. 테스트 시각을 고정해 항상 같은 결과를 얻는다.
BASE = datetime(2026, 11, 15, 10, tzinfo=KST).astimezone(UTC)
SORT_MODES = ('due_at', 'registered_at', 'urgency')


def make_case(case_id='a', **changes):
    """실제 프로젝트 필드명을 사용하는 모의 데이터. DB에는 저장하지 않는다."""
    row = {
        'id': case_id,
        'mock_id': f'MOCK-{case_id}',
        'registered_at': BASE,
        'urgency': 'urgent',
        'status': 'received',
        'completed_at': None,
        'flags': {'quality_check': False},
    }
    row.update(changes)
    return row


def ids(rows):
    return [row['id'] for row in rows]


class PriorityTests(unittest.TestCase):
    def test_valid_time(self):
        """UTC/KST는 허용하고, None·문자열·시간대 없는 시각은 거부한다."""
        for value in (BASE, BASE.astimezone(KST)):
            with self.subTest(value=value):
                self.assertTrue(priority.valid_time(value))
        for value in (None, '2026-11-15', 123, BASE.replace(tzinfo=None)):
            with self.subTest(value=value):
                self.assertFalse(priority.valid_time(value))

    def test_due_at_for_three_urgencies(self):
        """합의된 목표 시간: 긴급 1시간, 응급 4시간, 일반 24시간."""
        for urgency, hours in [('urgent', 1), ('emergency', 4), ('routine', 24)]:
            with self.subTest(urgency=urgency):
                row = make_case(urgency=urgency)
                self.assertEqual(priority.calculate_due_at(row), BASE + timedelta(hours=hours))

    def test_due_at_is_utc(self):
        due = priority.calculate_due_at(make_case(registered_at=BASE.astimezone(KST)))
        self.assertEqual(due, BASE + timedelta(hours=1))
        self.assertEqual(due.utcoffset(), timedelta(0))

    def test_invalid_data_returns_none(self):
        rows = [make_case(registered_at=None), make_case(registered_at='bad'),
                make_case(registered_at=BASE.replace(tzinfo=None)),
                make_case(urgency='unknown'), make_case(urgency=None), {}]
        for row in rows:
            with self.subTest(row=row):
                self.assertIsNone(priority.calculate_due_at(row))

    def test_datetime_overflow_returns_none(self):
        row = make_case(registered_at=datetime.max.replace(tzinfo=UTC))
        self.assertIsNone(priority.calculate_due_at(row))

    def test_overdue_boundary(self):
        """11:00까지 False, 11:00을 지난 순간부터 True."""
        row = make_case()
        due = BASE + timedelta(hours=1)
        self.assertFalse(priority.is_overdue(row, due - timedelta(microseconds=1)))
        self.assertFalse(priority.is_overdue(row, due))
        self.assertTrue(priority.is_overdue(row, due + timedelta(microseconds=1)))

    def test_fixed_deadline_and_remaining_time(self):
        """10:20/10:50/11:10에 확인해도 기한은 11:00으로 고정된다.

        대기·남은 시간은 별도 반환 함수가 없으므로 해당 관계식을 함께 검증한다.
        """
        row = make_case()
        for minutes, remaining, overdue in [(20, 40, False), (50, 10, False), (70, -10, True)]:
            with self.subTest(minutes=minutes):
                now = BASE + timedelta(minutes=minutes)
                due = priority.calculate_due_at(row)
                waiting = now - row['registered_at']
                self.assertEqual(due, BASE + timedelta(hours=1))
                self.assertEqual(due - now, timedelta(minutes=remaining))
                self.assertEqual(due - now, config.TARGET_TIME['urgent'] - waiting)
                self.assertEqual(priority.is_overdue(row, now), overdue)

    def test_not_overdue_when_done_invalid_or_uncalculable(self):
        rows = [make_case(status='done'), make_case(status='unknown'),
                make_case(registered_at=None), make_case(urgency='bad')]
        for row in rows:
            with self.subTest(row=row):
                self.assertFalse(priority.is_overdue(row, BASE + timedelta(days=2)))

    def test_invalid_now_raises_value_error(self):
        for now in (None, 'bad', BASE.replace(tzinfo=None)):
            with self.subTest(now=now), self.assertRaises(ValueError):
                priority.is_overdue(make_case(), now)

    def test_due_sort_uses_deadline_not_urgency(self):
        rows = [make_case('urgent'), make_case('routine', urgency='routine',
                registered_at=BASE - timedelta(hours=24))]
        self.assertEqual(ids(priority.sort_pending_cases(rows)), ['routine', 'urgent'])

    def test_equal_deadlines_use_registration_then_id(self):
        # 응급은 07:00 접수→11:00 기한, 긴급은 10:00 접수→11:00 기한.
        rows = [make_case('a'),
                make_case('z', urgency='emergency', registered_at=BASE - timedelta(hours=3)),
                make_case('b', urgency='emergency', registered_at=BASE - timedelta(hours=3))]
        self.assertEqual(ids(priority.sort_pending_cases(rows)), ['b', 'z', 'a'])

    def test_registration_sort_uses_registration_deadline_id(self):
        rows = [make_case('b'), make_case('a'), make_case('emergency', urgency='emergency'),
                make_case('old', urgency='routine', registered_at=BASE - timedelta(hours=1))]
        self.assertEqual(ids(priority.sort_pending_cases(rows, 'registered_at')),
                         ['old', 'a', 'b', 'emergency'])

    def test_urgency_sort_uses_target_registration_id(self):
        rows = [make_case('routine', urgency='routine'),
                make_case('emergency', urgency='emergency'), make_case('b'), make_case('a'),
                make_case('old', registered_at=BASE - timedelta(hours=1))]
        self.assertEqual(ids(priority.sort_pending_cases(rows, 'urgency')),
                         ['old', 'a', 'b', 'emergency', 'routine'])

    def test_uncalculable_rows_are_last_in_id_order(self):
        rows = [make_case('bad_b', registered_at=None), make_case('good'),
                make_case('bad_a', urgency='unknown')]
        for mode in SORT_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(ids(priority.sort_pending_cases(rows, mode)),
                                 ['good', 'bad_a', 'bad_b'])

    def test_pending_accepts_only_known_non_done_statuses(self):
        rows = [make_case(status, status=status) for status in config.STATUSES]
        rows += [make_case('unknown', status='unknown'), make_case('missing', status=None)]
        actual = priority.sort_pending_cases(rows)
        self.assertEqual({row['status'] for row in actual}, set(config.STATUSES) - {'done'})

    def test_quality_flags_do_not_change_sort_order(self):
        rows = [make_case('b'), make_case('a')]
        for mode in SORT_MODES:
            before = ids(priority.sort_pending_cases(rows, mode))
            for flags in [(True, False), (False, True)]:
                changed = copy.deepcopy(rows)
                for row, flag in zip(changed, flags):
                    row['flags']['quality_check'] = flag
                with self.subTest(mode=mode, flags=flags):
                    self.assertEqual(ids(priority.sort_pending_cases(changed, mode)), before)

    def test_unsupported_sort_raises_value_error(self):
        with self.assertRaises(ValueError):
            priority.sort_pending_cases([], 'quality')

    def test_completed_latest_first_ties_id_ascending(self):
        rows = [make_case('b', status='done', completed_at=BASE),
                make_case('a', status='done', completed_at=BASE),
                make_case('new', status='done', completed_at=BASE + timedelta(hours=1)),
                make_case('pending')]
        self.assertEqual(ids(priority.sort_completed_cases(rows)), ['new', 'a', 'b'])

    def test_invalid_completed_times_last_in_id_order(self):
        rows = [make_case('c', status='done', completed_at=None),
                make_case('b', status='done', completed_at='bad'),
                make_case('a', status='done', completed_at=BASE.replace(tzinfo=None)),
                make_case('valid', status='done', completed_at=BASE)]
        self.assertEqual(ids(priority.sort_completed_cases(rows)), ['valid', 'a', 'b', 'c'])

    def test_latest_target_setting_applies(self):
        """실제 config 파일을 바꾸지 않고 일시적으로 목표 시간을 변경한다."""
        row = make_case()
        with patch.dict(config.TARGET_TIME, {'urgent': timedelta(hours=2)}):
            self.assertEqual(priority.calculate_due_at(row), BASE + timedelta(hours=2))

    def test_inputs_are_not_modified(self):
        rows = [make_case('b'), make_case('a'), make_case('done', status='done', completed_at=BASE)]
        original = copy.deepcopy(rows)
        for mode in SORT_MODES:
            self.assertIsNot(priority.sort_pending_cases(rows, mode), rows)
        self.assertIsNot(priority.sort_completed_cases(rows), rows)
        priority.calculate_due_at(rows[0])
        priority.is_overdue(rows[0], BASE)
        self.assertEqual(rows, original)
        self.assertNotIn('due_at', rows[0])

    def test_empty_lists(self):
        for mode in SORT_MODES:
            self.assertEqual(priority.sort_pending_cases([], mode), [])
        self.assertEqual(priority.sort_completed_cases([]), [])


if __name__ == '__main__':
    unittest.main()
