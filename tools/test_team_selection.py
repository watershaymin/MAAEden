"""队伍识别、切换保护和原生客户端选项覆盖的回归；不操作游戏。"""

import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from menas_trial import parse_count, read_interface_options
from navigation import Navigator
from team_selection import TEAM_CENTERS, marker_team, parse_team, read_team, select_team


class TeamSelection(unittest.TestCase):
    def test_valid_teams_and_invalid_parameters(self):
        for team in range(11):
            self.assertEqual(parse_team(team), team)
            self.assertEqual(parse_team(str(team)), team)
        for team in (None, True, False, -1, 11, 1.0, '01', '1.0', '', [], {}):
            with self.subTest(team=team), self.assertRaises(ValueError):
                parse_team(team)

    def test_marker_must_be_unique_and_aligned(self):
        def result(*boxes):
            return SimpleNamespace(filtered_results=[SimpleNamespace(box=b) for b in boxes])
        for team, x in enumerate(TEAM_CENTERS, 1):
            for y in (560, 567):
                self.assertEqual(marker_team(result([x - 12, y - 12, 25, 25])), team)
        self.assertIsNone(marker_team(None))
        self.assertIsNone(marker_team(result([496, 548, 25, 25], [525, 548, 25, 25])))
        self.assertIsNone(marker_team(result([480, 548, 25, 25])))
        self.assertIsNone(marker_team(result([496, 500, 25, 25])))

    def test_keep_current_sends_no_input_or_recognition(self):
        nav = Mock()
        select_team(nav, 0, 'page')
        self.assertEqual(nav.mock_calls, [])

    def test_same_team_sends_no_click_and_wraps_both_directions(self):
        for readings, target, direction in [([9, 10, 1, 2], 2, 'Right'),
                                             ([2, 1, 10, 9], 9, 'Left'), ([4], 4, None)]:
            with self.subTest(target=target), patch('team_selection.read_team', side_effect=readings) as read:
                nav = Mock()
                select_team(nav, target, 'page')
                self.assertEqual(read.call_count, len(readings))
                self.assertEqual([call.args[0] for call in nav.action.call_args_list],
                                 ['TeamSelection' + direction] * (len(readings) - 1) if direction else [])

    def test_no_displacement_or_wrong_displacement_does_not_retry_click(self):
        for observed in (2, 4):
            with patch('team_selection.read_team', side_effect=[2, observed]):
                nav = Mock()
                with self.assertRaisesRegex(RuntimeError, '队伍切换未确认'):
                    select_team(nav, 5, 'page')
                nav.action.assert_called_once_with('TeamSelectionRight')

    def test_unrecognized_page_times_out_without_input(self):
        nav = Mock(deadline=100)
        nav.reco.return_value = None
        with patch('team_selection.time.monotonic', side_effect=[0, 0, 9]), patch('team_selection.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '无法确认入场队伍页'):
                read_team(nav, 'page')
        nav.action.assert_not_called()

    def test_transient_marker_needs_two_consecutive_confirmations(self):
        nav = Mock(deadline=time.monotonic() + 20)
        with patch('team_selection.marker_team', side_effect=[1, None, 2, 2]), patch('team_selection.time.sleep'):
            self.assertEqual(read_team(nav, 'page'), 2)
        self.assertEqual(nav.frame.call_count, 4)

    def test_stop_and_deadline_prevent_input(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=True), run_action=Mock())
        nav = Navigator(context)
        with self.assertRaisesRegex(RuntimeError, '用户停止'):
            select_team(nav, 2, 'page')
        context.tasker.stopping = False
        nav.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError):
            select_team(nav, 2, 'page')
        context.run_action.assert_not_called()


class NoInputController(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'team-options-and-fixtures'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720, 1280, 3), dtype=np.uint8)
    def click(self, *args): raise AssertionError('离线测试不允许发送输入')


