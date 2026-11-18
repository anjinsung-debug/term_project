import runpy
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from pandas.io.formats.style import Styler

import pacs

PAGE = Path(__file__).resolve().parents[1] / 'pages' / 'worklist.py'
BASE = datetime(2000, 1, 1, tzinfo=timezone.utc)


class Stopped(Exception):
    pass


def row(case_id='a', **changes):
    data = dict(id=case_id, mock_id=case_id, status='received', urgency='urgent',
                registered_at=BASE, completed_at=None, flags={})
    data.update(changes)
    return data


def table_records(value):
    """st.dataframe 한 번에 전달된 표를 행 딕셔너리 목록으로 읽는다."""
    if isinstance(value, Styler):
        value = value.data
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise AssertionError(f"예상하지 않은 표 자료형 또는 행 구조: {type(value).__name__}")


def render(rows, mode='due_at', role='manager', urgency=None, query='', denied=False):
    st = MagicMock()
    # 각 표에서 품질 열에 실제로 연결한 도움말을 확인할 수 있게 한다.
    st.column_config.TextColumn.side_effect = lambda label, **kwargs: dict(label=label, **kwargs)
    st.text_input.return_value = query
    st.selectbox.side_effect = [urgency, mode]
    st.tabs.return_value = [MagicMock(), MagicMock()]
    st.stop.side_effect = Stopped
    user = dict(uid='test-user', role=role)
    auth = types.ModuleType('pacs.auth')
    auth.require_login = MagicMock(return_value=user)
    auth.require_role = MagicMock()
    cases = types.ModuleType('pacs.cases')
    cases.CaseError = type('CaseError', (Exception,), {})
    cases.list_cases = MagicMock(return_value=rows)
    if denied:
        cases.list_cases.side_effect = PermissionError('권한 없음')
    def format_kst(value, *, with_seconds=False):
        return value.astimezone(timezone(timedelta(hours=9))).strftime(
            '%Y-%m-%d %H:%M:%S' if with_seconds else '%Y-%m-%d %H:%M')
    cases.format_kst = MagicMock(side_effect=format_kst)
    with patch.dict(sys.modules, {'streamlit': st, 'pacs.auth': auth, 'pacs.cases': cases}), \
         patch.object(pacs, 'auth', auth, create=True), patch.object(pacs, 'cases', cases, create=True):
        try:
            runpy.run_path(str(PAGE))
        except Stopped:
            pass
    # 표 하나당 한 번만 변환한다. 모든 표를 합치거나 행을 한 번 더 감싸지 않는다.
    tables = [
        table_records(call.args[0] if call.args else call.kwargs["data"])
        for call in st.dataframe.call_args_list
    ]
    return st, cases, tables


