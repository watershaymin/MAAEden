"""克鲁利大道进场：验证源楼层、出口按钮和跨图后的独立落点。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from cat_diary import CatDiaryRunner


class CluriEntranceTests(unittest.TestCase):
    def runner(self, locations=()):
        runner = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        runner.locate = Mock(side_effect=locations)
        runner.wait = Mock(return_value=object())
        runner.reco = Mock(return_value=object())
        runner.click = Mock()
        runner.wait_area_transition = Mock()
        runner.action = Mock()
        return runner

    def test_both_clues_use_tower_without_accepting_it_as_destination(self):
        for entry_id in ('cat_09', 'cat_16'):
            with self.subTest(entry=entry_id):
                runner = self.runner()
                entry = next(e for e in runner.catalog if e['id'] == entry_id)
                runner.teleport = Mock()
                runner.leave_time_tower = Mock()
                CatDiaryRunner.teleport(runner, entry)
                source = runner.teleport.call_args.args[0]
                self.assertEqual(source['teleport'], '时之塔')
                self.assertEqual(source['map_names'], ['时之塔1楼'])
                self.assertNotIn('approach', source)
                self.assertEqual(entry['map_names'], ['克鲁利大道'])
                self.assertEqual(entry['world_names'], ['克鲁利大道'])
                runner.leave_time_tower.assert_called_once_with(source, entry)

    def test_verified_exit_and_landing_need_no_movement(self):
        runner = self.runner([('时之塔1楼', (655, 457), [], None),
                              ('克鲁利大道', (226, 232), [], None)])
        runner.leave_time_tower({}, {})
        runner.wait.assert_called_once_with('CatDiaryTimeTowerExit')
        runner.click.assert_called_once_with(runner.reco.return_value)
        runner.wait_area_transition.assert_called_once()
        runner.action.assert_not_called()

    def test_wrong_floor_or_source_position_stops_before_exit(self):
        for name, point in [('时之塔2楼', (655, 457)), ('时之塔', (655, 457)),
                            ('时之塔1楼', (655, 360)), ('时之塔1楼', (730, 457))]:
            with self.subTest(name=name, point=point):
                runner = self.runner([(name, point, [], None)])
                with self.assertRaisesRegex(RuntimeError, '起点不符'):
                    runner.leave_time_tower({}, {})
                runner.wait.assert_not_called()
                runner.click.assert_not_called()
                runner.wait_area_transition.assert_not_called()

    def test_unrecognized_exit_cannot_click_or_enter_destination(self):
        runner = self.runner([('时之塔1楼', (655, 457), [], None)])
        runner.wait.side_effect = RuntimeError('出口未就绪')
        with self.assertRaisesRegex(RuntimeError, '出口未就绪'):
            runner.leave_time_tower({}, {})
        runner.click.assert_not_called()
        runner.wait_area_transition.assert_not_called()
        self.assertEqual(runner.locate.call_count, 1)

    def test_wrong_destination_or_landing_stops_without_movement(self):
        for name, point in [('时之塔1楼', (226, 232)), ('克鲁利大道2楼', (226, 232)),
                            ('克鲁利大道', (640, 232)), ('克鲁利大道', (226, 400))]:
            with self.subTest(name=name, point=point):
                runner = self.runner([('时之塔1楼', (655, 457), [], None),
                                      (name, point, [], None)])
                with self.assertRaisesRegex(RuntimeError, '未确认.*到达'):
                    runner.leave_time_tower({}, {})
                runner.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
