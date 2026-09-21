"""幻璃境的消耗、事件优先级与终境停机边界。"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from phantom import PhantomJackpot, PhantomRunner, distinct_points, room_from_text, stationary_scene, verify_white_party


class PhantomRules(unittest.TestCase):
    def test_terminal_title_does_not_depend_on_visit_count(self):
        self.assertEqual(room_from_text("终 之 境"), "last")
        self.assertEqual(room_from_text("幻璃境 終之境"), "last")
        self.assertEqual(room_from_text("此岸之境"), "dungeon")
        self.assertEqual(room_from_text("伍之境"), "baruoki")
        self.assertEqual(room_from_text("猫之境"), "cats")
        self.assertIsNone(room_from_text("平行迷宫"))

    def test_white_entry_requires_exact_target_ticket_and_cost(self):
        prompt = "将消耗1个白色解锁卡，并移动到幻璃境（困难）。"
        self.assertTrue(verify_white_party(prompt))
        for wrong in (prompt.replace("白色", "红色"), prompt.replace("1个", "2个"),
                      prompt.replace("幻璃境", "月影森林"), prompt + "克洛诺斯之石"):
            self.assertFalse(verify_white_party(wrong))

    def test_overlapping_templates_do_not_duplicate_events(self):
        hit = lambda box, score: SimpleNamespace(box=box, score=score)
        result = SimpleNamespace(filtered_results=[hit([100, 200, 12, 35], .95),
                                                   hit([99, 199, 14, 39], .9),
                                                   hit([400, 200, 12, 35], .94)])
        self.assertEqual(distinct_points(result), [(106, 217), (406, 217)])

    def test_observed_displacement_not_accumulated_swipe_time(self):
        image = np.random.default_rng(1).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        self.assertTrue(stationary_scene(image, image.copy()))
        self.assertFalse(stationary_scene(image, np.roll(image, 30, axis=1)))

    def test_jackpot_stops_before_any_game_input(self):
        runner = PhantomRunner(SimpleNamespace(tasker=Mock(), run_action=Mock()))
        runner.title = Mock(return_value="last")
        runner.record = Mock()
        runner.click = Mock()
        with self.assertRaisesRegex(PhantomJackpot, "你撞大运了"):
            runner.observe_room("frame")
        runner.context.run_action.assert_called_once_with("PhantomJackpot")
        runner.context.tasker.post_stop.assert_called_once_with()
        runner.click.assert_not_called()

    def test_first_room_excludes_both_left_statistics_events(self):
        runner = PhantomRunner(SimpleNamespace())
        runner.room = "first"
        runner.wait_room = Mock(return_value="frame")
        runner.events = Mock(return_value=[(320, 100), (460, 60), (1040, 140)])
        runner.interact = Mock(side_effect=PhantomJackpot("stop probe"))
        with self.assertRaises(PhantomJackpot):
            runner.run(enter=False)
        runner.interact.assert_called_once_with((1040, 140), "exit")

    def test_notification_is_visible_and_does_not_click_game(self):
        root = Path(__file__).resolve().parents[1]
        node = json.loads((root / "assets/resource/pipeline/phantom.json").read_text(encoding="utf-8"))["PhantomJackpot"]
        self.assertEqual(node["action"], "DoNothing")
        self.assertTrue(node["focus"]["aborted"])
        self.assertEqual(node["focus"]["Node.Action.Starting"]["content"], "你撞大运了")
        self.assertIn("dialog", node["focus"]["Node.Action.Starting"]["display"])

    def test_black_cat_waits_for_boxes_then_precedes_other_exits(self):
        for opened, expected in [(2, ((500, 230), "chest")), (3, ((300, 230), "black-cat"))]:
            with self.subTest(opened=opened):
                runner = PhantomRunner(SimpleNamespace())
                runner.room = "baruoki"
                runner.chests_opened = opened
                runner.wait_room = Mock(return_value="frame")
                runner.events = Mock(return_value=[(300, 230), (500, 230), (950, 100)])
                hit = SimpleNamespace(box=[275, 340, 50, 50], score=.9)
                runner.reco = Mock(return_value=SimpleNamespace(filtered_results=[hit]))
                runner.loot_points = Mock(side_effect=lambda frame, kind: [(300, 230)] if kind == "cat" else [(500, 230)])
                runner.interact = Mock(side_effect=PhantomJackpot("stop probe"))
                with self.assertRaises(PhantomJackpot):
                    runner.run(enter=False)
                runner.interact.assert_called_once_with(*expected)

    def test_baruoki_requires_black_cat_search_but_not_a_normal_stamp_cat(self):
        for searched in (False, True):
            with self.subTest(searched=searched):
                runner = PhantomRunner(SimpleNamespace())
                runner.room = 'baruoki'
                runner.chests_opened = 3
                runner.baruoki_left_checked = searched
                runner.wait_room = Mock(return_value='frame')
                runner.events = Mock(return_value=[(450, 161)])
                runner.reco = Mock(return_value=None)
                runner.loot_points = Mock(return_value=[])
                runner.record = Mock()
                runner.interact = Mock(side_effect=RuntimeError('exit probe'))
                runner.action = Mock(side_effect=RuntimeError('search probe'))
                with self.assertRaisesRegex(RuntimeError, 'exit probe' if searched else 'search probe'):
                    runner.run(enter=False)
                if searched:
                    runner.interact.assert_called_once_with((450, 161), 'exit')
                else:
                    runner.interact.assert_not_called()


if __name__ == "__main__":
    unittest.main()