class CaptureMenasOptions(CustomAction):
    def run(self, context, argv):
        try:
            params = read_interface_options(context, json.loads(argv.custom_action_param))
            self.result = (parse_count(params), parse_team(params.get('team', 0)))
            return True
        except Exception as exc:
            self.error = exc
            return False


class InspectMarkers(CustomAction):
    def run(self, context, argv):
        try:
            with np.load(ROOT / 'tools/fixtures/team_selection.npz', allow_pickle=False) as fixtures:
                for key in fixtures.files:
                    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                    frame[544:582, 490:790] = cv2.imdecode(fixtures[key], cv2.IMREAD_COLOR)
                    result = context.run_recognition('TeamSelectionMarker', frame)
                    self.result[key] = marker_team(result if result and result.hit else None)
            return True
        except Exception as exc:
            self.error = exc
            return False


class NativeTeams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Toolkit.init_option(ROOT / 'debug/team-selection/native-tests')
        cls.interface = json.loads((ROOT / 'assets/interface.json').read_text(encoding='utf-8'))
        cls.options = CaptureMenasOptions()
        cls.markers = InspectMarkers()
        cls.resource = Resource()
        assert cls.resource.register_custom_action('CaptureMenasTeams', cls.options)
        assert cls.resource.register_custom_action('InspectTeamMarkers', cls.markers)
        assert cls.resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
        cls.controller = NoInputController()
        assert cls.controller.post_connection().wait().succeeded
        cls.tasker = Tasker()
        assert cls.tasker.bind(cls.resource, cls.controller)

    def options_result(self, overrides):
        self.options.result = self.options.error = None
        job = self.tasker.post_task('MenasTrial', [*overrides, {
            'MenasTrial': {'custom_action': 'CaptureMenasTeams', 'next': [], 'post_delay': 0},
        }]).wait()
        self.assertIsNone(self.options.error)
        self.assertTrue(job.succeeded)
        return self.options.result

    def test_count_and_team_preserved_in_either_override_order(self):
        options = self.interface['option']
        count = json.loads(json.dumps(options['MenasTrialCount']['pipeline_override']).replace('"{count}"', '3'))
        team = options['MenasTrialTeam']['cases'][10]['pipeline_override']
        self.assertEqual(self.options_result([count, team]), (3, 10))
        self.assertEqual(self.options_result([team, count]), (3, 10))
        self.assertEqual(self.options_result([]), (0, 0))

    def test_old_cli_parameters_ignore_gui_options(self):
        team = self.interface['option']['MenasTrialTeam']['cases'][10]['pipeline_override']
        self.assertEqual(self.options_result([team, {'MenasTrial': {'custom_action_param': {'count': 1}}}]), (1, 0))
        self.assertEqual(self.options_result([team, {'MenasTrial': {'custom_action_param': {'count': 2, 'team': 3}}}]), (2, 3))

    def test_all_three_options_default_to_current_and_cover_ten_slots(self):
        for name in ('DungeonRedTeam', 'DungeonGreenTeam', 'MenasTrialTeam'):
            option = self.interface['option'][name]
            self.assertEqual(option['default_case'], 'current')
            self.assertEqual([case['name'] for case in option['cases']], ['current', *map(str, range(1, 11))])

    def test_real_red_green_and_menas_marker_samples_and_negatives(self):
        self.markers.result, self.markers.error = {}, None
        job = self.tasker.post_task('InspectTeamMarkers', {
            'InspectTeamMarkers': {'action': 'Custom', 'custom_action': 'InspectTeamMarkers', 'post_delay': 0},
        }).wait()
        self.assertIsNone(self.markers.error)
        self.assertTrue(job.succeeded)
        expected = {f'{page}_{team}': team for page in ('red', 'green', 'menas') for team in range(1, 11)}
        expected.update(no_marker=None, double_marker=None, wrong_position=None)
        self.assertEqual(self.markers.result, expected)


if __name__ == '__main__':
    unittest.main()
