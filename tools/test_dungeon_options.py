"""使用 Maa 原生多段 Pipeline 覆盖验证客户端副本配置，不连接游戏。"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from dungeons import parse_refill_policy, parse_skip_plan, read_interface_options


class NoGameController(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'dungeon-option-test'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720, 1280, 3), dtype=np.uint8)


class CaptureOptions(CustomAction):
    def run(self, context, argv):
        try:
            params = read_interface_options(context, json.loads(argv.custom_action_param), self.catalog)
            self.result = (parse_skip_plan(params, self.catalog), parse_refill_policy(params))
            return True
        except Exception as exc:
            self.error = exc
            return False


class NativeDungeonOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = json.loads((ROOT / 'assets/interface.json').read_text(encoding='utf-8'))
        cls.catalog = json.loads((ROOT / 'agent/data/dungeons.json').read_text(encoding='utf-8'))
        Toolkit.init_option(ROOT / 'debug/dungeons/option-regression')
        cls.probe = CaptureOptions()
        cls.probe.catalog = cls.catalog
        cls.resource = Resource()
        assert cls.resource.register_custom_action('CaptureDungeonOptions', cls.probe)
        assert cls.resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
        cls.controller = NoGameController()
        assert cls.controller.post_connection().wait().succeeded
        cls.tasker = Tasker()
        assert cls.tasker.bind(cls.resource, cls.controller)

    def run_options(self, overrides):
        self.probe.result = self.probe.error = None
        job = self.tasker.post_task('DungeonSkip', [*overrides, {
            'DungeonSkip': {'custom_action': 'CaptureDungeonOptions', 'next': [], 'post_delay': 0},
        }]).wait()
        self.assertIsNone(self.probe.error)
        self.assertTrue(job.succeeded)
        self.assertIsNotNone(self.probe.result)
        return self.probe.result

    def case(self, name, index):
        return self.interface['option'][name]['cases'][index]['pipeline_override']

    def count(self, name, value):
        override = self.interface['option'][name]['pipeline_override']
        return json.loads(json.dumps(override).replace('"{count}"', str(value)))

    def test_two_targets_routes_counts_and_refills_survive_native_overrides(self):
        overrides, expected = [], []
        for ticket, route_index, count in [('red', -1, 2), ('green', 1, 3)]:
            name = 'Dungeon' + ticket.title()
            case = next(c for c in self.interface['option'][name + 'Target']['cases'] if c.get('option'))
            route = self.interface['option'][case['option'][0]]['cases'][route_index]
            expected.append((case['name'], route['name'], count))
            overrides.extend([case['pipeline_override'], route['pipeline_override'], self.count(name + 'Count', count)])
        overrides.extend(self.case('DungeonRefill' + ticket, index) for ticket, index in [('Red', 1), ('Green', 0), ('Cat', 1)])
        plan, policy = self.run_options(overrides)
        self.assertEqual([(t['id'], t['skip_route_id'], count) for t, count in plan], expected)
        self.assertEqual(policy, {'red': True, 'green': False, 'cat': True})
        # 后一任务没有选这些选项时，不得继承前一任务覆盖。
        plan, policy = self.run_options([])
        self.assertEqual([(t['id'], count) for t, count in plan], [('snake_damak_vh', 4), ('moon_forest_h', 4)])
        self.assertEqual(policy, {'red': False, 'green': False, 'cat': False})

    def test_legacy_target_count_and_route_still_make_one_group(self):
        case = next(c for c in self.interface['option']['DungeonTarget']['cases'] if c.get('option'))
        route = self.interface['option'][case['option'][0]]['cases'][-1]
        plan, _ = self.run_options([case['pipeline_override'], route['pipeline_override'], self.count('DungeonCount', 2)])
        self.assertEqual([(t['id'], t['skip_route_id'], count) for t, count in plan], [(case['name'], route['name'], 2)])

    def test_cli_override_ignores_interface_settings(self):
        plan, _ = self.run_options([self.count('DungeonRedCount', 9), {
            'DungeonSkip': {'custom_action_param': {'red_count': 0, 'green_count': 1}},
        }])
        self.assertEqual([(t['id'], count) for t, count in plan], [('moon_forest_h', 1)])


if __name__ == '__main__':
    unittest.main()
