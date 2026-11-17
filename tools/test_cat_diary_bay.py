"""海湾入口只接受船墓准确楼层、出口按钮和跨图后的独立落点。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from cat_diary import CatDiaryRunner


class BayEntranceTests(unittest.TestCase):
    def runner(self, locations=()):
        runner = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        runner.locate = Mock(side_effect=locations)
        runner.wait = Mock(return_value=object())
        runner.reco = Mock(return_value=object())
        runner.click = Mock()
        runner.wait_area_transition = Mock()
        runner.action = Mock()
        return runner

    def test_bay_uses_ship_without_accepting_source_as_destination(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e['id'] == 'cat_52')
        runner.teleport = Mock()
        runner.leave_ship_graveyard = Mock()
        CatDiaryRunner.teleport(runner, entry)
        source = runner.teleport.call_args.args[0]
        self.assertEqual(source['id'], 'cat_53')
        self.assertEqual(source['teleport'], '船墓')
        self.assertEqual(source['map_names'], ['船墓第一只中型船船底'])
        self.assertNotIn('approach', source)
        self.assertEqual(entry['map_names'], ['库尔奇海湾'])
        self.assertEqual(entry['world_names'], ['库尔奇海湾'])
        runner.leave_ship_graveyard.assert_called_once_with(source, entry)

    def test_verified_door_crossing_needs_no_movement(self):
        runner = self.runner([('船墓第一只中型船船底', (815, 479), [], None),
                              ('库尔奇海湾', (250, 574), [], None)])
        runner.leave_ship_graveyard({}, {})
        runner.click.assert_called_once_with(runner.reco.return_value)
        runner.wait_area_transition.assert_called_once()
        runner.action.assert_not_called()

    def test_wrong_ship_floor_or_position_cannot_click(self):
        for name, point in [('船墓第一只中型船中甲板', (815, 479)),
                            ('船墓第二只中型船船底', (815, 479)),
                            ('船墓第一只中型船船底', (640, 479)),
                            ('船墓第一只中型船船底', (815, 400))]:
            with self.subTest(name=name, point=point):
                runner = self.runner([(name, point, [], None)])
                with self.assertRaisesRegex(RuntimeError, '起点不符'):
                    runner.leave_ship_graveyard({}, {})
                runner.wait.assert_not_called()
                runner.click.assert_not_called()

    def test_missing_or_disappearing_exit_cannot_click(self):
        for missing in ['wait', 'recheck']:
            runner = self.runner([('船墓第一只中型船船底', (815, 479), [], None)])
            if missing == 'wait':
                runner.wait.side_effect = RuntimeError('出口未就绪')
            else:
                runner.reco.return_value = None
            with self.assertRaises(RuntimeError):
                runner.leave_ship_graveyard({}, {})
            runner.click.assert_not_called()
            runner.wait_area_transition.assert_not_called()

    def test_failed_transition_cannot_claim_arrival(self):
        runner = self.runner([('船墓第一只中型船船底', (815, 479), [], None)])
        runner.wait_area_transition.side_effect = RuntimeError('未开始切换场景')
        with self.assertRaises(RuntimeError):
            runner.leave_ship_graveyard({}, {})
        self.assertEqual(runner.locate.call_count, 1)

    def test_wrong_destination_or_landing_stops(self):
        for name, point in [('船墓第一只中型船船底', (250, 574)),
                            ('库尔奇海湾2楼', (250, 574)),
                            ('库尔奇海湾', (640, 574)), ('库尔奇海湾', (250, 400))]:
            with self.subTest(name=name, point=point):
                runner = self.runner([('船墓第一只中型船船底', (815, 479), [], None),
                                      (name, point, [], None)])
                with self.assertRaisesRegex(RuntimeError, '未确认.*到达'):
                    runner.leave_ship_graveyard({}, {})
                runner.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
