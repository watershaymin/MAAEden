"""默认任务接入、会话失效、战斗恢复与移动羽毛的时效边界。"""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from navigation import Navigator
from cat_diary import CatDiaryRunner
from monthly_trial import MonthlyNavigator
from minimap_navigation import (MiniMapNavigator, NavigationInterrupted, LocalizationLost,
                                Observation, project_point, map_offset)


class SessionTests(unittest.TestCase):
    def runner(self, cls=Navigator):
        return cls(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))

    def test_same_map_reuses_session_and_observes_direction(self):
        nav = self.runner()
        with patch('minimap_navigation.MiniMapNavigator') as factory:
            session = factory.return_value
            session.atlas = None
            nav.position('巴尔沃基')
            session.atlas, session.map_name = object(), '绿之村巴尔沃基'
            nav.navigation_movement = 'left'
            nav.position('巴尔沃基')
            session.calibrate.assert_called_once_with(audit=False)
            session.locate.assert_called_once_with('left')
            self.assertIsNone(nav.navigation_movement)
            factory.assert_called_once()

    def test_unspecified_initial_map_locks_name_without_rebuilding(self):
        nav = self.runner()
        with patch('minimap_navigation.MiniMapNavigator') as factory:
            session = factory.return_value
            session.atlas = None
            nav.position()
            session.atlas, session.map_name = object(), '绿之村巴尔沃基'
            nav.position('绿之村巴尔沃基')
            factory.assert_called_once()

    def test_same_title_different_floor_road_rebuilds(self):
        nav = self.runner()
        with patch('minimap_navigation.MiniMapNavigator') as factory:
            nav.localize(('研究中心',), '下层')
            nav.localize(('研究中心',), '上层')
            self.assertEqual(factory.call_count, 2)

    def test_explicit_reset_clears_all_navigation_state(self):
        nav = self.runner()
        nav.navigation_session = object()
        nav.navigation_key = ('old',)
        nav.navigation_movement = 'left'
        nav.reset_navigation()
        self.assertIsNone(nav.navigation_session)
        self.assertIsNone(nav.navigation_key)
        self.assertIsNone(nav.navigation_movement)

    def test_initial_aliases_then_exact_title_lock(self):
        session = MiniMapNavigator(self.runner(), '月影森林', exact=False)
        self.assertTrue(session.accepts_name('月影森林入口'))
        self.assertFalse(session.accepts_name('其他森林'))
        session.atlas, session.map_name = object(), '月影森林入口'
        self.assertFalse(session.accepts_name('月影森林深处'))
        floor = MiniMapNavigator(self.runner(), '时之塔1楼')
        self.assertFalse(floor.accepts_name('时之塔2楼'))

    def test_stop_prevents_creating_session_or_control(self):
        nav = self.runner()
        nav.context.tasker.stopping = True
        with patch('minimap_navigation.MiniMapNavigator') as factory:
            with self.assertRaisesRegex(RuntimeError, '停止'):
                nav.position('地图')
            factory.assert_not_called()

    def test_monthly_interruption_uses_original_counter_and_world(self):
        nav = self.runner(MonthlyNavigator)
        def recovered():
            nav.counter.observe('rewards')
            nav.counter.observe('world')
        nav.world = Mock(side_effect=recovered)
        first = Mock(atlas=None)
        first.calibrate.side_effect = NavigationInterrupted('battle')
        second = Mock(atlas=None, map_name='魔物巢穴', position=(711, 402))
        with patch('minimap_navigation.MiniMapNavigator', side_effect=[first, second]) as factory:
            self.assertEqual(nav.position('魔物巢穴'), ('魔物巢穴', (711, 402)))
            self.assertEqual(nav.counter.wins, 1)
            self.assertTrue(all(call.args[0] is nav for call in factory.call_args_list))
            nav.world.assert_called_once()

    def test_repeated_battle_interruption_is_bounded(self):
        nav = self.runner(MonthlyNavigator)
        nav.world = Mock()
        session = Mock(atlas=None)
        session.calibrate.side_effect = NavigationInterrupted('battle')
        with patch('minimap_navigation.MiniMapNavigator', return_value=session):
            with self.assertRaisesRegex(RuntimeError, '5 次'):
                nav.position('魔物巢穴')
        self.assertEqual(nav.world.call_count, 5)

    def test_battle_preserves_completed_atlas_but_resamples_position(self):
        nav = self.runner(MonthlyNavigator)
        nav.world = Mock()
        session = Mock(atlas=object(), map_name='魔物巢穴', position=(675, 402))
        session.locate.side_effect = [NavigationInterrupted('battle'), (675, 402)]
        with patch('minimap_navigation.MiniMapNavigator', return_value=session) as factory:
            nav.position('魔物巢穴')
            factory.assert_called_once()
        self.assertEqual(session.locate.call_count, 2)
        session.calibrate.assert_not_called()
        nav.world.assert_called_once()

    def test_burst_detects_battle_before_processing_map(self):
        nav = self.runner(MonthlyNavigator)
        nav.frame = Mock(return_value={'MonthlyRewards'})
        nav.reco = lambda node, frame: node in frame
        session = MiniMapNavigator(nav, '魔物巢穴')
        with self.assertRaises(NavigationInterrupted):
            session.burst()
        nav.frame.assert_called_once()

    def test_arrival_needs_independent_map_observation(self):
        nav = self.runner()
        nav.navigation_key = (('地图',), None, True)
        nav.navigation_session = Mock()
        nav.localize = Mock(return_value=Mock(last_map_position=(614, 300), position=(600, 300)))
        with self.assertRaisesRegex(RuntimeError, '未到达'):
            nav.audit_navigation((600, 300), 8)

    def test_cat_diary_uses_session_and_floor_profile(self):
        nav = self.runner(CatDiaryRunner)
        nav.tracking_cat = True
        session = Mock(map_name='研究中心', position=(500, 462), road=object())
        session.cat_targets.return_value = [(560, 462)]
        nav.localize = Mock(return_value=session)
        entry = {'teleport': '研究中心', 'location': '研究中心', 'map_names': ['研究中心'], 'road_map': '上层'}
        result = nav.locate(entry, (480, 462), 'right')
        self.assertEqual(result[:3], ('研究中心', (500, 462), [(560, 462)]))
        nav.localize.assert_called_once_with(('研究中心',), '上层', 'right', exact=True)

    def test_floor_approach_does_not_refresh_nonexistent_cat_targets(self):
        nav = self.runner(CatDiaryRunner)
        session = Mock(map_name='研究中心', position=(500, 462), road=object())
        nav.localize = Mock(return_value=session)
        self.assertEqual(nav.locate({'teleport': '研究中心', 'location': '研究中心'})[2], [])
        session.cat_targets.assert_not_called()

    def test_anchor_offset_and_projection_use_same_coordinates(self):
        nav = self.runner()
        nav.reco = Mock(return_value=SimpleNamespace(box=SimpleNamespace(x=932.5, y=212, w=20, h=20),
                                                    filtered_results=[]))
        offset = map_offset(nav, None, '影之镇纳兹里克')
        self.assertEqual(offset, (0, -13))
        observation = Observation((640, 397), 10, 0, transform=((2, 0, 400), (0, 2, 200)))
        self.assertEqual(project_point(observation, (120, 98.5), offset), (640, 410))
        nav.reco.return_value.box.x += 30
        with self.assertRaises(LocalizationLost):
            map_offset(nav, None, '影之镇纳兹里克')

    def test_periodic_wrong_map_does_not_toggle_a_second_time(self):
        session = MiniMapNavigator(self.runner(), '地图')
        session.runner.world = Mock()
        session.calibrate = Mock(side_effect=LocalizationLost('地图不符'))
        with self.assertRaisesRegex(LocalizationLost, '地图不符'):
            session.locate()
        session.calibrate.assert_called_once()

    def test_final_audit_closes_map_without_rebuilding_at_farming_point(self):
        nav = self.runner()
        nav.world, nav.action = Mock(), Mock()
        nav.reco = Mock(return_value=True)
        nav.text = Mock(return_value='地图')
        session = MiniMapNavigator(nav, '地图')
        session.atlas, session.position = object(), (600, 339)
        session.wait_map = Mock()
        session.burst = Mock(return_value=[np.zeros((720,1280,3), np.uint8)]*10)
        with patch('minimap_navigation.pulse_position', return_value=(601, 339)), \
                patch('minimap_navigation.MapAtlas') as atlas:
            self.assertEqual(session.calibrate(audit=True), (601, 339))
        atlas.assert_not_called()
        self.assertEqual(nav.action.call_count, 2)

    def test_disappeared_map_during_battle_animation_recovers(self):
        nav = self.runner()
        nav.world, nav.action = Mock(), Mock()
        nav.reco = Mock(return_value=None)
        session = MiniMapNavigator(nav, '地图')
        session.wait_map, session.burst = Mock(), Mock(return_value=[object()]*10)
        with self.assertRaises(NavigationInterrupted):
            session.calibrate()
        self.assertEqual(nav.action.call_count, 1)

    def test_stopped_or_changed_scene_is_not_swallowed_as_relocalization(self):
        session = MiniMapNavigator(self.runner(), '地图')
        session.runner.world = Mock()
        session.last_calibration = time.monotonic()
        session.observe_only = Mock(side_effect=RuntimeError('用户停止'))
        session.calibrate = Mock()
        with self.assertRaisesRegex(RuntimeError, '停止'):
            session.locate()
        session.calibrate.assert_not_called()

    def test_sparse_map_fallback_recovers_when_minimap_becomes_available(self):
        nav = self.runner()
        frame = np.zeros((720,1280,3), np.uint8)
        nav.world = Mock(return_value=frame)
        nav.action = Mock()
        nav.text = Mock(return_value='绿之村巴尔沃基')
        nav.reco = lambda node, *args: True if node == 'NavigationLocalMap' else None
        session = MiniMapNavigator(nav, '绿之村巴尔沃基', allow_full_map=True)
        session.wait_map = Mock()
        session.burst = Mock(return_value=[frame]*10)
        atlas = Mock()
        atlas.observe.side_effect = [LocalizationLost('sparse')]*3 + [Observation((600,339), 10, .5)]
        with patch('minimap_navigation.MapAtlas', return_value=atlas), \
                patch('minimap_navigation.pulse_position', return_value=(600,339)), \
                patch('minimap_navigation.time.sleep'):
            for expected in [False, False, True, False]:
                session.calibrate()
                self.assertEqual(session.full_map_mode, expected)

    def test_sparse_mode_uses_fresh_full_map_instead_of_stale_minimap(self):
        session = MiniMapNavigator(self.runner(), '地图', allow_full_map=True)
        session.runner.world = Mock()
        session.full_map_mode = True
        session.calibrate = Mock(return_value=(600,339))
        session.observe_only = Mock()
        self.assertEqual(session.locate('left'), (600,339))
        session.observe_only.assert_not_called()
        session.calibrate.assert_called_once()


