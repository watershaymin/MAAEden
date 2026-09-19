"""小地图时序定位、错误匹配和停止/到达保护回归。"""

import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from minimap_navigation import (LocalizationLost, MAP_ROI, MINI_ROI, MapAtlas,
                                MiniMapNavigator, Observation, parse_route, pulse_position)
from navigation import NavigationMiniMapRoute


def sequence(two=False, frozen=False, occluded=False):
    frames = []
    for radius in [5, 6, 7, 8, 9, 8, 7, 6]:
        f = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillConvexPoly(f, np.array([[1090, 75], [1100, 85], [1090, 95], [1080, 85]]), (30, 180, 230))
        for center in [(1140, 95)] + ([(1200, 120)] if two else []):
            cv2.circle(f, center, 7 if frozen else radius, (20, 180, 240), 2, cv2.LINE_AA)
        if occluded:
            # 静止图例与环外沿相接，但圆心仍由多帧可见弧线约束。
            cv2.rectangle(f, (1147, 84), (1160, 100), (30, 180, 230), -1)
        frames.append(f)
    return frames


class PulseTests(unittest.TestCase):
    def test_breathing_radius_and_static_yellow_quest(self):
        self.assertLess(math.dist(pulse_position(sequence()), (1140, 95)), 1)

    def test_static_yellow_ring_is_not_a_player(self):
        with self.assertRaises(LocalizationLost):
            pulse_position(sequence(frozen=True))

    def test_two_pulsing_candidates_are_ambiguous(self):
        with self.assertRaises(LocalizationLost):
            pulse_position(sequence(two=True))

    def test_touching_static_icon_does_not_move_the_center(self):
        self.assertLess(math.dist(pulse_position(sequence(occluded=True)), (1140, 95)), 2)

    def test_blank_or_insufficient_frames_are_rejected(self):
        for frames in [sequence()[:3], [np.zeros((720, 1280, 3), np.uint8)] * 8]:
            with self.assertRaises(LocalizationLost):
                pulse_position(frames)


class ControlTests(unittest.TestCase):
    def session(self):
        runner = Mock()
        runner.deadline = time.monotonic() + 60
        runner.navigation_interrupted.return_value = False
        runner.reco.return_value = None
        runner.world.return_value = np.zeros((720, 1280, 3), np.uint8)
        runner.frame.return_value = runner.world.return_value
        session = MiniMapNavigator(runner, '绿之村巴尔沃基')
        session.last_calibration = time.monotonic()
        session.atlas = Mock()
        session.road = Mock()
        session.position = (600, 339)
        session.burst = Mock(return_value=sequence())
        return session

    def test_parameter_validation_happens_before_control(self):
        good = {'map_name': '绿之村巴尔沃基', 'waypoints': [[600, 254]]}
        self.assertEqual(parse_route(good)[2], 60)
        for params in [None, {}, dict(good, waypoints=[[True, 300]]),
                       dict(good, waypoints=[[float('nan'), 300]]), dict(good, max_steps=True),
                       dict(good, waypoints=[[400, 900]])]:
            with self.assertRaises(ValueError):
                parse_route(params)
        with patch('cat_diary.CatDiaryRunner') as runner:
            self.assertFalse(NavigationMiniMapRoute().run(None, SimpleNamespace(custom_action_param='{}')))
            runner.assert_not_called()

    def test_good_minimap_observation_does_not_open_map(self):
        session = self.session()
        session.atlas.observe.return_value = Observation((625, 339), 20, .5)
        self.assertEqual(session.locate('right'), (625, 339))
        session.runner.action.assert_not_called()
        self.assertEqual(session.mini_updates, 1)

    def test_lost_observation_has_bounded_recalibration(self):
        session = self.session()
        session.atlas.observe.side_effect = LocalizationLost('ambiguous')
        session.calibrate = Mock(return_value=(600, 339))
        for _ in range(3):
            session.locate()
        with self.assertRaises(LocalizationLost):
            session.locate()
        self.assertEqual(session.calibrate.call_count, 3)
        session.runner.action.assert_not_called()

    def test_wrong_map_stays_open_and_sends_no_swipe(self):
        session = self.session()
        session.wait_map = Mock()
        session.runner.reco.return_value = True
        session.runner.text.return_value = '其他地图'
        with self.assertRaisesRegex(LocalizationLost, '地图不符'):
            session.calibrate()
        self.assertEqual([c.args[0] for c in session.runner.action.call_args_list], ['NavigationToggleLocalMap'])

    def test_stop_propagates_without_another_swipe(self):
        session = self.session()
        session.calibrate = Mock()
        session.runner.check.side_effect = RuntimeError('用户停止')
        with self.assertRaisesRegex(RuntimeError, '用户停止'):
            session.follow([[800, 339]])
        session.runner.action.assert_not_called()

    def test_no_displacement_stops_after_three_steps(self):
        session = self.session()
        session.calibrate = Mock()
        session.locate = Mock()
        session.road.step.return_value = ('right', 600)
        with self.assertRaisesRegex(RuntimeError, '连续三步'):
            session.follow([[800, 339]])
        self.assertEqual(session.runner.action.call_count, 3)

    def test_unstoppable_connector_target_stops_after_observed_crossing(self):
        session = self.session()
        session.position = (705, 461)
        session.calibrate = Mock()
        session.road.step.return_value = ('up', 600)
        def located(*args):
            session.position = (705, 359)
        session.locate = located
        with self.assertRaisesRegex(RuntimeError, '不可停留'):
            session.follow([[705, 390]])
        self.assertEqual(session.runner.action.call_count, 1)

    def test_road_projection_is_not_arrival(self):
        session = self.session()
        session.calibrate = Mock()
        session.road.step.return_value = None
        with self.assertRaisesRegex(RuntimeError, '道路投影'):
            session.follow([[620, 339], [600, 339]])
        session.runner.action.assert_not_called()

    def test_final_success_requires_full_map_position_at_target(self):
        session = self.session()
        session.position = (600, 339)
        session.last_map_position = (612, 339)
        session.calibrate = Mock()
        with self.assertRaisesRegex(RuntimeError, '终点整图复核未到达'):
            session.follow([[600, 339]])
        session.runner.action.assert_not_called()

    def test_time_limit_uses_existing_runner_checks(self):
        from cat_diary import CatDiaryRunner
        runner = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        runner.deadline = time.monotonic() - 1
        session = MiniMapNavigator(runner, 'test')
        with self.assertRaisesRegex(RuntimeError, '运行时间'):
            session.burst()


class LiveReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = np.load(Path(__file__).parent / 'fixtures/minimap_navigation.npz')

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def full_frame(self, patch, roi):
        f = np.zeros((720, 1280, 3), np.uint8)
        x, y, w, h = roi
        f[y:y + h, x:x + w] = patch
        return f

    def atlas(self, name):
        base = self.full_frame(self.fixture[name + '_base'], MAP_ROI)
        large = self.full_frame(self.fixture[name + '_map'], MAP_ROI)
        return MapAtlas(base, [large], name, self.fixture[name + '_position'])

    def test_live_quest_overlap_does_not_select_exclamation_hole(self):
        for name, roi, expected in [('overlap_mini', MINI_ROI, (1109, 95)),
                                     ('overlap_large', MAP_ROI, (579, 359))]:
            frames = [self.full_frame(f, self.fixture[name + '_roi']) for f in self.fixture[name]]
            with self.subTest(name=name):
                self.assertLess(math.dist(pulse_position(frames, roi), expected), 3)

    def test_live_exit_overlap_keeps_stable_inner_ring_center(self):
        # 星之塔入口：外圈与出口箭头重叠，Hough 圆心偏到 (1168.5, 119.5)。
        # 独立整图与静态地图变换、人工检查均支持实际内孔 (1166, 116)。
        frames = [self.full_frame(f, MINI_ROI) for f in self.fixture['star_exit_overlap']]
        self.assertLess(math.dist(pulse_position(frames), (1166, 116)), 1.5)

    def test_live_minimap_registration_matches_independent_full_map(self):
        for name in ('baruoki', 'konium'):
            atlas = self.atlas(name)
            for patch_image in self.fixture[name + '_mini']:
                f = self.full_frame(patch_image, MINI_ROI)
                result = atlas.register(f, self.fixture[name + '_mini_position'])
                with self.subTest(name=name):
                    self.assertLess(math.dist(result.position, self.fixture[name + '_position']), 3)
                    self.assertGreaterEqual(result.inliers, 8)

    def test_other_map_cannot_reuse_current_atlas(self):
        atlas = self.atlas('baruoki')
        f = self.full_frame(self.fixture['konium_mini'][-1], MINI_ROI)
        with self.assertRaises(LocalizationLost):
            atlas.register(f, self.fixture['konium_mini_position'])

    def test_far_pulse_candidate_is_rejected_by_observed_map_coordinates(self):
        atlas = self.atlas('baruoki')
        f = self.full_frame(self.fixture['baruoki_mini'][-1], MINI_ROI)
        with patch('minimap_navigation.pulse_candidates', return_value=[(1090, 90), (1140, 90)]), \
                patch.object(atlas, 'register', side_effect=[Observation((400, 400), 20, 1)] * 2
                             + [Observation((625, 339), 20, 1)] * 2):
            self.assertEqual(atlas.observe([f, f], (600, 339), 'right').position, (625, 339))


