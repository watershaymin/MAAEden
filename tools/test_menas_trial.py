"""梅纳斯次数、票券读取和逐场结算的回归检查。"""

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from menas_trial import MenasNavigator, MenasTrial, ROUND_NODES, parse_count, parse_tickets


class Parameters(unittest.TestCase):
    def test_default_zero_and_integer_strings(self):
        self.assertEqual(parse_count({}), 0)
        for count in [0, 1, 999, "0", "12", "999"]:
            self.assertEqual(parse_count({"count": count}), int(count))

    def test_rejects_invalid_counts(self):
        for count in [-1, 1000, 1.5, True, False, None, "01", "1.0", "-1", ""]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                parse_count({"count": count})
        with self.assertRaises(ValueError):
            parse_count([])

    def test_ticket_label_is_required_and_zero_is_valid(self):
        for text, expected in [("入场券持有量: 3/10", 3), ("入场券持有量：0/10", 0),
                               ("入场券持有量：12/10", 12)]:
            self.assertEqual(parse_tickets([SimpleNamespace(text=text, score=1)]), expected)
        for text in ["3/10", "入场券持有量：O/10", "入场券持有量：1/0", "入场券持有量：-1/10"]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                parse_tickets([SimpleNamespace(text=text, score=1)])
        with self.assertRaises(RuntimeError):
            parse_tickets([SimpleNamespace(text="入场券持有量：3/10", score=0.7)])


class Counting(unittest.TestCase):
    def navigator(self, tickets):
        nav = MenasNavigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.prepare = Mock(side_effect=tickets)
        nav.pipeline = Mock()
        return nav

    def test_zero_consumes_initial_tickets_and_stops_after_last_settlement(self):
        nav = self.navigator([3, 2, 1])
        self.assertEqual(nav.run_trials(0), 3)
        self.assertEqual(nav.prepare.call_count, 3)
        self.assertEqual(nav.pipeline.call_count, 3)
        nav.pipeline.assert_called_with("MenasTrialRunOnce", "MenasTrialComplete")

    def test_requested_count_keeps_remaining_tickets(self):
        nav = self.navigator([5, 4])
        self.assertEqual(nav.run_trials(2), 2)
        self.assertEqual(nav.pipeline.call_count, 2)

    def test_insufficient_tickets_never_submit_extra_run(self):
        nav = self.navigator([1])
        self.assertEqual(nav.run_trials(3), 1)
        self.assertEqual(nav.pipeline.call_count, 1)

    def test_no_tickets_closes_stage_without_challenging(self):
        nav = self.navigator([0])
        self.assertEqual(nav.run_trials(0), 0)
        nav.pipeline.assert_called_once_with("MenasTrialClose", "MenasTrialComplete")

    def test_unchanged_or_unexpected_quantity_stops_before_next_challenge(self):
        for remaining in [3, 0, 4]:
            nav = self.navigator([3, remaining])
            with self.subTest(remaining=remaining), self.assertRaisesRegex(RuntimeError, "入场券变化不符"):
                nav.run_trials(0)
            self.assertEqual(nav.pipeline.call_count, 1)

    def test_settlement_failure_does_not_start_another_round(self):
        nav = self.navigator([3])
        nav.pipeline.side_effect = RuntimeError("settlement failed")
        with self.assertRaisesRegex(RuntimeError, "settlement"):
            nav.run_trials(0)
        self.assertEqual(nav.prepare.call_count, 1)

    def test_prepare_resets_round_limits_and_rejects_inconsistent_ocr(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False), clear_hit_count=Mock(return_value=True))
        nav = MenasNavigator(context)
        nav.pipeline = Mock()
        nav.frame = Mock(return_value="stage")
        def reading(count):
            return SimpleNamespace(all_results=[SimpleNamespace(text=f"入场券持有量：{count}/10", score=1)])
        nav.reco = Mock(side_effect=[True, reading(3), True, reading(2)])
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            nav.prepare()
        self.assertEqual([c.args[0] for c in context.clear_hit_count.call_args_list], list(ROUND_NODES))

    def test_failed_pipeline_even_with_completion_name_is_rejected(self):
        result = SimpleNamespace(status=SimpleNamespace(succeeded=False),
                                 nodes=[SimpleNamespace(name="MenasTrialComplete")])
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False), run_task=Mock(return_value=result))
        with self.assertRaisesRegex(RuntimeError, "未完成"):
            MenasNavigator(context).pipeline("MenasTrialRunOnce", "MenasTrialComplete")

    def test_stop_and_timeout_do_not_send_inputs(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=True), run_task=Mock(), clear_hit_count=Mock())
        nav = MenasNavigator(context)
        with self.assertRaisesRegex(RuntimeError, "用户停止"):
            nav.prepare()
        context.clear_hit_count.assert_not_called()
        context.tasker.stopping = False
        nav.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(RuntimeError, "时间上限"):
            nav.pipeline("MenasTrialRunOnce", "MenasTrialComplete")
        context.run_task.assert_not_called()

    def test_partial_requested_count_does_not_report_success(self):
        with patch("menas_trial.MenasNavigator") as ctor:
            ctor.return_value.run_trials.return_value = 1
            self.assertFalse(MenasTrial().run(None, SimpleNamespace(custom_action_param='{"count": 3}')))
            self.assertTrue(MenasTrial().run(None, SimpleNamespace(custom_action_param='{"count": 0}')))


if __name__ == "__main__":
    unittest.main()
