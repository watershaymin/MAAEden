"""不连接设备：副本卡片归属、目录匹配、列表重排与单次消耗边界。"""

import json
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from dungeons import DungeonSkipUnavailable
from monthly_dungeons import (DungeonTrial, MonthlyTrialDungeons, TrialDungeonNavigator,
                              match_dungeon, parse_cards, same_rows, verify_snapshot)


def row(text, y, x=470, score=0.99):
    return SimpleNamespace(text=text, box=[x, y, len(text) * 20, 24], score=score)


def card_rows(name="次元战舰", title="星天·开拓的考验", kind="平行迷宫", state="未达成", y=220):
    return [row(title, y), row(f"通关{kind}「{name}」", y + 55), row("奖励", y + 100),
            row(state, y + 108, 1027)]


NORMAL = DungeonTrial("开拓的考验", "平行迷宫", "时层回廊", "", False)
STAR = DungeonTrial("星天开拓的考验", "平行迷宫", "次元战舰", "", False)
ALIEN = DungeonTrial("星天踏破的考验", "异境", "巴尔沃基地区", "", False)
PERIOD = "2026/09/30"
CATALOG = json.loads((Path(__file__).resolve().parents[1] / "agent/data/dungeons.json").read_text(encoding="utf-8"))


class CardTests(unittest.TestCase):
    def test_reads_normal_star_and_alien_cards(self):
        self.assertEqual(parse_cards(card_rows("时层回廊", "开拓的考验")), [NORMAL])
        self.assertEqual(parse_cards(card_rows()), [STAR])
        self.assertEqual(parse_cards(card_rows("巴尔沃基地区", "星天·踏破的考验", "异境")), [ALIEN])

    def test_completed_and_claimed_need_their_own_button(self):
        for state in ("领取奖励", "已领取奖励"):
            self.assertEqual(parse_cards(card_rows(state=state)), [replace(STAR, completed=True)])
        rows = card_rows()[:-1]
        for y in (135, 420, 550):
            self.assertEqual(parse_cards(rows + [row("领取奖励", y, 1027)]), [])

    def test_clipped_low_confidence_and_ambiguous_cards_are_not_actionable(self):
        self.assertEqual(parse_cards(card_rows()[1:]), [])
        self.assertEqual(parse_cards(card_rows()[:-1]), [])
        rows = card_rows()
        rows[1].score = 0.5
        self.assertEqual(parse_cards(rows), [])
        self.assertEqual(parse_cards(card_rows() + [row("领取奖励", 350, 1027)]), [])

    def test_split_ocr_and_quote_variants(self):
        rows = [row("星天 ・", 220), row("开拓的考验", 223, 550),
                row("通关平行迷宫", 277), row("“次元 战舰”", 274, 650), row("未达成", 328, 1027)]
        self.assertEqual(parse_cards(rows), [STAR])

    def test_other_monthly_tasks_are_not_dungeons(self):
        self.assertEqual(parse_cards([row("星天·冒险的考验", 220),
                                     row("开始任务「次元战舰」", 275), row("未达成", 328, 1027)]), [])

    def test_difficulty_is_not_ignored(self):
        rows = card_rows()
        rows[1].text += "（非常困难）"
        self.assertEqual(parse_cards(rows), [replace(STAR, difficulty="非常困难")])

    def test_same_text_at_different_positions_is_not_list_boundary(self):
        a = card_rows()
        self.assertTrue(same_rows(a, list(reversed(a))))
        self.assertFalse(same_rows(a, card_rows(y=410)))
        self.assertFalse(same_rows([], []))


class MatchingTests(unittest.TestCase):
    def test_uses_current_skip_catalog_and_prefers_hard(self):
        for card in (NORMAL, STAR):
            target, reason = match_dungeon(card, CATALOG)
            self.assertEqual(target["name"], card.name)
            self.assertEqual(target["difficulty"], "困难")
            self.assertEqual(target["ticket_cost"], 1)
            self.assertEqual(reason, "")
        self.assertIsNone(match_dungeon(ALIEN, CATALOG)[0])

    def test_names_are_exact_and_difficulty_is_respected(self):
        self.assertIsNone(match_dungeon(replace(STAR, name="次元战"), CATALOG)[0])
        self.assertIsNone(match_dungeon(replace(STAR, name="次元战舰方舟"), CATALOG)[0])
        self.assertEqual(match_dungeon(replace(STAR, difficulty="非常困难"), CATALOG)[0]["difficulty"], "非常困难")
        self.assertIsNone(match_dungeon(replace(STAR, kind="异境"), CATALOG)[0])

    def test_same_name_different_routes_are_ignored(self):
        self.assertIsNone(match_dungeon(replace(STAR, name="扭曲的大漩涡"), CATALOG)[0])