class SparseMapReplayTests(unittest.TestCase):
    full_frame = LiveReplayTests.full_frame
    atlas = LiveReplayTests.atlas
    tearDownClass = classmethod(LiveReplayTests.tearDownClass.__func__)
    @classmethod
    def setUpClass(cls):
        cls.fixture = np.load(Path(__file__).parent / 'fixtures/minimap_sparse.npz')

    def test_sparse_live_maps_match_independent_full_map(self):
        for name in ('cat_04', 'cat_10', 'cat_38', 'cat_48', 'cat_50', 'fantasy', 'iskariot'):
            with self.subTest(name=name):
                atlas = self.atlas(name)
                frames = [self.full_frame(f, MINI_ROI) for f in self.fixture[name+'_mini']]
                with patch.object(atlas, 'register_features', side_effect=LocalizationLost('测试轮廓分支')):
                    result = atlas.observe(frames, self.fixture[name+'_position'])
                self.assertEqual(result.source, 'contour')
                self.assertLess(math.dist(result.position, self.fixture[name+'_position']), 3)
                if name == 'cat_48':
                    self.assertGreater(atlas.contours.scale, .65)
                    self.assertLess(atlas.contours.scale, .78)

    def test_feature_scale_is_learned_from_independent_full_map(self):
        atlas = self.atlas('cat_48')
        frames = [self.full_frame(f, MINI_ROI) for f in self.fixture['cat_48_mini']]
        result = atlas.observe(frames, self.fixture['cat_48_position'])
        self.assertLess(math.dist(result.position, self.fixture['cat_48_position']), 3)
        self.assertGreater(atlas.feature_scale, .65)
        self.assertLess(atlas.feature_scale, .78)

    def test_repeated_road_geometry_is_rejected(self):
        from minimap_geometry import ContourAtlas
        base = np.zeros((720, 1280, 3), np.uint8)
        full = base.copy()
        mini = np.zeros((155, 242, 3), np.uint8)
        cv2.rectangle(mini, (35, 45), (190, 57), (200, 200, 200), -1)
        cv2.rectangle(mini, (160, 45), (173, 120), (200, 200, 200), -1)
        doubled = cv2.resize(mini, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        # 两个完全相同且同时可见的路段：锚点不能替代唯一性证据。
        full[140:450, 170:654] = doubled
        full[140:450, 630:1114] |= doubled
        atlas = ContourAtlas(base, full, (250, 160))
        with self.assertRaises(ValueError):
            atlas.register(mini, (10, 10))

    def test_empty_minimap_is_rejected(self):
        atlas = self.atlas('cat_04')
        with self.assertRaises(LocalizationLost):
            atlas.register(np.zeros((720, 1280, 3), np.uint8), (1100, 95))

    def test_local_animation_does_not_mask_global_fade(self):
        from minimap_geometry import background_stable
        previous = np.full((48,160,3), 100, np.float32)
        animation = np.random.default_rng(42).uniform(-3,3, previous.shape)
        self.assertTrue(background_stable(previous, previous+animation))
        self.assertFalse(background_stable(previous, previous+animation+5))
        self.assertFalse(background_stable(previous, previous+animation*5))


class OccludedRoadTests(unittest.TestCase):
    def road(self):
        from cat_diary import RoadMap
        base = np.zeros((720, 1280, 3), np.uint8)
        full = base.copy()
        cv2.line(full, (480, 250), (480, 380), (180, 180, 180), 24)
        cv2.line(full, (480, 380), (650, 380), (180, 180, 180), 24)
        boxes = [[450, 350, 80, 64]]
        return RoadMap(base, full, boxes, (515, 380)), boxes

    def test_observed_corner_hidden_by_player_is_connected(self):
        from minimap_roads import complete_corners
        road, boxes = self.road()
        with self.assertRaises(RuntimeError):
            road.path((600, 380), (480, 280))
        complete_corners(road, boxes, (515, 380))
        self.assertGreater(len(road.path((600, 380), (480, 280))), 20)

    def test_unidentified_gap_is_never_bridged(self):
        from minimap_roads import complete_corners
        road, _ = self.road()
        complete_corners(road, [], (515, 380))
        with self.assertRaises(RuntimeError):
            road.path((600, 380), (480, 280))


class RepairSequenceTests(unittest.TestCase):
    full_frame = LiveReplayTests.full_frame
    atlas = LiveReplayTests.atlas
    tearDownClass = classmethod(LiveReplayTests.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        cls.fixture = np.load(Path(__file__).parent / 'fixtures/minimap_repair.npz')

    def test_feature_to_contour_handoff_after_movement(self):
        for name in ('industrial_handoff', 'industrial_mixed'):
            with self.subTest(name=name):
                atlas = self.atlas(name)
                first = [self.full_frame(f, MINI_ROI) for f in self.fixture[name+'_mini']]
                atlas.observe(first, self.fixture[name+'_position'])
                moved = [self.full_frame(f, MINI_ROI) for f in self.fixture[name+'_moved']]
                result = atlas.observe(moved)
                self.assertLess(math.dist(result.position, self.fixture[name+'_measured']), 3)
                self.assertIn(result.source, ('contour', 'hybrid'))

    def test_both_backgrounds_remove_pose_ghost_from_tiny_map(self):
        name = 'tiny_background'
        base = self.full_frame(np.maximum(self.fixture[name+'_before'], self.fixture[name+'_base']), MAP_ROI)
        full = self.full_frame(self.fixture[name+'_map'], MAP_ROI)
        atlas = MapAtlas(base, [full], name, self.fixture[name+'_position'])
        frames = [self.full_frame(f, MINI_ROI) for f in self.fixture[name+'_mini']]
        result = atlas.observe(frames, self.fixture[name+'_position'])
        self.assertLess(math.dist(result.position, self.fixture[name+'_position']), 3)


class TransitionTests(unittest.TestCase):
    def test_verified_landings_do_not_create_a_walkable_connector(self):
        from cat_diary import RoadMap
        from minimap_transitions import add_landings, load_transitions
        road = RoadMap.from_segments([])
        add_landings(road, load_transitions('背叛之地伊丝卡莉欧忒'))
        road.nearest((640,439))
        road.nearest((640,282))
        with self.assertRaises(RuntimeError):
            road.path((640,439), (640,282))

    def test_discrete_link_only_connects_confirmed_endpoints(self):
        from cat_diary import RoadMap
        from minimap_transitions import choose_transition, load_transitions
        road = RoadMap.from_segments([[590,439,690,439], [617,282,663,282]])
        transitions = load_transitions('背叛之地伊丝卡莉欧忒')
        self.assertIsNotNone(choose_transition(transitions, set(), road, (640,439), (640,282)))
        self.assertIsNone(choose_transition(transitions, {0}, road, (640,439), (640,282)))
        self.assertIsNone(choose_transition(transitions, set(), road, (800,439), (640,282)))
        self.assertEqual(load_transitions('其他地图'), [])

    def test_missing_button_never_clicks(self):
        from minimap_transitions import interact
        runner = Mock()
        runner.reco.return_value = None
        with self.assertRaisesRegex(RuntimeError, '未确认交互按钮'):
            interact(runner, {'roi': [580,220,120,110]})
        runner.click.assert_not_called()

    def test_interaction_without_observed_transition_is_bounded(self):
        from minimap_transitions import interact
        runner = Mock()
        with patch('minimap_transitions.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '未进入过渡状态'):
                interact(runner, {'roi': [580,220,120,110]})
        runner.click.assert_called_once()
        self.assertEqual(runner.frame.call_count, 15)

    def test_wrong_observed_landing_cannot_complete(self):
        session = ControlTests().session()
        session.position = (640,439)
        session.transitions = [{'from': [640,439], 'to': [640,282], 'roi': [580,220,120,110]}]
        session.road.step.side_effect = RuntimeError('断续路径')
        def calibrated(*args, **kwargs):
            if session.interactions:
                session.position = (700,300)
        session.calibrate = calibrated
        with patch('minimap_transitions.interact') as clicked:
            with self.assertRaisesRegex(RuntimeError, '实际落点'):
                session.follow([[640,282]])
        clicked.assert_called_once()
        session.runner.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
