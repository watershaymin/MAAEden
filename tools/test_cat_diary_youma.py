"""妖魔殿一楼进场与昆仑山殿外路线隔离。"""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from cat_diary import CatDiaryRunner


class YoumaEntranceTests(unittest.TestCase):
    def runner(self, positions=()):
        r = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        self.road = Mock()
        self.road.step.return_value = ('up', 600)
        r.locate = Mock(side_effect=[(name, point, [], self.road) for name, point in positions])
        r.wait = Mock(return_value=object())
        r.reco = Mock(return_value=object())
        r.click = Mock()
        r.wait_area_transition = Mock()
        r.action = Mock()
        return r

    def test_cat_enters_palace_after_exact_exterior_teleport(self):
        r = self.runner()
        entry = next(e for e in r.catalog if e['id'] == 'cat_67')
        r.teleport = Mock()
        r.enter_youma_palace = Mock()
        CatDiaryRunner.teleport(r, entry)
        source = r.teleport.call_args.args[0]
        self.assertNotIn('approach', source)
        self.assertEqual(source['map_names'], ['妖魔殿'])
        self.assertEqual(source['road_map'], '妖魔殿')
        self.assertEqual(source['world_names'], ['妖魔殿'])
        self.assertEqual(entry['map_names'], ['妖魔殿一楼入口'])
        r.enter_youma_palace.assert_called_once_with(source, entry)

    def test_kunlun_remains_outside_and_does_not_enter_palace(self):
        r = self.runner()
        entry = next(e for e in r.catalog if e.get('approach') == 'kunlun_slide')
        r.teleport = Mock()
        r.slide_to_kunlun = Mock()
        r.enter_youma_palace = Mock()
        CatDiaryRunner.teleport(r, entry)
        source = r.teleport.call_args.args[0]
        self.assertNotIn('approach', source)
        self.assertEqual(source['map_names'], ['妖魔殿'])
        self.assertEqual(source['road_map'], '妖魔殿')
        self.assertEqual(entry['map_names'], ['昆仑山脉'])
        r.slide_to_kunlun.assert_called_once_with(source, entry)
        r.enter_youma_palace.assert_not_called()

    def test_verified_road_door_and_inside_landing(self):
        r = self.runner([('妖魔殿', (650, 394)), ('妖魔殿', (650, 309)),
                         ('妖魔殿一楼入口', (640, 440))])
        r.enter_youma_palace({}, {})
        self.assertEqual(r.action.call_count, 1)
        self.assertEqual(r.action.call_args.args[1]['CatDiarySwipe']['end'], [200, 270])
        r.wait.assert_called_once_with('CatDiaryYoumaDoor')
        r.click.assert_called_once_with(r.reco.return_value)
        r.wait_area_transition.assert_called_once()

    def test_wrong_map_or_teleport_landing_cannot_move_or_click(self):
        for name, point in [('妖魔殿一楼入口', (650, 394)), ('妖魔殿二楼', (650, 394)),
                            ('妖魔殿', (650, 300)), ('妖魔殿', (700, 394))]:
            with self.subTest(name=name, point=point):
                r = self.runner([(name, point)])
                with self.assertRaisesRegex(RuntimeError, '起点不符'):
                    r.enter_youma_palace({}, {})
                r.action.assert_not_called()
                r.click.assert_not_called()

    def test_deviation_after_movement_cannot_click_door(self):
        r = self.runner([('妖魔殿', (650, 394)), ('妖魔殿', (680, 315))])
        with self.assertRaisesRegex(RuntimeError, '偏离'):
            r.enter_youma_palace({}, {})
        r.click.assert_not_called()

    def test_other_road_direction_is_rejected(self):
        r = self.runner([('妖魔殿', (650, 394))])
        self.road.step.return_value = ('right', 600)
        with self.assertRaisesRegex(RuntimeError, '向上道路'):
            r.enter_youma_palace({}, {})
        r.action.assert_not_called()

    def test_missing_door_cannot_click_or_transition(self):
        r = self.runner([('妖魔殿', (650, 394)), ('妖魔殿', (650, 309))])
        r.reco.return_value = None
        with self.assertRaisesRegex(RuntimeError, '按钮未就绪'):
            r.enter_youma_palace({}, {})
        r.click.assert_not_called()
        r.wait_area_transition.assert_not_called()

    def test_wrong_inside_floor_or_landing_stops(self):
        for name, point in [('妖魔殿', (640, 440)), ('妖魔殿二楼入口', (640, 440)),
                            ('妖魔殿一楼入口', (640, 360))]:
            with self.subTest(name=name, point=point):
                r = self.runner([('妖魔殿', (650, 394)), ('妖魔殿', (650, 309)), (name, point)])
                with self.assertRaisesRegex(RuntimeError, '未确认进入'):
                    r.enter_youma_palace({}, {})
                self.assertEqual(r.action.call_count, 1)

    def test_stalled_movement_stops_after_three_inputs(self):
        r = self.runner([('妖魔殿', (650, 394))] * 4)
        with self.assertRaisesRegex(RuntimeError, '连续三步'):
            r.enter_youma_palace({}, {})
        self.assertEqual(r.action.call_count, 3)
        r.click.assert_not_called()

    def test_progress_without_reaching_door_has_three_step_bound(self):
        r = self.runner([('妖魔殿', (650, y)) for y in (394, 380, 365, 350)])
        with self.assertRaisesRegex(RuntimeError, '超过 3 步'):
            r.enter_youma_palace({}, {})
        self.assertEqual(r.action.call_count, 3)
        r.click.assert_not_called()

    def test_stop_and_expired_diary_are_checked_before_movement(self):
        for mode in ('stop', 'expired'):
            r = self.runner()
            if mode == 'stop':
                r.context.tasker.stopping = True
            else:
                r.round_deadline = time.monotonic() - 1
            with self.assertRaises(RuntimeError):
                r.enter_youma_palace({}, {})
            r.locate.assert_not_called()
            r.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