class FlowTests(unittest.TestCase):
    def scanner(self, pages, start=0):
        nav = TrialDungeonNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.open_trials = Mock()
        nav.frame = Mock(return_value=None)
        nav.rows = Mock(return_value=[row(PERIOD + " 23:59", 520)])
        position = [start]
        nav.page_rows = Mock(side_effect=lambda period: pages[position[0]])

        def scroll(node, period, previous):
            position[0] = max(0, min(len(pages) - 1, position[0] + (1 if node.endswith("Down") else -1)))
            current = pages[position[0]]
            return current, same_rows(previous, current)
        nav.scroll = Mock(side_effect=scroll)
        return nav

    def test_scans_from_arbitrary_position_and_requires_three_complete_cards(self):
        pages = [card_rows("时层回廊", "开拓的考验"), card_rows(),
                 card_rows("巴尔沃基地区", "星天·踏破的考验", "异境")]
        nav = self.scanner(pages, start=2)
        with patch("monthly_dungeons.time.sleep"):
            self.assertEqual(nav.read_dungeons(), ([NORMAL, STAR, ALIEN], PERIOD))
        nav = self.scanner(pages[:2])
        with patch("monthly_dungeons.time.sleep"), self.assertRaisesRegex(RuntimeError, "只确认 2 个"):
            nav.read_dungeons()

    def test_partial_card_is_read_on_next_overlapping_page(self):
        pages = [card_rows("时层回廊", "开拓的考验") + card_rows(y=600)[:2], card_rows(),
                 card_rows("巴尔沃基地区", "星天·踏破的考验", "异境")]
        nav = self.scanner(pages)
        with patch("monthly_dungeons.time.sleep"):
            self.assertEqual(nav.read_dungeons()[0], [NORMAL, STAR, ALIEN])

    def test_unstable_second_read_fails(self):
        nav = self.scanner([card_rows()])
        nav.page_rows.side_effect = [card_rows(), card_rows(state="领取奖励")]
        with patch("monthly_dungeons.time.sleep"), self.assertRaisesRegex(RuntimeError, "连续两次"):
            nav.read_dungeons()

    def test_verification_handles_reordering_and_rejects_reset_or_no_progress(self):
        before = [NORMAL, STAR, ALIEN]
        after = [ALIEN, replace(STAR, completed=True), NORMAL]
        verify_snapshot(before, after, PERIOD, PERIOD, STAR.key)
        for current, period in ((before, PERIOD), (after, "2026/10/31"),
                                ([NORMAL, ALIEN, replace(STAR, name="月影森林", completed=True)], PERIOD)):
            with self.assertRaises(RuntimeError):
                verify_snapshot(before, current, PERIOD, period, STAR.key)
        with self.assertRaises(RuntimeError):
            verify_snapshot(after, before, PERIOD, PERIOD)

    def navigator(self, snapshots):
        nav = TrialDungeonNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.read_dungeons = Mock(side_effect=[(cards, PERIOD) for cards in snapshots])
        for method in ("close_progress", "pipeline", "wait", "action", "world"):
            setattr(nav, method, Mock())
        return nav

    def test_each_target_once_then_verifies_and_keeps_unsupported(self):
        nav = self.navigator([[NORMAL, STAR, ALIEN], [replace(NORMAL, completed=True), STAR, ALIEN],
                              [ALIEN, replace(NORMAL, completed=True), replace(STAR, completed=True)]])
        with patch("monthly_dungeons.DungeonNavigator") as ctor:
            ctor.return_value.skip.return_value = 1
            self.assertTrue(nav.run_dungeons(CATALOG))
            self.assertEqual([c.args[0]["name"] for c in ctor.return_value.skip.call_args_list],
                             ["时层回廊", "次元战舰"])
            self.assertEqual([c.args[1] for c in ctor.return_value.skip.call_args_list], [1, 1])
        self.assertEqual(nav.close_progress.call_count, 2)

    def test_completed_rerun_has_no_inputs(self):
        nav = self.navigator([[replace(NORMAL, completed=True), replace(STAR, completed=True), ALIEN]])
        with patch("monthly_dungeons.DungeonNavigator") as ctor:
            self.assertTrue(nav.run_dungeons(CATALOG))
            ctor.assert_not_called()
        nav.close_progress.assert_not_called()

    def test_disabled_button_is_ignored_but_other_failures_propagate(self):
        cards = [NORMAL, replace(STAR, completed=True), ALIEN]
        nav = self.navigator([cards, cards])
        with patch("monthly_dungeons.DungeonNavigator") as ctor:
            ctor.return_value.skip.side_effect = DungeonSkipUnavailable("disabled")
            self.assertTrue(nav.run_dungeons(CATALOG))
            ctor.return_value.skip.assert_called_once()
        nav.action.assert_called_once_with("MonthlyDungeonCloseMenu")
        nav = self.navigator([cards])
        with patch("monthly_dungeons.DungeonNavigator") as ctor:
            ctor.return_value.skip.side_effect = RuntimeError("猫掌特急券不足")
            with self.assertRaisesRegex(RuntimeError, "猫掌"):
                nav.run_dungeons(CATALOG)
        nav.action.assert_not_called()

    def test_no_progress_never_spends_again(self):
        cards = [NORMAL, STAR, ALIEN]
        nav = self.navigator([cards, cards])
        with patch("monthly_dungeons.DungeonNavigator") as ctor:
            ctor.return_value.skip.return_value = 1
            with self.assertRaisesRegex(RuntimeError, "仍未达成"):
                nav.run_dungeons(CATALOG)
            ctor.return_value.skip.assert_called_once()

    def test_stop_and_timeout_send_no_inputs(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=True), run_action=Mock())
        nav = TrialDungeonNavigator(context)
        with self.assertRaisesRegex(RuntimeError, "停止"):
            nav.action("MonthlyDungeonScrollDown")
        context.run_action.assert_not_called()
        context.tasker.stopping = False
        nav.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError):
            nav.frame()

    def test_invalid_parameters_do_not_start_navigation(self):
        with patch("monthly_dungeons.TrialDungeonNavigator") as ctor:
            for params in ([], {"max_minutes": True}, {"max_minutes": 0}, {"max_minutes": 121}):
                self.assertFalse(MonthlyTrialDungeons().run(None, SimpleNamespace(custom_action_param=json.dumps(params))))
            ctor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
