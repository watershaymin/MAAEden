"""验证谜晶规则的 AND/OR 边界、实测 OCR、锁定幂等性与消耗计数。"""

import json
import itertools
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))
from menas_appraisal import (AppraisalRunner, MenasAppraisal, Weapon, load_catalog, matches,
                            parse_affixes, parse_main, parse_quantity, parse_rules, parse_stock)
from update_menas_appraisal_options import generate


def row(text, x=0, y=0, w=50, h=22, score=.999):
    return SimpleNamespace(text=text, box=[x, y, w, h], score=score)


class RuleTests(unittest.TestCase):
    def weapon(self, attack=200, magic=100, affixes=("全状态20UP",), kind="剑"):
        return Weapon(kind, attack, magic, affixes)

    def rules(self, **kwargs):
        return parse_rules({"attack_min": 200, **kwargs})

    def test_inclusive_and_zero_disabled(self):
        self.assertTrue(matches(self.weapon(), self.rules()))
        self.assertFalse(matches(self.weapon(199), self.rules()))
        self.assertFalse(matches(self.weapon(199), self.rules(condition_mode="any")))

    def test_numeric_any_all(self):
        self.assertTrue(matches(self.weapon(), self.rules(magic_min=200)))
        self.assertFalse(matches(self.weapon(), self.rules(magic_min=200, stat_mode="all")))

    def test_affix_only_empty_stats_not_true(self):
        rules = self.rules(attack_min=0, affixes={"all_stats_20": True}, condition_mode="any")
        self.assertFalse(matches(self.weapon(affixes=()), rules))
        self.assertTrue(matches(self.weapon(affixes=("全状态20UP",)), rules))

    def test_affix_all_any(self):
        params = {"attack_min": 0, "affixes": {"all_stats_20": True, "resist_all": True}}
        self.assertFalse(matches(self.weapon(), self.rules(**params)))
        self.assertTrue(matches(self.weapon(), self.rules(**params, affix_mode="any")))

    def test_groups_all_any(self):
        params = {"affixes": {"all_stats_20": True}}
        self.assertFalse(matches(self.weapon(199), self.rules(**params)))
        self.assertTrue(matches(self.weapon(199), self.rules(**params, condition_mode="any")))

    def test_weapon_filter_always_applies(self):
        rules = self.rules(weapons={"staff": True}, condition_mode="any")
        self.assertFalse(matches(self.weapon(), rules))
        self.assertTrue(matches(self.weapon(kind="杖"), rules))

    def test_extra_affix_exact_and_normalized(self):
        rules = self.rules(attack_min=0, extra_affixes="暴击威力＋40％； 胜利时回复20%Another Force")
        self.assertTrue(matches(self.weapon(affixes=("暴击威力+40%", "胜利时回复20%AnotherForce")), rules))
        self.assertFalse(matches(self.weapon(affixes=("暴击威力+4%", "胜利时回复20%AnotherForce")), rules))

    def test_collect_only_never_locks(self):
        self.assertFalse(matches(self.weapon(), parse_rules({"auto_lock": False})))

    def test_invalid_rules_rejected_before_navigation(self):
        for params in ({}, {"attack_min": True}, {"batches": -1}, {"batches": "01"},
                       {"attack_min": 10000}, {"auto_lock": "false"}, {"affixes": []},
                       {"affixes": {"typo": True}}, {"affixes": {"all_stats_20": 1}},
                       {"stat_mode": "xor"}, {"typo": 123}, {"extra_affixes": 123}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                parse_rules(params)
        with patch("menas_appraisal.AppraisalRunner") as runner:
            self.assertFalse(MenasAppraisal().run(None, SimpleNamespace(custom_action_param="{}")))
            runner.assert_not_called()

    def test_gui_every_case_changes_its_rule(self):
        options = generate(load_catalog())
        for case in options["MenasAppraisalAffixes"]["cases"]:
            params = case["pipeline_override"]["MenasAppraisal"]["custom_action_param"]
            rules = parse_rules(params)
            self.assertTrue(matches(self.weapon(affixes=(case["label"],)), rules))
            self.assertFalse(matches(self.weapon(affixes=()), rules))


class DefaultPresetTests(unittest.TestCase):
    AFFIXES = ("中毒时强化+30%", "疼痛时强化+30%", "HP最大时伤害+25%",
               "暴击威力+40%", "全属性攻击力+25%")

    def test_all_affix_combinations_and_weapon_stat_boundaries(self):
        rules = parse_rules({"rule_mode": "poison_pain"})
        # 从用户列出的组合展开成七组允许集合，独立核对全部32种词条组合。
        accepted = ({0, 1}, {0, 2, 3}, {0, 2, 4}, {0, 3, 4},
                    {1, 2, 3}, {1, 2, 4}, {1, 3, 4})
        for bits in itertools.product((False, True), repeat=5):
            indices = {i for i, selected in enumerate(bits) if selected}
            affixes = tuple(self.AFFIXES[i] for i in indices)
            affix_match = any(required <= indices for required in accepted)
            for kind in "杖剑刀斧枪弓拳锤":
                for attack, magic in itertools.product((210, 211), repeat=2):
                    with self.subTest(affixes=affixes, kind=kind, attack=attack, magic=magic):
                        expected_stat = magic == 211 if kind == "杖" else attack == 211
                        self.assertEqual(matches(Weapon(kind, attack, magic, affixes), rules),
                                         expected_stat and affix_match)

    def test_duplicate_bonus_does_not_count_twice(self):
        weapon = Weapon("剑", 250, 250, (self.AFFIXES[0], self.AFFIXES[2], self.AFFIXES[2]))
        self.assertFalse(matches(weapon, parse_rules({"rule_mode": "poison_pain"})))

    def test_threshold_option_and_existing_switches(self):
        weapon = Weapon("杖", 999, 211, self.AFFIXES[:2])
        self.assertTrue(matches(weapon, parse_rules({"rule_mode": "poison_pain"})))
        self.assertFalse(matches(weapon, parse_rules({"rule_mode": "poison_pain", "primary_above": 211})))
        self.assertFalse(matches(weapon, parse_rules({"rule_mode": "poison_pain", "auto_lock": False})))
        self.assertFalse(matches(weapon, parse_rules({"rule_mode": "poison_pain", "weapons": {"sword": True}})))
        for params in ({"rule_mode": "typo"}, {"primary_above": True},
                       {"primary_above": -1}, {"primary_above": "210.0"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                parse_rules({"rule_mode": "poison_pain", **params})

    def test_pipeline_and_gui_default_agree(self):
        pipeline = json.loads((ROOT / "assets/resource/pipeline/menas_appraisal.json").read_text(encoding="utf-8"))
        base = pipeline["MenasAppraisal"]["custom_action_param"]
        options = generate(load_catalog())
        mode = options["MenasAppraisalRuleMode"]
        case = next(c for c in mode["cases"] if c["name"] == mode["default_case"])
        gui_params = {**base, **case["pipeline_override"]["MenasAppraisal"]["custom_action_param"]}
        field = options["MenasAppraisalPrimaryStat"]["inputs"][0]
        gui_params[field["name"]] = int(field["default"])
        self.assertEqual(parse_rules(base), parse_rules(gui_params))
        self.assertEqual(parse_rules(base).rule_mode, "poison_pain")
        self.assertEqual(parse_rules(base).primary_above, 210)
        custom = next(c for c in mode["cases"] if c["name"] == "custom")
        custom_params = {**gui_params, **custom["pipeline_override"]["MenasAppraisal"]["custom_action_param"],
                         "attack_min": 200}
        self.assertEqual(parse_rules(custom_params).rule_mode, "custom")
        self.assertTrue(matches(Weapon("剑", 200, 50, ()), parse_rules(custom_params)))


class OCRTests(unittest.TestCase):
    def test_main_numbers_and_confidence(self):
        rows = [row("谜晶之杖", 70, 68), row("60", 433, 123),
                row("202", 423, 164), row("206", 423, 205)]
        self.assertEqual(parse_main(rows), ("杖", 202, 206))
        rows[-1].score = .7
        with self.assertRaises(RuntimeError):
            parse_main(rows)

    def test_stock_and_batch_quantity(self):
        self.assertEqual(parse_stock([row("持有数272")]), 272)
        self.assertEqual(parse_stock([row("持有数0")]), 0)
        self.assertEqual(parse_quantity([row("x 25", score=.90)]), 25)
        self.assertEqual(parse_quantity([row("× 7")]), 7)
        with self.assertRaises(RuntimeError):
            parse_quantity([row("x 25", score=.6)])

    def test_affix_fragments_and_missing_line(self):
        rows = [row("全状态20UP", 541, 320), row("胜利时回复20%", 541, 353),
                row("Another Force", 685, 353), row("-", 955, 353)]
        self.assertEqual(parse_affixes(rows), ("全状态20UP", "胜利时回复20%AnotherForce"))
        with self.assertRaises(RuntimeError):
            parse_affixes([rows[1]])
        with self.assertRaises(RuntimeError):
            parse_affixes([])

    def test_real_ocr_fixtures(self):
        cases = json.loads((ROOT / "tools/fixtures/menas_appraisal_ocr.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(list(parse_main([SimpleNamespace(**r) for r in case["main"]])), case["expected_main"])
                self.assertEqual(list(parse_affixes([SimpleNamespace(**r) for r in case["detail"]])), case["expected_affixes"])

    def test_all_observed_affixes_have_catalog_entries(self):
        samples = json.loads((ROOT / "tools/fixtures/menas_appraisal_samples.json").read_text(encoding="utf-8"))
        catalog = load_catalog()
        self.assertEqual(len(samples), catalog["weapons_observed"])
        counts = {a["name"]: sum(a["name"] in w["affixes"] for w in samples) for a in catalog["affixes"]}
        self.assertEqual(counts, {a["name"]: a["observed_count"] for a in catalog["affixes"]})
        self.assertEqual({a for w in samples for a in w["affixes"]}, set(counts))


class RunnerTests(unittest.TestCase):
    def runner(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        runner = AppraisalRunner(context)
        return runner

    def test_stop_and_deadline(self):
        runner = self.runner()
        runner.context.tasker.stopping = True
        with self.assertRaisesRegex(RuntimeError, "用户停止"):
            runner.check()
        runner.context.tasker.stopping = False
        runner.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(RuntimeError, "时间上限"):
            runner.check()

    def test_existing_lock_is_never_toggled(self):
        runner = self.runner()
        weapon = Weapon("弓", 178, 66, ("全状态20UP",))
        runner.main = Mock(return_value=("弓", 178, 66))
        runner.lock_state = Mock(return_value=True)
        runner.act = Mock()
        runner.lock(weapon)
        runner.act.assert_not_called()

    def test_lock_requires_notice_and_final_icon(self):
        runner = self.runner()
        runner.main = Mock(return_value=("弓", 178, 66))
        runner.lock_state = Mock(side_effect=[False, False])
        runner.act, runner.ready = Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, "图标"):
            runner.lock(Weapon("弓", 178, 66, ()))
        self.assertEqual([c.args[0] for c in runner.act.call_args_list], ["Lock", "AcknowledgeLock"])
        self.assertEqual(runner.ready.call_args_list[0].args, ("LockNotice",))

    def test_partial_batch_is_not_submitted(self):
        runner = self.runner()
        runner.ensure, runner.act = Mock(), Mock()
        runner.ready = Mock(return_value=object())
        runner.rows = Mock(return_value=[row("x 7")])
        with self.assertRaises(RuntimeError):
            runner.submit()
        self.assertEqual([c.args[0] for c in runner.act.call_args_list], ["Auto"])

    def test_scan_locks_only_matching_unlocked_weapons(self):
        runner = self.runner()
        high = Weapon("剑", 200, 100, ("全状态20UP",))
        low = Weapon("剑", 199, 100, ("全状态20UP",))
        runner.read_weapon = Mock(side_effect=[(high, False), (high, True), (low, False)] + [(low, True)] * 22)
        runner.report = {"weapons": []}
        runner.save, runner.lock = Mock(), Mock()
        runner.scan_batch(parse_rules({"attack_min": 200}), 1)
        runner.lock.assert_called_once_with(high)
        self.assertEqual(runner.read_weapon.call_count, 25)
        self.assertFalse(runner.report["weapons"][2]["locked_after"])
        self.assertTrue(runner.report["weapons"][3]["locked_after"])
        self.assertTrue(all(w["status"] == "done" for w in runner.report["weapons"]))

    def test_submit_timeout_records_uncertain_consumption_without_retry(self):
        runner = self.runner()
        runner.ensure, runner.act, runner.save = Mock(), Mock(), Mock()
        runner.ready = Mock(side_effect=[object(), RuntimeError("结果页超时")])
        runner.rows = Mock(return_value=[row("x 25")])
        runner.report = {"unconfirmed_consumption": False}
        with self.assertRaisesRegex(RuntimeError, "结果页超时"):
            runner.submit()
        self.assertTrue(runner.report["unconfirmed_consumption"])
        self.assertEqual([c.args[0] for c in runner.act.call_args_list], ["Auto", "Submit"])

    def run_mock(self, stocks, batches=0, scan_error=None):
        runner = self.runner()
        runner.open, runner.act, runner.ensure, runner.ready = Mock(), Mock(), Mock(), Mock()
        runner.stock = Mock(side_effect=stocks)
        runner.submit = Mock()
        runner.scan_batch = Mock(side_effect=scan_error)
        runner.save = Mock()
        with patch("menas_appraisal.Path.mkdir"):
            success = runner.run(parse_rules({"auto_lock": False, "batches": batches}))
        return runner, success

    def test_all_mode_uses_initial_complete_batches(self):
        runner, success = self.run_mock([52, 52, 27, 27, 2])
        self.assertTrue(success)
        self.assertEqual(runner.submit.call_count, 2)
        self.assertEqual(runner.report["consumed"], 50)
        self.assertEqual(runner.report["completed_batches"], 2)

    def test_insufficient_and_stock_drift_stop(self):
        runner, success = self.run_mock([24])
        self.assertTrue(success)
        runner.submit.assert_not_called()
        for stocks, batches in (([24], 1), ([50, 49], 0)):
            with self.assertRaises(RuntimeError):
                self.run_mock(stocks, batches)

    def test_failed_scan_keeps_result_and_does_not_consume_next_batch(self):
        runner = self.runner()
        runner.open, runner.act, runner.save = Mock(), Mock(), Mock()
        runner.stock = Mock(side_effect=[50, 50])
        runner.submit = Mock()
        runner.scan_batch = Mock(side_effect=RuntimeError("OCR 不确定"))
        with patch("menas_appraisal.Path.mkdir"), self.assertRaises(RuntimeError):
            runner.run(parse_rules({"auto_lock": False, "batches": 2}))
        runner.submit.assert_called_once()
        runner.act.assert_not_called()
        self.assertEqual(runner.report["completed_batches"], 0)
        self.assertEqual(runner.report["consumed"], 25)
        self.assertEqual(runner.report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
