"""不连接设备：月度试炼卡片归属、结算去重、进度回退与停止保护。"""

import sys
import time
import unittest
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from monthly_trial import (MonthlyNavigator, MonthlyStarTrial, VictoryCounter,
                           parse_period, parse_progress, verify_progress, nest_player_position)


def row(text, y=350, x=470):
    return SimpleNamespace(text=text, box=[x, y, 340, 28], score=0.99)


class MonthlyTrialTests(unittest.TestCase):
    def test_gold_ring_rejects_other_colors_and_multiple_markers(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        def ring(x, color):
            yy, xx = np.ogrid[:720, :1280]
            radius = (xx - x) ** 2 + (yy - 402) ** 2
            frame[(radius >= 36) & (radius <= 64)] = color
        ring(675, (40, 200, 245))
        self.assertEqual(nest_player_position(frame), (675, 402))
        ring(710, (40, 200, 245))
        self.assertIsNone(nest_player_position(frame))
        frame[:] = 0
        ring(675, (230, 80, 240))
        self.assertIsNone(nest_player_position(frame))

    def test_200_card_requires_own_star_title(self):
        title = row("星天 · 战士的考验")
        for value in (0, 1, 199, 200):
            self.assertEqual(parse_progress([title, row(f"获得200场战斗的胜利 （{value}/200）", 402)]), value)
        for rows in ([row("战士的考验"), row("获得200场战斗的胜利 (12/200)", 402)],
                     [title, row("获得200场战斗的胜利 (12/200)", 600)],
                     [title, row("获得25场战斗的胜利 (12/25)", 402)],
                     [row("获得200场战斗的胜利 (12/200)", 402)]):
            self.assertIsNone(parse_progress(rows))

    def test_invalid_or_ambiguous_card_rejected(self):
        title = row("星天·战士的考验")
        with self.assertRaises(ValueError):
            parse_progress([title, row("获得200场战斗的胜利 (201/200)", 402)])
        with self.assertRaises(ValueError):
            parse_progress([title, row("获得200场战斗的胜利 (12/200)", 402),
                            row("获得200场战斗的胜利 (13/200)", 403)])

    def test_completed_card_hides_fraction_and_requires_own_claim_button(self):
        card = [row("星天·战士的考验", 425), row("获得200场战斗的胜利", 475)]
        self.assertEqual(parse_progress(card + [row("领取奖励", 535, 1025)]), 200)
        for button in (row("领取奖励", 342, 1025), row("领取奖励", 725, 1025),
                       row("领取奖励", 535), row("未达成", 535, 1025)):
            self.assertIsNone(parse_progress(card + [button]))

    def test_period_and_server_progress_guard(self):
        self.assertEqual(parse_period([row("2026/09/30 23:59")]), "2026/09/30")
        with self.assertRaises(ValueError):
            parse_period([row("未知")])
        verify_progress(175, 200, "2026/09/30", "2026/09/30")
        for current, period in [(10, "2026/09/30"), (25, "2026/09/30"), (50, "2026/10/31")]:
            with self.assertRaises(RuntimeError):
                verify_progress(25, current, "2026/09/30", period)

    def test_rewards_count_once_after_world_returns(self):
        counter = VictoryCounter()
        for state in ["world", "battle", "battle", "rewards", "rewards"]:
            self.assertEqual(counter.observe(state), 0)
        self.assertEqual(counter.observe("world"), 1)
        self.assertEqual(counter.observe("world"), 1)
        # 开场自动伤害可能跳过可操作战斗画面，但真实结算仍计为一胜。
        counter.observe("rewards")
        self.assertEqual(counter.observe("world"), 2)

    def test_battle_without_rewards_is_not_victory(self):
        counter = VictoryCounter()
        counter.observe("battle")
        with self.assertRaises(RuntimeError):
            counter.observe("world")
        self.assertEqual(counter.wins, 0)

    def test_stop_and_deadline_send_no_inputs(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=True), run_action=Mock(), run_task=Mock())
        nav = MonthlyNavigator(context)
        for operation in (lambda: nav.action("MonthlyAttack"), lambda: nav.pipeline("MonthlyOpenTrials")):
            with self.assertRaises(RuntimeError):
                operation()
        context.run_action.assert_not_called()
        context.run_task.assert_not_called()
        context.tasker.stopping = False
        nav.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError):
            nav.frame()

    def test_completed_month_never_navigates_or_farms(self):
        with patch("monthly_trial.MonthlyNavigator") as ctor:
            ctor.return_value.read_progress.return_value = (200, "2026/09/30")
            self.assertTrue(MonthlyStarTrial().run(None, SimpleNamespace(custom_action_param='{}')))
            ctor.return_value.enter_nest.assert_not_called()
            ctor.return_value.farm.assert_not_called()

    def test_menu_animation_does_not_click_menu_twice(self):
        nav = MonthlyNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.frame = Mock(side_effect=[{"MonthlyOpenMenu"}, {"MonthlyOpenMenu"},
                                     {"MonthlyOpenRecords"}, {"MonthlyOpenMedals"},
                                     {"MonthlySelectTrials"}, {"MonthlyTrialsReady"},
                                     set(), {"MonthlyTrialsReady"}, set()])
        nav.reco = lambda node, frame: node in frame
        nav.action = Mock()
        nav.wait = Mock()
        nav.rows = lambda node, frame: ([row("2026/09/30 23:59")] if node == "MonthlyReadPeriod"
                                      else [row("星天·战士的考验"), row("获得200场战斗的胜利 (68/200)", 402)])
        with patch("monthly_trial.time.sleep"):
            self.assertEqual(nav.read_progress(), (68, "2026/09/30"))
        self.assertEqual([call.args[0] for call in nav.action.call_args_list],
                         ["MonthlyOpenMenu", "MonthlyOpenRecords", "MonthlyOpenMedals", "MonthlySelectTrials"])

    def test_navigation_wins_reduce_next_batch(self):
        with patch("monthly_trial.MonthlyNavigator") as ctor:
            nav = ctor.return_value
            nav.read_progress.side_effect = [(190, "2026/09/30"), (200, "2026/09/30")]
            nav.counter.wins = 0
            nav.enter_nest.side_effect = lambda: setattr(nav.counter, "wins", 3)
            self.assertTrue(MonthlyStarTrial().run(None, SimpleNamespace(custom_action_param='{}')))
            nav.farm.assert_called_once_with(7)

    def test_ignored_trial_tab_click_has_bounded_retry(self):
        nav = MonthlyNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        clock = [100]
        def frame():
            clock[0] += 11
            return {"MonthlySelectTrials"}
        nav.frame = frame
        nav.reco = lambda node, image: node in image
        nav.action = Mock()
        with patch("monthly_trial.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, "菜单跳转未完成"):
                nav.read_progress()
        self.assertEqual([call.args[0] for call in nav.action.call_args_list], ["MonthlySelectTrials"] * 3)

    def test_wins_before_initial_snapshot_are_not_counted_twice(self):
        with patch("monthly_trial.MonthlyNavigator") as ctor:
            nav = ctor.return_value
            nav.counter.wins = 8
            nav.read_progress.side_effect = [(190, "2026/09/30"), (200, "2026/09/30")]
            self.assertTrue(MonthlyStarTrial().run(None, SimpleNamespace(custom_action_param='{}')))
            nav.farm.assert_called_once_with(10)

    def test_bad_params_cannot_escape_callback(self):
        for params in ('{"max_minutes":true}', '{"max_minutes":0}', '{"max_minutes":1000}', '[]', '{'):
            with patch("monthly_trial.MonthlyNavigator") as ctor:
                self.assertFalse(MonthlyStarTrial().run(None, SimpleNamespace(custom_action_param=params)))
                ctor.assert_not_called()

    def test_interrupted_move_can_retry_but_wall_and_reverse_cannot(self):
        nav = MonthlyNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.world = Mock()
        nav.action = Mock()
        nav.position = Mock(return_value=("魔物巢穴", (670, 402)))
        with self.assertRaises(RuntimeError):
            nav.move("right", 600, "魔物巢穴", (670, 402))

        def battle_interrupted():
            nav.counter.wins += 1
            return "魔物巢穴", (670, 402)

        nav.position.side_effect = lambda _: battle_interrupted()
        self.assertEqual(nav.move("right", 600, "魔物巢穴", (670, 402)), (670, 402))
        nav.position.side_effect = None
        nav.position.return_value = ("魔物巢穴", (660, 402))
        with self.assertRaises(RuntimeError):
            nav.move("right", 600, "魔物巢穴", (670, 402))

    def test_battle_after_map_opens_restarts_localization(self):
        nav = MonthlyNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.world = Mock()
        nav.action = Mock()
        nav.frame = Mock(side_effect=[{"MonthlyLocalMap", "MonthlyTowerMapTitle"},
                                     {"MonthlyRewards"},
                                     {"MonthlyLocalMap", "MonthlyTowerMapTitle", "MonthlyPlayer"}])
        marker = SimpleNamespace(box=SimpleNamespace(x=700, y=392, w=20, h=20), filtered_results=[])
        nav.reco = lambda node, frame, override=None: (marker if node == "MonthlyPlayer" else True) if node in frame else None
        nav.rows = Mock(return_value=[row("魔物巢穴")])
        with patch("monthly_trial.time.sleep"), patch("monthly_trial.nest_player_position", return_value=None):
            self.assertEqual(nav.position("魔物巢穴"), ("魔物巢穴", (710, 402)))
        self.assertEqual(nav.action.call_count, 3)  # 打开、战斗后重新打开、成功后关闭。
        self.assertEqual(nav.action.call_args.args, ("MonthlyCloseLocalMap",))
        self.assertEqual(nav.world.call_count, 4)

    def test_route_rechecks_after_each_step(self):
        nav = MonthlyNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.position = Mock(return_value=("第1层", (653, 530)))
        nav.move = Mock(return_value=(653, 445))
        self.assertEqual(nav.route([((653, 445), 5)], "第1层"), (653, 445))
        nav.move.assert_called_once_with("up", 600, "第1层", (653, 530))


if __name__ == "__main__":
    unittest.main()
