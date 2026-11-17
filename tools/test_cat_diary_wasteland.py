"""沉淀之地进场的源坐标、场景顺序、位移和落点边界。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from cat_diary import CatDiaryRunner


class WastelandEntranceTests(unittest.TestCase):
    def runner(self):
        runner = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        runner.action = Mock()
        runner.reset_navigation = Mock()
        runner.world = Mock(return_value=object())
        runner.locate = Mock(side_effect=[
            ('再生村落安格尔', (565, 399), [], None),
            ('再生村落安格尔', (376, 399), [], None),
            ('再生村落安格尔', (376, 399), [], None),
            ('再生村落安格尔', (347, 399), [], None),
            ('沉淀之地', (1030, 316), [], None),
        ])
        runner.crossing_map_name = Mock(side_effect=['再生村落安格尔'] * 2 + [None] * 7 + ['沉淀之地'])
        stages = [('Wall', 740), ('WallEnd', 130), ('Ruin', 475), ('Log', 310),
                  ('Tree', 250), ('Tree', 666), ('Tree', 1057)]
        def reco(node, frame):
            index = (runner.reco.call_count - 1) // 5
            name, x = stages[index]
            if node == 'CatDiaryAngalWest' + name:
                return SimpleNamespace(best_result=SimpleNamespace(box=[x, 0, 10, 10]))
            return None
        runner.reco = Mock(side_effect=reco)
        return runner

    def test_catalog_uses_angal_before_exact_wasteland(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e['id'] == 'cat_72')
        runner.teleport = Mock()
        runner.walk_angal_wasteland = Mock()
        CatDiaryRunner.teleport(runner, entry)
        source = runner.teleport.call_args.args[0]
        self.assertEqual(source['id'], 'cat_71')
        self.assertEqual(entry['map_names'], ['沉淀之地'])
        self.assertEqual(entry['world_names'], ['沉淀之地'])
        runner.walk_angal_wasteland.assert_called_once_with(source, entry)

    def test_verified_source_passage_and_landing(self):
        runner = self.runner()
        runner.walk_angal_wasteland({}, {})
        self.assertEqual(runner.action.call_count, 10)
        self.assertEqual(runner.locate.call_count, 5)

    def test_wrong_source_name_position_or_route_stops(self):
        for name, position in [('再生村落安格尔2楼', (565, 399)),
                               ('再生村落安格尔', (400, 399)),
                               ('再生村落安格尔', (565, 430))]:
            runner = self.runner()
            runner.locate.side_effect = [(name, position, [], None)]
            with self.assertRaises(RuntimeError):
                runner.walk_angal_wasteland({}, {})
            runner.action.assert_not_called()

    def test_source_stall_stops(self):
        runner = self.runner()
        runner.locate.side_effect = [('再生村落安格尔', (565, 399), [], None)] * 4
        with self.assertRaisesRegex(RuntimeError, '连续三步'):
            runner.walk_angal_wasteland({}, {})
        self.assertEqual(runner.action.call_count, 3)

    def test_unknown_passage_and_wrong_map_stop(self):
        for name in [None, '其他区域']:
            runner = self.runner()
            runner.crossing_map_name.side_effect = [name]
            runner.reco = Mock(return_value=None)
            with self.assertRaises(RuntimeError):
                runner.walk_angal_wasteland({}, {})
            self.assertEqual(runner.action.call_count, 1)

    def test_passage_cannot_start_midway_or_move_backwards(self):
        for stages in [[2], [0, 2], [0, 1, 0]]:
            runner = self.runner()
            runner.crossing_map_name.side_effect = [None] * 4
            results = []
            for stage in stages:
                results.extend(SimpleNamespace(best_result=SimpleNamespace(box=[50, 0, 10, 10]))
                               if i == stage else None for i in range(5))
            runner.reco = Mock(side_effect=results)
            with self.assertRaises(RuntimeError):
                runner.walk_angal_wasteland({}, {})

    def test_passage_stall_and_step_limit_stop(self):
        for moves, message in [(4, '连续三步'), (13, '超过 12 步')]:
            runner = self.runner()
            runner.crossing_map_name.side_effect = [None] * moves
            def reco(node, frame):
                index = (runner.reco.call_count - 1) // 5
                x = 50 if moves == 4 else 50 + index * 5
                return SimpleNamespace(best_result=SimpleNamespace(box=[x, 0, 10, 10])) if node.endswith('Wall') else None
            runner.reco = Mock(side_effect=reco)
            with self.assertRaisesRegex(RuntimeError, message):
                runner.walk_angal_wasteland({}, {})

    def test_wrong_landing_stops(self):
        runner = self.runner()
        runner.crossing_map_name.side_effect = ['沉淀之地']
        runner.locate.side_effect = [
            ('再生村落安格尔', (565, 399), [], None),
            ('再生村落安格尔', (376, 399), [], None),
            ('沉淀之地', (640, 316), [], None),
        ]
        with self.assertRaisesRegex(RuntimeError, '东侧落点'):
            runner.walk_angal_wasteland({}, {})


if __name__ == '__main__':
    unittest.main()