class TargetTests(unittest.TestCase):
    def session(self):
        session = MiniMapNavigator(Mock(), '地图')
        session.frames = [object(), object()]
        session.map_frames = [object()]
        session.last_calibration = time.monotonic()-10
        session.target_time = time.monotonic()-5
        session.position = (640, 400)
        session.target_positions = [(800, 400)]
        session.target_source = 'map'
        session.observation = Observation((640, 400), 10, 0, transform=((2, 0, 400), (0, 2, 200)))
        session.calibrate = Mock()
        return session

    def test_two_frames_refresh_moving_target_without_opening_map(self):
        session = self.session()
        with patch('minimap_navigation.feather_points', side_effect=[[(120, 100)], [(122, 100)]]):
            self.assertEqual(session.cat_targets(), [(644, 400)])
        session.calibrate.assert_not_called()
        self.assertEqual(session.target_source, 'minimap')

    def test_one_frame_false_detection_does_not_replace_far_search_point(self):
        session = self.session()
        with patch('minimap_navigation.feather_points', side_effect=[[], [(120, 100)]]):
            self.assertEqual(session.cat_targets(), [(800, 400)])
        session.calibrate.assert_not_called()

    def test_nearby_stale_target_is_reobserved_and_can_disappear(self):
        session = self.session()
        session.target_positions = [(650, 400)]
        with patch('minimap_navigation.feather_points', return_value=[]):
            self.assertEqual(session.cat_targets(), [])
        session.calibrate.assert_called_once()

    def test_lost_visible_target_forces_refresh(self):
        session = self.session()
        session.target_source = 'minimap'
        with patch('minimap_navigation.feather_points', return_value=[]):
            self.assertEqual(session.cat_targets(), [])
        session.calibrate.assert_called_once()

    def test_far_search_point_expires(self):
        session = self.session()
        session.last_calibration -= 30
        session.target_time -= 30
        with patch('minimap_navigation.feather_points', return_value=[]):
            session.cat_targets()
        session.calibrate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