class WorklistTests(unittest.TestCase):
    def test_roles_and_filters_forwarded(self):
        for role in ('registrar', 'reviewer', 'manager'):
            with self.subTest(role=role):
                _, cases, _ = render([], role=role, urgency='urgent', query='MOCK')
                cases.list_cases.assert_called_once_with(
                    {'uid': 'test-user', 'role': role}, urgency='urgent', mock_id_query='MOCK')

    def test_empty_lists(self):
        st, _, tables = render([])
        self.assertEqual(tables, [])
        st.tabs.assert_called_once_with(['미완료 (0)', '완료 (0)'])

    def test_selected_sort_and_column_order(self):
        data = [row('new'), row('old', urgency='routine', registered_at=BASE-timedelta(hours=24))]
        expected = {
            'due_at': (['old', 'new'], ['모의 케이스 ID', '기한', '긴급도', '접수 시각']),
            'registered_at': (['old', 'new'], ['모의 케이스 ID', '접수 시각', '기한', '긴급도']),
            'urgency': (['new', 'old'], ['모의 케이스 ID', '긴급도', '기한', '접수 시각']),
        }
        for mode, (order, columns) in expected.items():
            with self.subTest(mode=mode):
                _, _, tables = render(data, mode)
                self.assertEqual([r['모의 케이스 ID'] for r in tables[0]], order)
                self.assertEqual(list(tables[0][0])[:4], columns)

    def test_uncalculable_is_last_and_not_within_deadline(self):
        for mode in ('due_at', 'registered_at', 'urgency'):
            with self.subTest(mode=mode):
                _, _, tables = render([row('bad', registered_at='bad'), row('good')], mode)
                self.assertEqual(tables[0][-1]['모의 케이스 ID'], 'bad')
                self.assertEqual(tables[0][-1]['기한 상태'], '기한 계산 불가')
                self.assertEqual(tables[0][-1]['기한'], '-')
                self.assertEqual(tables[0][-1]['접수 시각'], '-')

    def test_overdue_and_future(self):
        now = datetime.now(timezone.utc)
        _, _, tables = render([row('past', registered_at=now - timedelta(days=2)),
                               row('future', registered_at=now)])
        self.assertEqual([r['기한 상태'] for r in tables[0]], ['기한 초과', '기한 내'])

    def test_seconds_enabled(self):
        _, cases, tables = render([row(registered_at=BASE.replace(second=12))])
        self.assertTrue(tables[0][0]['접수 시각'].endswith(':12'))
        self.assertTrue(all(call.kwargs.get('with_seconds') is True for call in cases.format_kst.call_args_list))

    def test_quality_only_when_flagged(self):
        _, _, tables = render([row('a', flags={'quality_check': True}), row('b', flags=None)])
        self.assertEqual([r['품질'] for r in tables[0]], ['점검 필요', ''])
        self.assertEqual([r['긴급도'] for r in tables[0]], ['긴급', '긴급'])

    def test_completed_sort_and_invalid_times(self):
        data = [row('b', status='done', completed_at=BASE), row('a', status='done', completed_at=BASE),
                row('new', status='done', completed_at=BASE+timedelta(hours=1)),
                row('bad', status='done', completed_at='bad')]
        st, _, tables = render(data)
        self.assertEqual([r['모의 케이스 ID'] for r in tables[0]], ['new', 'a', 'b', 'bad'])
        self.assertEqual(tables[0][-1]['완료 시각'], '-')
        self.assertTrue(st.warning.called)

    def test_unknown_status_is_visible_separately(self):
        _, _, tables = render([row('bad', status='unknown')])
        self.assertEqual(tables[0][0]['케이스 ID'], 'bad')
        self.assertIn('확인 사유', tables[0][0])

    def test_pending_styles_for_three_urgencies(self):
        rows = [row('a'), row('b', urgency='emergency'), row('c', urgency='routine')]
        st, _, tables = render(rows, mode='urgency')
        styled = st.dataframe.call_args.args[0]
        self.assertIsInstance(styled, Styler)
        self.assertEqual([r['긴급도'] for r in tables[0]], ['긴급', '응급', '일반'])

        # pandas가 실제로 생성한 CSS에서 해당 행·긴급도 열에 적용된 배경색 확인.
        css = styled.to_html().split('</style>', 1)[0].lower()
        column = styled.data.columns.get_loc('긴급도')
        for index, color in enumerate(('#fee2e2', '#ffedd5', '#dcfce7')):
            with self.subTest(color=color):
                self.assertRegex(css, rf'_row{index}_col{column}\s*\{{[^}}]*background-color:\s*{color}')

    def test_quality_help_on_pending_and_completed_tables(self):
        st, _, tables = render([row('open'), row('closed', status='done', completed_at=BASE)])
        self.assertEqual([table[0]['모의 케이스 ID'] for table in tables], ['open', 'closed'])
        for call in st.dataframe.call_args_list:
            help_text = call.kwargs['column_config']['품질']['help']
            self.assertIn('빈칸', help_text)
            self.assertIn('품질 통과를 보장하지 않습니다', help_text)

    def test_permission_denied_stops_before_table(self):
        st, _, tables = render([], denied=True)
        self.assertFalse(tables)
        st.error.assert_called_once_with('권한 없음')
        st.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
