"""离线验证猫咪日记的地点消歧、刷新循环、真实完成态和停止保护。"""

import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from cat_diary import CatDiary, CatDiaryRunner, DiaryState, RoadMap, count_stamps, load_catalog, match_clue, remaining_seconds, verify_change


class CatDiaryTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(tasker=SimpleNamespace(stopping=False), run_action=Mock())

    def runner(self):
        return CatDiaryRunner(self.context)

    def test_catalog_and_three_supplied_clues(self):
        catalog = load_catalog()
        self.assertEqual(len(catalog), 76)
        for text, location in [
            ("宁静又美丽的海岸……真是适合被称作世界边缘的地方喵！", "最终之岛"),
            ("这里对我们猫咪来说\n感觉是个舒服自在的神社呢喵……！", "猫神神社"),
            ("这里有一片美丽的金黄色麦田喵！在这里玩躲猫猫的话一定很好玩喵。", "劳拉巨蛋城"),
        ]:
            self.assertEqual(match_clue(text, catalog)["location"], location)
        # 对照表里每个短语均须能唯一映射到一个目的地。
        for entry in catalog:
            for clue in entry["clues"]:
                with self.subTest(id=entry["id"], clue=clue):
                    self.assertEqual(match_clue(clue, catalog)["location"], entry["location"])

    def test_unknown_and_ambiguous_clues_are_not_teleports(self):
        catalog = load_catalog()
        for text in ("", "喵", "不可思议的领域", "新增的地点", "宁静又美丽的海岸这里有一片美丽的金黄色麦田"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                match_clue(text, catalog)

    def test_refresh_replaces_old_queue_and_runs_until_all_three_finish(self):
        runner = self.runner()
        a, b, c, refreshed = [entry["id"] for entry in runner.catalog[:4]]
        states = [DiaryState((a, b, c), 0), DiaryState((refreshed, b, c), 1),
                  DiaryState((None, b, c), 2), DiaryState((None, None, c), 3),
                  DiaryState((None, None, None), 4)]
        runner.read_diary = Mock(side_effect=states)
        runner.close_diary = Mock()
        runner.teleport = Mock()
        runner.chase = Mock()
        runner.run()
        self.assertEqual([call.args[0]["id"] for call in runner.chase.call_args_list], [a, refreshed, b, c])

    def test_same_location_with_new_stamp_is_processed_again(self):
        runner = self.runner()
        target = runner.catalog[0]["id"]
        runner.read_diary = Mock(side_effect=[DiaryState((target, None, None), 0),
                                             DiaryState((target, None, None), 1),
                                             DiaryState((None, None, None), 2)])
        runner.close_diary = Mock()
        runner.teleport = Mock()
        runner.chase = Mock()
        runner.run()
        self.assertEqual(runner.read_diary.call_count, 3)
        self.assertEqual(runner.chase.call_count, 2)

    def test_already_complete_never_leaves_diary(self):
        runner = self.runner()
        runner.read_diary = Mock(return_value=DiaryState((None, None, None), 6))
        runner.teleport = Mock()
        runner.run()
        runner.teleport.assert_not_called()

    def test_unchanged_state_and_reset_fail(self):
        state = DiaryState(("cat_01", None, None), 3)
        for after in (state, DiaryState(("cat_02", None, None), 0),
                      DiaryState(("cat_01", "cat_02", None), 4)):
            with self.assertRaises(RuntimeError):
                verify_change(state, after)

    def test_daily_timer_does_not_accept_weekly_reward_timer(self):
        self.assertEqual(remaining_seconds("剩余 23小时"), 23 * 3600)
        self.assertEqual(remaining_seconds("剩余1小时5分钟"), 3900)
        self.assertEqual(remaining_seconds("剩余59秒"), 59)
        for content in ("", "剩余", "剩余6天", "剩余xx小时"):
            with self.assertRaises(ValueError):
                remaining_seconds(content)
        pipeline = json.loads((Path(__file__).resolve().parents[1] / "assets/resource/pipeline/cat_diary.json").read_text(encoding="utf-8"))
        self.assertLess(pipeline["CatDiaryRemaining"]["roi"][1], 145)

    def test_round_expiry_stops_before_another_input(self):
        runner = self.runner()
        runner.round_deadline = time.monotonic() - 1
        with self.assertRaisesRegex(RuntimeError, "刷新时间"):
            runner.action("CatDiarySwipe")
        self.context.run_action.assert_not_called()

    def test_unreadable_slot_is_not_a_finished_cat(self):
        runner = self.runner()
        runner.open_diary = Mock()
        runner.frame = Mock(return_value=np.zeros((720, 1280, 3), dtype=np.uint8))
        runner.diary_ready = Mock(return_value=True)
        runner.reco = Mock(side_effect=lambda node, *args: True if node == "CatDiaryCloseButton" else None)
        runner.text = Mock(return_value="")
        with patch("cat_diary.time.monotonic", side_effect=[0, 0, 30]), patch("cat_diary.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "没有文字"):
                runner.read_diary()

    def test_late_reward_is_dismissed_before_closing_diary(self):
        runner = self.runner()
        runner.frame = Mock(side_effect=range(5))
        runner.diary_ready = Mock(side_effect=[True, True, True, True, False])
        runner.reco = Mock(side_effect=lambda node, frame: (node == "CatDiaryRewardToast" and frame == 1)
                           or (node == "CatDiaryCloseButton" and frame == 3))
        runner.action = Mock()
        runner.world = Mock()
        with patch("cat_diary.time.sleep"):
            runner.close_diary()
        self.assertEqual([call.args[0] for call in runner.action.call_args_list],
                         ["CatDiaryDismissToast", "CatDiaryClose"])
        runner.world.assert_called_once()

    def test_split_confirmation_requires_exact_destination(self):
        runner = self.runner()
        runner.frame = Mock(return_value=None)
        runner.text = Mock(return_value="即将移动到古代树之村 帕德列。")
        yes = object()
        runner.reco = Mock(side_effect=lambda node, *args: yes if node == "CatDiaryConfirmYes" else True)
        self.assertIs(runner.wait_confirm("帕德列", "^帕德列$", ["古代树之村 帕德列"]), yes)
        runner.text.return_value = "即将移动到猫神神社。"
        with patch("cat_diary.time.monotonic", side_effect=[0, 0, 11]):
            with self.assertRaisesRegex(RuntimeError, "确认文字不符"):
                runner.wait_confirm("帕德列", "^帕德列$", ["古代树之村 帕德列"])

    def test_stamps_require_red_paw_area_not_yellow_background(self):
        frame = np.full((720, 1280, 3), [135, 210, 250], dtype=np.uint8)
        self.assertEqual(count_stamps(frame), 0)
        frame[520:545, 373:398] = [0, 0, 180]
        self.assertEqual(count_stamps(frame), 1)

    def test_paths_follow_connectors_and_do_not_cross_gaps(self):
        road = RoadMap.from_segments([[400, 300, 600, 300], [600, 300, 600, 400], [600, 400, 800, 400]])
        path = road.path((400, 300), (800, 400))
        self.assertTrue(all(abs(y - 300) <= 6 or abs(x - 600) <= 6 or abs(y - 400) <= 6 for x, y in path))
        self.assertEqual(road.step((400, 300), (800, 400))[0], "right")
        disconnected = RoadMap.from_segments([[400, 300, 500, 300], [560, 300, 800, 300]])
        with self.assertRaises(RuntimeError):
            disconnected.path((400, 300), (800, 300))

    def test_player_can_occlude_a_road_endpoint_but_not_a_real_gap(self):
        base = np.zeros((720, 1280, 3), dtype=np.uint8)
        overlay = base.copy()
        overlay[288:313, 400:601] = 160
        occlusions = [[550, 268, 80, 64]]
        road = RoadMap(base, overlay, occlusions, (590, 300))
        self.assertEqual(road.step((590, 300), (420, 300))[0], "left")
        overlay[288:313, 500:560] = 0
        disconnected = RoadMap(base, overlay, occlusions, (590, 300))
        with self.assertRaises(RuntimeError):
            disconnected.path((590, 300), (420, 300))

    def test_known_sami_route_does_not_turn_early(self):
        runner = self.runner()
        road = RoadMap.from_segments(runner.maps["海之国佐见"])
        self.assertEqual(road.step((727, 404), (770, 232))[0], "right")
        self.assertEqual(road.step((768, 404), (770, 232))[0], "up")

    def test_ring_offset_does_not_trigger_another_lane(self):
        road = RoadMap.from_segments(self.runner().maps["王都尤尼冈"])
        for position in ((508, 275), (505.5, 275.5)):
            self.assertEqual(road.step(position, (629, 280.5))[0], "right")
        self.assertEqual(road.step((506, 360), (629, 280.5))[0], "up")

    def test_moving_icons_do_not_erase_previously_traversed_road(self):
        runner = self.runner()
        road = RoadMap.from_segments([[400, 300, 650, 300]])
        hidden = RoadMap.from_segments([])
        runner.interact = Mock(side_effect=[False, False, True])
        runner.locate = Mock(side_effect=[("地图", (400, 300), [(600, 300)], road),
                                         ("地图", (430, 300), [(610, 300)], hidden)])
        runner.action = Mock()
        runner.chase(runner.catalog[0])
        self.assertEqual(runner.action.call_count, 2)
        for call in runner.action.call_args_list:
            self.assertEqual(call.args[1]["CatDiarySwipe"]["end"], [380, 450])

    def test_stopping_and_timeout_do_not_click(self):
        runner = self.runner()
        self.context.tasker.stopping = True
        with self.assertRaises(RuntimeError):
            runner.action("CatDiarySwipe")
        self.context.tasker.stopping = False
        runner.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError):
            runner.click(Mock())
        self.context.run_action.assert_not_called()

    def test_invalid_parameters_and_callback_exceptions_are_failures(self):
        for params in ([], {"max_minutes": True}, {"max_minutes": 0}, {"max_steps": 0}, {"max_steps": 601}):
            with patch("cat_diary.CatDiaryRunner") as runner:
                self.assertFalse(CatDiary().run(None, SimpleNamespace(custom_action_param=json.dumps(params))))
                runner.assert_not_called()
        with patch("cat_diary.CatDiaryRunner", side_effect=AttributeError("callback")):
            self.assertFalse(CatDiary().run(None, SimpleNamespace(custom_action_param="{}")))


if __name__ == "__main__":
    unittest.main()
