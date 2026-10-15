"""南门路线的越界、停滞、场景顺序和终点保护。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_cat_diary as helpers
from cat_diary import CatDiaryRunner
from minimap_navigation import MiniMapNavigator, LocalizationLost, NavigationInterrupted


class VermilionTests(unittest.TestCase):
    setUp = helpers.CatDiaryTests.setUp
    runner = helpers.CatDiaryTests.runner

    def route(self, names=(None, None, '红叶街道'), landmarks=((0, 800), (1, 600)), landing=('红叶街道', (640, 117))):
        runner = self.runner()
        road = Mock()
        road.step.return_value = ('left', 600)
        runner.locate = Mock(side_effect=[('辰之国那古萨无', (649,445), [], road),
                                         ('辰之国那古萨无', (678,531), [], road),
                                         (*landing, [], road)])
        runner.crossing_map_name = Mock(side_effect=names)
        runner.world = Mock(side_effect=landmarks)
        nodes = ['CatDiaryNagsham'+s for s in ('Pillar', 'Vine', 'Tree')]
        runner.reco = Mock(side_effect=lambda node, frame: SimpleNamespace(
            best_result=SimpleNamespace(box=[frame[1], 0, 50, 100]))
            if frame is not None and node == nodes[frame[0]] else None)
        runner.action = Mock()
        runner.reset_navigation = Mock()
        return runner

    def test_teleport_dispatches_verified_source(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e['id'] == 'cat_64')
        runner.teleport = Mock()
        runner.walk_nagsham_vermilion = Mock()
        CatDiaryRunner.teleport(runner, entry)
        source = runner.teleport.call_args.args[0]
        self.assertEqual(source['id'], 'cat_65')
        self.assertEqual(entry['map_names'], ['红叶街道'])
        runner.walk_nagsham_vermilion.assert_called_once_with(source, entry)

    def test_route_requires_independent_destination_landing(self):
        runner = self.route()
        runner.walk_nagsham_vermilion({}, {})
        self.assertEqual(runner.action.call_count, 4)
        self.assertEqual(runner.locate.call_count, 3)
        self.assertEqual(runner.reset_navigation.call_count, 2)

    def test_source_identity_start_and_road_bounds(self):
        for name, point in [('那古萨无',(649,445)), ('辰之国那古萨无',(545,189))]:
            runner = self.route()
            runner.locate.side_effect = [(name, point, [], None)]
            with self.assertRaisesRegex(RuntimeError, '起点不符'):
                runner.walk_nagsham_vermilion({}, {})
            runner.action.assert_not_called()
        runner = self.route()
        first = ('辰之国那古萨无',(649,445),[],Mock(step=Mock(return_value=('left',600))))
        runner.locate.side_effect = [first,('辰之国那古萨无',(524,360),[],None)]
        with self.assertRaisesRegex(RuntimeError, '偏离'):
            runner.walk_nagsham_vermilion({}, {})

    def test_three_stalled_source_moves_stop(self):
        runner = self.route()
        runner.locate.side_effect = [('辰之国那古萨无',(649,445),[],Mock(step=Mock(return_value=('left',600))))]*4
        with self.assertRaisesRegex(RuntimeError, '三步'):
            runner.walk_nagsham_vermilion({}, {})
        self.assertEqual(runner.action.call_count, 3)

    def test_missing_wrong_and_reversed_landmarks_stop(self):
        for marks in [(None,), ((1,600),), ((0,800),(1,700),(0,300))]:
            runner = self.route([None]*len(marks), marks)
            with self.assertRaisesRegex(RuntimeError, '标志不符|城门柱|顺序异常'):
                runner.walk_nagsham_vermilion({}, {})

    def test_stalled_passage_and_step_limit(self):
        runner = self.route([None]*4, [(0,800)]*4)
        with self.assertRaisesRegex(RuntimeError, '三步'):
            runner.walk_nagsham_vermilion({}, {})
        runner = self.route([None]*13, [(0,1000-20*i) for i in range(13)])
        with self.assertRaisesRegex(RuntimeError, '超过 12 步'):
            runner.walk_nagsham_vermilion({}, {})

    def test_unexpected_map_or_landing_rejected(self):
        runner = self.route(['辰之国那古萨无'])
        with self.assertRaisesRegex(RuntimeError, '意外地图'):
            runner.walk_nagsham_vermilion({}, {})
        for landing in [('红叶街道',(780,117)),('红叶街道2',(640,117))]:
            runner = self.route(landing=landing)
            with self.assertRaisesRegex(RuntimeError, '落点'):
                runner.walk_nagsham_vermilion({}, {})

    def test_user_stop_prevents_movement(self):
        runner = self.route()
        runner.context.tasker.stopping = True
        with self.assertRaisesRegex(RuntimeError, '用户停止'):
            runner.walk_nagsham_vermilion({}, {})
        runner.action.assert_not_called()

    def test_pulse_resample_is_bounded_and_rechecks_map(self):
        runner = self.runner()
        runner.reco = Mock(side_effect=lambda node, frame: node == 'NavigationLocalMap')
        session = MiniMapNavigator(runner, '红叶街道')
        session.burst = Mock(return_value=[2])
        with patch('minimap_navigation.pulse_position', side_effect=[LocalizationLost('两个候选'), (640,117)]), \
                patch('minimap_navigation.read_map_name', return_value='红叶街道'):
            self.assertEqual(session.read_full_map_position([1], '红叶街道', '红叶街道')[2], (640,117))
        session.burst.assert_called_once_with(10)
        session.burst.reset_mock()
        with patch('minimap_navigation.pulse_position', side_effect=LocalizationLost('两个候选')), \
                patch('minimap_navigation.read_map_name', return_value='红叶街道'):
            with self.assertRaises(LocalizationLost):
                session.read_full_map_position([1], '红叶街道', '红叶街道')
        self.assertEqual(session.burst.call_count, 2)
        runner.context.run_action.assert_not_called()

    def test_pulse_resample_rejects_changed_or_closed_map(self):
        for visible, title, error in [(True, '辰之国那古萨无', LocalizationLost),
                                       (False, '红叶街道', NavigationInterrupted)]:
            runner = self.runner()
            runner.reco = Mock(side_effect=lambda node, frame: visible if node == 'NavigationLocalMap' else None)
            session = MiniMapNavigator(runner, '红叶街道')
            session.burst = Mock(return_value=[2])
            with patch('minimap_navigation.pulse_position', side_effect=LocalizationLost('两个候选')), \
                    patch('minimap_navigation.read_map_name', return_value=title):
                with self.assertRaises(error):
                    session.read_full_map_position([1], '红叶街道', '红叶街道')
            session.burst.assert_called_once()
            runner.context.run_action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
