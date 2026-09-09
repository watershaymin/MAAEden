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

    def test_september_9_live_clues(self):
        catalog = load_catalog()
        for text, location in [
            ("这个村落也太冷了吧喵！我要快点去雪屋里避难喵！", "隐居村落 伊杜依斯"),
            ("凉爽的山风 配上风车的声音真是个舒服的国度喵～", "山之国 加达洛"),
            ("真是风光明媚的国家喵！猫咪赛跑也很有意思呢喵！", "辰之国 那古萨无"),
        ]:
            with self.subTest(location=location):
                self.assertEqual(match_clue(text, catalog)["location"], location)

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

    def test_september_10_live_clues(self):
        catalog = load_catalog()
        for text, location in [
            ("这里是最先进的都市吧喵！不知道这个时代会贩卖着什么样的物品呢喵！", "埃尔吉昂·伽玛区"),
            ("飞扬的沙尘让我好想闭上眼睛喵……但我的目光却离不开那些转个不停的风车喵！", "扎博"),
            ("喵！？那个长得像眼球的东西是什喵啊喵？真是座不可思议的岛喵……", "破晓之岛"),
            ("真是一座充满着混浊气息的城镇喵……那些红红蓝蓝的雾状朦胧是什么啊喵？", "影之镇 纳兹里克"),
        ]:
            with self.subTest(location=location):
                self.assertEqual(match_clue(text, catalog)["location"], location)

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

    def test_confirmation_ignores_tiny_punctuation_but_preserves_real_digits(self):
        runner = self.runner()
        label = SimpleNamespace(text="即将移动到曙光都市埃尔吉昂", box=[471, 288, 314, 29], score=0.999)
        punctuation = SimpleNamespace(text="2", box=[782, 303, 9, 9], score=0.856)
        runner.reco = Mock(return_value=SimpleNamespace(all_results=[label, punctuation]))
        self.assertEqual(runner.text("CatDiaryConfirmText", None, single_line=True), label.text)
        punctuation.box = [782, 288, 20, 29]
        self.assertEqual(runner.text("CatDiaryConfirmText", None, single_line=True), label.text + "2")

    def test_oversized_destination_box_is_clicked_at_its_center(self):
        runner = self.runner()
        self.context.run_action.return_value = SimpleNamespace(success=True)
        result = SimpleNamespace(box=SimpleNamespace(x=185, y=582, w=140, h=86))
        runner.click(result)
        self.context.run_action.assert_called_once_with("CatDiaryClick", box=(255, 625, 1, 1))

    def test_map_title_keeps_prefix_first_despite_ocr_height_offset(self):
        runner = self.runner()
        rows = [SimpleNamespace(text="影之镇", box=[20, 17, 128, 42], score=0.997),
                SimpleNamespace(text="纳茲里克", box=[169, 14, 177, 47], score=0.883)]
        runner.reco = Mock(return_value=SimpleNamespace(all_results=rows))
        self.assertEqual(runner.text("CatDiaryMapName", None, single_line=True), "影之镇纳茲里克")

    def test_teleport_only_clicks_era_when_it_is_not_already_selected(self):
        for entry_id, region, initially_selected in (("cat_70", "东方", True), ("cat_70", "东方", False),
                                                     ("cat_43", "冥峡界", True), ("cat_43", "冥峡界", False)):
            with self.subTest(entry_id=entry_id, initially_selected=initially_selected):
                runner = self.runner()
                entry = next(e for e in runner.catalog if e["id"] == entry_id)
                selected = initially_selected
                label = SimpleNamespace(best_result=SimpleNamespace(text=entry["teleport"]))
                runner.world = Mock()
                runner.frame = Mock()
                runner.wait = Mock()
                runner.select_region = Mock()
                runner.wait_confirm = Mock(return_value=object())
                runner.click = Mock()

                def action(node, *args):
                    nonlocal selected
                    if node == "CatDiarySelectEra":
                        selected = True

                def recognize(node, *args):
                    if node == "CatDiaryEraSelected":
                        return selected
                    if node == "CatDiaryDestination":
                        return label
                    return node == "CatDiaryWorldMap"

                runner.action = Mock(side_effect=action)
                runner.reco = Mock(side_effect=recognize)
                runner.teleport(entry)
                era_clicks = [call for call in runner.action.call_args_list if call.args[0] == "CatDiarySelectEra"]
                self.assertEqual(len(era_clicks), 0 if initially_selected else 1)
                runner.select_region.assert_called_once_with(region)
                if not initially_selected:
                    self.assertEqual(era_clicks[0].args[1]["CatDiarySelectEra"]["target"],
                                     [447 if region == "冥峡界" else 203, 115])

    def test_underworld_region_must_be_recognized_before_selection(self):
        for found in (True, False):
            with self.subTest(found=found):
                runner = self.runner()
                button, label = object(), object()
                runner.frame = Mock()
                runner.wait = Mock()
                runner.click = Mock()
                runner.reco = Mock(side_effect=[button, label if found else None])
                if found:
                    runner.select_region("冥峡界")
                    self.assertEqual([call.args[0] for call in runner.click.call_args_list], [button, label])
                else:
                    with self.assertRaisesRegex(RuntimeError, "未识别冥峡界入口"):
                        runner.select_region("冥峡界")
                    runner.click.assert_called_once_with(button)

    def test_elzion_gama_route_and_separate_upper_streets(self):
        road = RoadMap.from_segments(self.runner().maps["埃尔吉昂伽玛区"])
        self.assertEqual(road.step((549.5, 403), (665, 395.5))[0], "right")
        path = road.path((678, 232), (832, 232))
        self.assertGreater(max(y for _, y in path), 300)

    def test_calibrated_slopes_use_horizontal_input_and_keep_vertical_junctions(self):
        runner = self.runner()
        key = "影之镇纳兹里克"
        road = RoadMap.from_segments(runner.maps[key], runner.horizontal_slopes[key])
        for position, direction in [((875, 297), "left"), ((859, 303), "left"),
                                    ((842, 307), "up"), ((815, 220), "left"), ((749, 208), "down")]:
            with self.subTest(position=position):
                self.assertEqual(road.step(position, (731, 289.5))[0], direction)
        disconnected = RoadMap.from_segments(runner.maps[key])
        with self.assertRaises(RuntimeError):
            disconnected.path((946, 284), (731, 289.5))
        with self.assertRaises(ValueError):
            RoadMap.from_segments([], [[800, 200, 800, 300]])

    def test_map_anchor_restores_player_and_cat_coordinates(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e["id"] == "cat_43")
        runner.world = Mock()
        runner.action = Mock()
        runner.frame = Mock(side_effect=[1, 2])
        runner.text = Mock(return_value="影之镇 纳茲里克")

        def result(x, y, w, h):
            return SimpleNamespace(box=SimpleNamespace(x=x, y=y, w=w, h=h), filtered_results=[])

        def recognize(node, frame):
            if node == "NavigationLocalMap":
                return True
            if node == "CatDiaryNazrikAnchor":
                # 先排除横向偏离 30px 的错误候选，再使用纵移 -13px 的真实锚点。
                return result(953 if frame == 1 else 923, 200, 39, 44)
            if node == "CatDiaryPlayer":
                return result(865, 274, 20, 18)
            if node == "CatDiaryMarker":
                return SimpleNamespace(filtered_results=[SimpleNamespace(box=[714, 242, 34, 33])])
            return None

        runner.reco = Mock(side_effect=recognize)
        _, position, targets, road = runner.locate(entry, (895, 288), "left")
        self.assertEqual(position, (875, 296))
        self.assertEqual(targets, [(731, 289.5)])
        self.assertEqual(road.step(position, targets[0])[0], "left")
        self.assertEqual(runner.frame.call_count, 2)
        self.assertTrue(runner.text.call_args.kwargs["single_line"])

    def test_stamps_require_red_paw_area_not_yellow_background(self):
        frame = np.full((720, 1280, 3), [135, 210, 250], dtype=np.uint8)
        self.assertEqual(count_stamps(frame), 0)
        frame[520:545, 373:398] = [0, 0, 180]
        self.assertEqual(count_stamps(frame), 1)

    def test_live_reward_card_includes_seventh_stamp_and_rollover(self):
        # 2026-09-09 实机日记的印章区域：5 枚、礼物上第 7 枚、换卡后 1 枚。
        with np.load(Path(__file__).parent / "fixtures/cat_diary_stamps.npz") as samples:
            for band, expected in zip(samples["bands"], samples["expected"]):
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                frame[514:566, 358:898] = band
                self.assertEqual(count_stamps(frame), expected)
        before = DiaryState((None, "cat_46", "cat_60"), 7)
        verify_change(before, DiaryState((None, "cat_46", None), 1))
        for after in (DiaryState((None, "cat_46", None), 0),
                      DiaryState((None, "cat_46", None), 2),
                      DiaryState(("cat_68", "cat_46", None), 1)):
            with self.assertRaises(RuntimeError):
                verify_change(before, after)

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

    def test_near_junction_turns_without_overshooting_the_alignment(self):
        road = RoadMap.from_segments([[440, 269, 840, 269], [548, 269, 548, 354],
                                      [522, 354, 803, 354]])
        for position in ((541.5, 351.5), (551, 354), (554, 354)):
            with self.subTest(position=position):
                self.assertEqual(road.step(position, (638, 262.5))[0], "up")
        self.assertEqual(road.step((585, 354), (638, 262.5))[0], "left")
        # 路面内短折线不是换道口，不能把水平方向上的目标变成上下移动。
        road.path = Mock(return_value=[(542, 354), (546, 354), (546, 350),
                                       (550, 350), (554, 350), (558, 350)])
        self.assertEqual(road.step((543, 354), (638, 350))[0], "right")

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

    def test_occluded_junction_does_not_reverse_onto_a_longer_route(self):
        # 破晓之岛有左右两个换道口。角色靠近左口时遮住道路，当前图仍能
        # 经右口绕路；不能因此右行，离开遮挡后又左行，形成重复折返。
        runner = self.runner()
        full = RoadMap.from_segments([[440, 269, 840, 269], [548, 269, 548, 354],
                                      [726, 269, 726, 354], [522, 354, 803, 354]])
        hidden = RoadMap.from_segments([[440, 269, 840, 269], [726, 269, 726, 354],
                                        [522, 354, 803, 354]])
        self.assertEqual(hidden.step((559, 354), (632, 262.5))[0], "right")
        runner.interact = Mock(side_effect=[False, False, True])
        runner.locate = Mock(side_effect=[("破晓之岛", (585, 354), [(632, 262.5)], full),
                                         ("破晓之岛", (559, 354), [(638, 262.5)], hidden)])
        runner.action = Mock()
        runner.chase(runner.catalog[0])
        self.assertEqual(runner.action.call_count, 2)
        for call in runner.action.call_args_list:
            self.assertEqual(call.args[1]["CatDiarySwipe"]["end"], [20, 450])

    def test_blocked_movement_uses_a_newly_observed_route(self):
        runner = self.runner()
        full = RoadMap.from_segments([[440, 269, 840, 269], [548, 269, 548, 354],
                                      [726, 269, 726, 354], [522, 354, 803, 354]])
        hidden = RoadMap.from_segments([[440, 269, 840, 269], [726, 269, 726, 354],
                                        [522, 354, 803, 354]])
        runner.interact = Mock(side_effect=[False, False, True])
        runner.locate = Mock(side_effect=[("破晓之岛", (585, 354), [(632, 262.5)], full),
                                         ("破晓之岛", (585, 354), [(638, 262.5)], hidden)])
        runner.action = Mock()
        runner.chase(runner.catalog[0])
        self.assertEqual(runner.action.call_args.args[1]["CatDiarySwipe"]["end"], [380, 450])

    def test_nearby_cat_is_checked_again_after_closing_map(self):
        runner = self.runner()
        road = RoadMap.from_segments([[400, 300, 650, 300]])
        runner.interact = Mock(side_effect=[False, True])
        runner.locate = Mock(return_value=("地图", (500, 300), [(504, 300)], road))
        runner.action = Mock()
        runner.chase(runner.catalog[0])
        self.assertEqual(runner.interact.call_count, 2)
        runner.action.assert_not_called()

    def test_known_road_rejects_background_lantern_as_player(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e["id"] == "cat_68")
        runner.world = Mock()
        runner.action = Mock()
        runner.frame = Mock(side_effect=[1, 2])
        runner.text = Mock(return_value="隐居村落伊杜依斯")

        def recognize(node, frame):
            if node == "NavigationLocalMap":
                return True
            if node == "CatDiaryPlayer":
                # 实机曾将 y=175 的灯笼误认成角色；真实角色位于 y=361。
                return SimpleNamespace(box=SimpleNamespace(x=673, y=165 if frame == 1 else 351, w=20, h=20),
                                       filtered_results=[])
            return None

        runner.reco = Mock(side_effect=recognize)
        with patch("cat_diary.time.sleep"):
            _, position, _, _ = runner.locate(entry)
        self.assertEqual(position, (683, 361))
        self.assertEqual(runner.frame.call_count, 2)

    def test_itoise_route_uses_observed_lane_connectors(self):
        road = RoadMap.from_segments(self.runner().maps["隐居村落伊杜依斯"])
        self.assertEqual(road.step((688, 360), (620, 531))[0], "right")
        self.assertEqual(road.step((730, 361), (620, 531))[0], "down")
        self.assertEqual(road.step((726, 444), (620, 531))[0], "left")
        self.assertEqual(road.step((653, 447), (620, 531))[0], "down")

    def test_nagsham_route_does_not_turn_at_quest_icon(self):
        road = RoadMap.from_segments(self.runner().maps["辰之国那古萨无"])
        self.assertEqual(road.step((751, 446), (870, 361))[0], "right")
        self.assertEqual(road.step((807.5, 445.5), (870, 361))[0], "up")

    def test_hidden_marker_can_still_have_a_scene_interaction(self):
        runner = self.runner()
        runner.interact = Mock(side_effect=[False, True])
        runner.locate = Mock(return_value=("地图", (500, 300), [], RoadMap.from_segments([])))
        runner.action = Mock()
        runner.chase(runner.catalog[0])
        runner.action.assert_not_called()

    def test_calibrated_occlusion_search_never_counts_as_success(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e["id"] == "cat_46")
        road = RoadMap.from_segments(runner.maps["山之国加达洛"])
        runner.interact = Mock(return_value=False)
        runner.locate = Mock(return_value=("山之国加达洛", (422, 392), [], road))
        runner.action = Mock()
        with self.assertRaisesRegex(RuntimeError, "连续四帧"):
            runner.chase(entry)
        self.assertEqual(runner.locate.call_count, 5)
        runner.action.assert_not_called()

    def test_occlusion_search_only_moves_on_calibrated_roads(self):
        runner = self.runner()
        entry = next(e for e in runner.catalog if e["id"] == "cat_46")
        road = RoadMap.from_segments(runner.maps["山之国加达洛"])
        runner.interact = Mock(side_effect=[False, False, True])
        runner.locate = Mock(return_value=("山之国加达洛", (595, 393), [], road))
        runner.action = Mock()
        runner.chase(entry)
        self.assertEqual(runner.action.call_count, 1)
        self.assertEqual(runner.action.call_args.args[1]["CatDiarySwipe"]["end"], [20, 450])

    def test_invalid_parameters_and_callback_exceptions_are_failures(self):
        for params in ([], {"max_minutes": True}, {"max_minutes": 0}, {"max_steps": 0}, {"max_steps": 601}):
            with patch("cat_diary.CatDiaryRunner") as runner:
                self.assertFalse(CatDiary().run(None, SimpleNamespace(custom_action_param=json.dumps(params))))
                runner.assert_not_called()
        with patch("cat_diary.CatDiaryRunner", side_effect=AttributeError("callback")):
            self.assertFalse(CatDiary().run(None, SimpleNamespace(custom_action_param="{}")))


if __name__ == "__main__":
    unittest.main()
