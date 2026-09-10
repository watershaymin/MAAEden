"""副本参数和消耗约束的回归检查。"""
import sys
import json
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'agent'))
from dungeons import (DungeonNavigator, DungeonSkip, blank_map_point, parse_request, parse_refill_policy,
                      parse_skip_plan, read_interface_options, verify_party, proof_refill_allowed, refill_ticket)


OFFERS = {ticket: f'要使用1次导证之力，回复{label}吗？ 导证之力：剩余12次'
          for ticket, label in [('red', '红色解锁卡'), ('green', '绿色解锁卡'), ('cat', '猫掌特急券')]}


class FakeDungeon(DungeonNavigator):
    def __init__(self, frames):
        self.frames = iter(frames)
        self.actions = []

    def choose(self, target):
        self.actions.append('choose')

    def frame(self):
        return next(self.frames)

    def text(self, frame):
        return [SimpleNamespace(text=frame)]

    def reco(self, node, frame):
        if node == 'DungeonProofRefill':
            return frame in OFFERS.values()
        return node == frame

    def action(self, node, override=None):
        self.actions.append(node)

    def wait(self, node, seconds=10):
        self.actions.append(node)

    def refill(self, target, source_action, text, ticket):
        self.actions.append('refill:' + source_action + ':' + ticket)

    def select_skip_region(self, target, frame):
        self.actions.append('select-region')


class DungeonCounting(unittest.TestCase):
    def test_region_selection_does_not_count_and_resets_after_settlement(self):
        nav = FakeDungeon(['请选择区域。', 'DungeonContinuePage', 'transition',
                           '请选择区域。', 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id': 'entna'}, 2), 2)
        self.assertEqual(nav.actions.count('select-region'), 2)
        self.assertEqual(nav.actions.count('DungeonContinueSkip'), 1)

    def test_repeated_region_selection_stops(self):
        nav = FakeDungeon(['请选择区域。', '请选择区域。'])
        with self.assertRaisesRegex(RuntimeError, '重复出现区域选择'):
            nav.skip({'id': 'entna'}, 1)
        self.assertEqual(nav.actions.count('select-region'), 1)

    def test_ends_at_requested_count(self):
        nav = FakeDungeon(['DungeonContinuePage', 'DungeonCongratulations',
                           'DungeonCongratulations', 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 2), 2)
        self.assertEqual(nav.actions.count('DungeonContinueSkip'), 1)
        self.assertEqual(nav.actions[-2:], ['DungeonEndSkip', 'StartUpWorldReady'])

    def test_does_not_submit_another_skip_after_single_run(self):
        nav = FakeDungeon(['DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 1), 1)
        self.assertNotIn('DungeonContinueSkip', nav.actions)

    def test_stones_stop_without_confirmation(self):
        nav = FakeDungeon(['将消耗克洛诺斯之石补充解锁卡'])
        with self.assertRaisesRegex(RuntimeError, '克洛诺斯'):
            nav.skip({'id':'test'}, 1)
        self.assertEqual(nav.actions, ['choose', 'DungeonSkipActive'])

    def test_reward_bonus_is_not_a_refill_dialog(self):
        nav = FakeDungeon(['受「星天引导之证」之力的影响 获得量增加中',
                           'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 1), 1)

    def test_cat_voucher_refill_stops_without_spending(self):
        nav = FakeDungeon(['要使用1次导证之力，回复猫掌特急券吗？'])
        with self.assertRaisesRegex(RuntimeError, '猫掌特急券不足'):
            nav.skip({'id':'test'}, 1)
        self.assertEqual(nav.actions, ['choose', 'DungeonSkipActive'])

    def test_white_card_reward_does_not_add_a_run(self):
        nav = FakeDungeon(['DungeonWhiteCardReward', 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 1), 1)
        self.assertEqual(nav.actions.count('DungeonWhiteCardReward'), 1)

    def test_refill_does_not_increment_completed_count(self):
        nav = FakeDungeon(['DungeonContinuePage', OFFERS['red'],
                           OFFERS['red'], 'DungeonCongratulations', 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 2, {'red': True}), 2)
        self.assertEqual(nav.actions.count('refill:DungeonContinueSkip:red'), 1)

    def test_repeated_refill_without_completion_stops(self):
        nav = FakeDungeon([OFFERS['red'], OFFERS['red']])
        with self.assertRaisesRegex(RuntimeError, '再次要求补票'):
            nav.skip({'id':'test'}, 1, {'red': True})
        self.assertEqual(nav.actions.count('refill:DungeonSkipActive:red'), 1)

    def test_each_ticket_stops_when_disabled(self):
        for ticket in OFFERS:
            with self.subTest(ticket=ticket):
                nav = FakeDungeon([OFFERS[ticket]])
                with self.assertRaisesRegex(RuntimeError, '未启用星天之证补充'):
                    nav.skip({'id':'test'}, 1)
                self.assertEqual(nav.actions, ['choose', 'DungeonSkipActive'])

    def test_each_ticket_can_be_enabled_independently(self):
        for ticket in OFFERS:
            with self.subTest(ticket=ticket):
                nav = FakeDungeon([OFFERS[ticket], 'DungeonContinuePage'])
                self.assertEqual(nav.skip({'id':'test'}, 1, {ticket: True}), 1)
                self.assertEqual(nav.actions.count('refill:DungeonSkipActive:' + ticket), 1)

    def test_key_then_cat_refill_in_same_run_and_reset_after_completion(self):
        nav = FakeDungeon([OFFERS['green'], OFFERS['cat'], 'DungeonContinuePage',
                           OFFERS['cat'], OFFERS['cat'], 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 2, {'green': True, 'cat': True}), 2)
        self.assertIn('refill:DungeonSkipActive:cat', nav.actions)
        self.assertIn('refill:DungeonContinueSkip:cat', nav.actions)

    def test_cat_disabled_after_key_refill_stops(self):
        nav = FakeDungeon([OFFERS['red'], OFFERS['cat']])
        with self.assertRaisesRegex(RuntimeError, '猫掌特急券不足'):
            nav.skip({'id':'test'}, 1, {'red': True})
        self.assertEqual(nav.actions.count('refill:DungeonSkipActive:red'), 1)

class DungeonParameters(unittest.TestCase):
    def setUp(self):
        self.target = {'id':'snake','name':'蛇肝达玛克','difficulty':'非常困难','can_enter':True,'can_skip':True,'ticket':'red','ticket_cost':1}
        self.catalog={'dungeons':[self.target]}

    def test_region_selection_requires_configured_and_recognized_label(self):
        nav = DungeonNavigator(SimpleNamespace())
        nav.action = Mock()
        with self.assertRaisesRegex(RuntimeError, '尚未配置'):
            nav.select_skip_region(self.target, 'frame')
        self.target['skip_region'] = '皱囊虫遗迹'
        nav.reco = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, '未确认区域选择弹窗'):
            nav.select_skip_region(self.target, 'frame')
        nav.action.assert_not_called()

    def test_region_selection_waits_until_dialog_leaves(self):
        nav = DungeonNavigator(SimpleNamespace())
        nav.action = Mock()
        nav.frame = Mock(return_value='frame')
        rows = SimpleNamespace(all_results=[SimpleNamespace(text='皱囊虫遗迹', score=0.99, box=[320, 208, 132, 36])])
        nav.reco = Mock(side_effect=[True, rows, True, False])
        self.target['skip_region'] = '皱囊虫遗迹'
        nav.select_skip_region(self.target, 'frame')
        nav.action.assert_called_once_with('DungeonClick', {'DungeonClick': {'target': [386, 226]}})
        self.assertEqual(nav.frame.call_count, 2)

    def test_region_choice_uses_requested_row_and_rejects_duplicates(self):
        nav = DungeonNavigator(SimpleNamespace())
        nav.action = Mock()
        nav.frame = Mock(return_value='frame')
        rows = [SimpleNamespace(text=name, score=0.99, box=[320, 210 + i * 80, 130, 30])
                for i, name in enumerate(['皱囊虫遗迹', '死亡迷宫', '晓之塔 图里亚尔瓦'])]
        self.target['skip_region'] = '死亡迷宫'
        nav.reco = Mock(side_effect=[True, SimpleNamespace(all_results=rows), False])
        nav.select_skip_region(self.target, 'frame')
        nav.action.assert_called_once_with('DungeonClick', {'DungeonClick': {'target': [385, 305]}})
        nav.action.reset_mock()
        rows.append(SimpleNamespace(text='死亡迷宫', score=0.99, box=[320, 450, 130, 30]))
        nav.reco = Mock(side_effect=[True, SimpleNamespace(all_results=rows)])
        with self.assertRaisesRegex(RuntimeError, '同名入口不唯一'):
            nav.select_skip_region(self.target, 'frame')
        nav.action.assert_not_called()

    def test_absent_route_does_not_fall_back_to_first_choice(self):
        nav = DungeonNavigator(SimpleNamespace())
        nav.action = Mock()
        self.target['skip_region'] = '死亡迷宫'
        rows = SimpleNamespace(all_results=[SimpleNamespace(text='皱囊虫遗迹', score=0.99, box=[320, 210, 130, 30])])
        nav.reco = Mock(side_effect=[True, rows])
        with patch('dungeons.time.monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(RuntimeError, '未确认扫荡区域'):
                nav.select_skip_region(self.target, 'frame')
        nav.action.assert_not_called()

    def test_count_rejects_nonpositive_fraction_bool_and_unbounded(self):
        for value in [0,-1,1000,1.5,True,'1.0','0',None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_request({'target':'snake','count':value},self.catalog)
        self.assertEqual(parse_request({'target':'snake','count':'12'},self.catalog)[1],12)

    def test_requires_verified_skip_and_unique_destination(self):
        self.target['can_skip']=False
        with self.assertRaises(ValueError):parse_request({'target':'snake'},self.catalog)
        self.target['can_skip']=True
        self.catalog['dungeons'].append(self.target.copy())
        with self.assertRaises(ValueError):parse_request({'target':'snake'},self.catalog)

    def test_destination_difficulty_and_cost_must_all_match(self):
        text='将消耗1个红色解锁卡，并移动到蛇肝达玛克（非常困难）。'
        self.assertTrue(verify_party(text,self.target))
        for old,new in [('1个','2个'),('红色','绿色'),('蛇肝达玛克','月影森林'),('非常困难','困难')]:
            self.assertFalse(verify_party(text.replace(old,new),self.target))

    def test_proof_only_positive_allowlist(self):
        offer = '回复红色解锁卡 要使用1次导证之力，回复红色解锁卡吗？ 导证之力：剩余33次'
        self.assertTrue(proof_refill_allowed(offer, 'red'))
        self.assertFalse(proof_refill_allowed(offer, 'green'))
        self.assertFalse(proof_refill_allowed(offer.replace('33次','0次'), 'red'))
        self.assertFalse(proof_refill_allowed(offer.replace('使用1次','使用2次'), 'red'))
        for text in ['补充解锁卡','消耗克洛诺斯之石进行补充','星天引导之证不足，消耗克洛诺斯之石补充','星天引导之证']:
            self.assertFalse(proof_refill_allowed(text))

    def test_refill_policy_defaults_to_no_and_rejects_truthy_strings(self):
        self.assertEqual(parse_refill_policy({}), {'red': False, 'green': False, 'cat': False})
        self.assertEqual(parse_refill_policy({'refill_cat': True}), {'red': False, 'green': False, 'cat': True})
        for ticket in OFFERS:
            for value in ['false', 'true', 0, 1, None]:
                with self.subTest(ticket=ticket, value=value), self.assertRaises(ValueError):
                    parse_refill_policy({'refill_' + ticket: value})

    def test_cat_refill_requires_own_positive_quota(self):
        self.assertEqual(refill_ticket(OFFERS['cat']), 'cat')
        self.assertTrue(proof_refill_allowed(OFFERS['cat'], 'cat'))
        self.assertFalse(proof_refill_allowed(OFFERS['cat'], 'red'))
        for text in [OFFERS['cat'].replace('12次', '0次'), OFFERS['cat'] + '克洛诺斯之石',
                     OFFERS['cat'] + ' 导证之力：剩余0次', OFFERS['cat'].replace('使用1次', '使用2次')]:
            self.assertFalse(proof_refill_allowed(text, 'cat'))

    def test_refill_checks_quota_and_target_before_any_click(self):
        for ticket, text in [('cat', OFFERS['cat'].replace('12次', '0次')),
                             ('green', OFFERS['green']), ('cat', OFFERS['cat'] + '克洛诺斯之石')]:
            nav = DungeonNavigator(SimpleNamespace())
            nav.action = Mock()
            with self.subTest(ticket=ticket), self.assertRaisesRegex(RuntimeError, '未通过核对'):
                nav.refill(self.target, 'DungeonSkipActive', text, ticket)
            nav.action.assert_not_called()

    def test_refill_requires_correct_receipt_before_resubmitting(self):
        nav = DungeonNavigator(SimpleNamespace())
        nav.action = Mock()
        nav.frame = Mock(return_value='receipt')
        nav.reco = Mock(return_value=False)
        with patch('dungeons.time.monotonic', side_effect=[0, 21]):
            with self.assertRaisesRegex(RuntimeError, '未确认获得对应票券'):
                nav.refill(self.target, 'DungeonSkipActive', OFFERS['cat'], 'cat')
        nav.action.assert_called_once_with('DungeonProofRefill')
        expected = nav.reco.call_args.args[2]['DungeonProofReceived']['expected'][0]
        self.assertIn('猫掌特急券', expected)

    def test_refill_receipt_then_return_and_resubmit(self):
        nav = DungeonNavigator(SimpleNamespace())
        calls = Mock()
        nav.action = calls.action
        nav.wait = calls.wait
        nav.frame = Mock(return_value='receipt')
        nav.reco = Mock(return_value=True)
        nav.party_matches = Mock(return_value=True)
        nav.refill(self.target, 'DungeonSkipActive', OFFERS['cat'], 'cat')
        self.assertEqual([(c[0], c.args[0]) for c in calls.mock_calls], [
            ('action', 'DungeonProofRefill'), ('action', 'DungeonProofReceived'),
            ('wait', 'DungeonSkipActive'), ('action', 'DungeonSkipActive')])

    def test_dismiss_avoids_a_dungeon_under_the_old_fixed_click(self):
        rows = [SimpleNamespace(box=[236, 410, 100, 24])]
        self.assertNotEqual(blank_map_point(rows), (350, 400))
        with self.assertRaisesRegex(RuntimeError, '空白区域'):
            blank_map_point([SimpleNamespace(box=[0, 0, 1280, 720])])

    def test_split_element_label_keeps_the_requested_element(self):
        nav = FakeDungeon([])
        rows = [SimpleNamespace(text='古代席尔贝利亚大陆', box=[518,197,172,22]),
                SimpleNamespace(text='晶', box=[705,201,19,17])]
        self.assertIsNotNone(nav.label(rows, '古代席尔贝利亚大陆 晶'))
        self.assertIsNone(nav.label(rows, '古代席尔贝利亚大陆 阴'))
        rows.append(SimpleNamespace(text='古代席尔贝利亚大陆 晶', box=[900,300,210,25]))
        with self.assertRaisesRegex(RuntimeError, '同名入口不唯一'):
            nav.label(rows, '古代席尔贝利亚大陆 晶')

class DungeonPlan(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.catalog = json.loads((root / 'agent/data/dungeons.json').read_text(encoding='utf-8'))
        self.defaults = json.loads((root / 'assets/resource/pipeline/dungeons.json').read_text(
            encoding='utf-8'))['DungeonSkip']['custom_action_param']

    def test_defaults_and_independent_counts(self):
        for params in ({}, self.defaults):
            plan = parse_skip_plan(params, self.catalog)
            self.assertEqual([(target['ticket'], count) for target, count in plan], [('red', 4), ('green', 4)])
        plan = parse_skip_plan({'red_count': '3', 'green_count': '2'}, self.catalog)
        self.assertEqual([count for _, count in plan], [3, 2])

    def test_route_selection_is_per_target_and_does_not_mutate_catalog(self):
        target = next(d for d in self.catalog['dungeons'] if d['id'] == 'dungeon_d6bebfdd633b')
        route = target['skip_routes'][1]
        params = {'target': target['id'], 'routes': {target['id']: route['id'], 'old_target': 'stale_route'}}
        selected, _ = parse_request(params, self.catalog)
        self.assertEqual(selected['skip_region'], route['name'])
        self.assertNotIn('skip_region', target)
        default, _ = parse_request({'target': target['id']}, self.catalog)
        self.assertEqual(default['skip_route_id'], target['default_route'])
        plan = parse_skip_plan({'red_count': 0, 'green_target': target['id'], 'routes': params['routes']}, self.catalog)
        self.assertEqual(plan[0][0]['skip_route_id'], route['id'])

    def test_invalid_routes_are_rejected_before_execution(self):
        for value in (None, 'route', [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_skip_plan({'routes': value}, self.catalog)
        with self.assertRaisesRegex(ValueError, '路线无效'):
            parse_request({'target': 'dungeon_d6bebfdd633b', 'routes': {'dungeon_d6bebfdd633b': 'not-found'}}, self.catalog)
        with self.assertRaisesRegex(ValueError, '没有.*路线'):
            parse_request({'target': 'moon_forest_h', 'routes': {'moon_forest_h': 'not-found'}}, self.catalog)

    def test_red_and_green_use_their_own_route_in_one_plan(self):
        red = next(d for d in self.catalog['dungeons'] if d['ticket'] == 'red' and d.get('skip_routes'))
        green = next(d for d in self.catalog['dungeons'] if d['ticket'] == 'green' and d.get('skip_routes'))
        routes = {red['id']: red['skip_routes'][-1]['id'], green['id']: green['skip_routes'][1]['id']}
        plan = parse_skip_plan({'red_target': red['id'], 'green_target': green['id'], 'routes': routes}, self.catalog)
        self.assertEqual([target['skip_route_id'] for target, _ in plan], [routes[red['id']], routes[green['id']]])
        routes[green['id']] = routes[red['id']]
        context = SimpleNamespace(run_task=Mock())
        params = {'red_target': red['id'], 'green_target': green['id'], 'routes': routes}
        with patch('dungeons.DungeonNavigator') as ctor:
            self.assertFalse(DungeonSkip().run(context, SimpleNamespace(custom_action_param=json.dumps(params))))
            ctor.assert_not_called()
            context.run_task.assert_not_called()

    def test_interface_options_require_complete_nodes_and_do_not_affect_cli(self):
        context = SimpleNamespace(get_node_data=Mock(return_value=None))
        with self.assertRaisesRegex(ValueError, '配置节点缺失'):
            read_interface_options(context, {'use_interface_options': True}, self.catalog)
        context.get_node_data.reset_mock()
        params = {'red_count': 1, 'green_count': 0}
        self.assertEqual(read_interface_options(context, params, self.catalog), params)
        context.get_node_data.assert_not_called()

    def test_zero_disables_each_group_and_both(self):
        for ticket, remaining in [('red', 'green'), ('green', 'red')]:
            plan = parse_skip_plan({ticket + '_count': '0', ticket + '_target': 'unused'}, self.catalog)
            self.assertEqual([(target['ticket'], count) for target, count in plan], [(remaining, 4)])
        self.assertEqual(parse_skip_plan({'red_count': 0, 'green_count': 0}, self.catalog), [])

    def test_invalid_counts_and_cross_ticket_targets(self):
        for ticket in ('red', 'green'):
            for value in (-1, 1000, True, 1.5, '01', '1.0', None):
                with self.subTest(ticket=ticket, value=value), self.assertRaises(ValueError):
                    parse_skip_plan({ticket + '_count': value}, self.catalog)
            wrong = 'moon_forest_h' if ticket == 'red' else 'snake_damak_vh'
            with self.assertRaisesRegex(ValueError, '其他票种'):
                parse_skip_plan({ticket + '_target': wrong}, self.catalog)

    def test_two_key_dungeon_count_means_runs(self):
        target = next(v for v in self.catalog['dungeons'] if v['ticket'] == 'green'
                      and v['ticket_cost'] == 2 and v['can_skip'])
        plan = parse_skip_plan({'red_count': 0, 'green_target': target['id'], 'green_count': 2}, self.catalog)
        self.assertEqual(plan, [(target, 2)])

    def test_legacy_override_does_not_also_spend_other_ticket(self):
        for target in ('snake_damak_vh', 'moon_forest_h'):
            params = dict(self.defaults, target=target, count=3)
            plan = parse_skip_plan(params, self.catalog)
            self.assertEqual([(v['id'], count) for v, count in plan], [(target, 3)])
        plan = parse_skip_plan(dict(self.defaults, count=2), self.catalog)
        self.assertEqual([(v['id'], count) for v, count in plan], [('snake_damak_vh', 2)])

    def test_action_runs_both_groups_in_order_and_resets_each_invocation(self):
        events = []
        def entrance(name):
            events.append(name)
            return SimpleNamespace(status=SimpleNamespace(succeeded=True),
                                   nodes=[SimpleNamespace(name='DungeonMenuReady')])
        def skip(target, count, policy):
            events.append((target['ticket'], count, policy))
            return count
        context = SimpleNamespace(run_task=Mock(side_effect=entrance))
        params = {'red_count': 3, 'green_count': 2, 'refill_red': True}
        argv = SimpleNamespace(custom_action_param=json.dumps(params))
        with patch('dungeons.DungeonNavigator') as ctor:
            ctor.return_value.party_matches.return_value = False
            ctor.return_value.skip.side_effect = skip
            action = DungeonSkip()
            self.assertTrue(action.run(context, argv))
            self.assertTrue(action.run(context, argv))
        policy = {'red': True, 'green': False, 'cat': False}
        self.assertEqual(events, ['DungeonEntrance', ('red', 3, policy),
                                  'DungeonEntrance', ('green', 2, policy)] * 2)

    def test_invalid_second_group_is_rejected_before_any_navigation(self):
        context = SimpleNamespace(run_task=Mock())
        with patch('dungeons.DungeonNavigator') as ctor:
            argv = SimpleNamespace(custom_action_param='{"green_target":"snake_damak_vh"}')
            self.assertFalse(DungeonSkip().run(context, argv))
            ctor.assert_not_called()
            context.run_task.assert_not_called()

    def test_disabled_groups_never_navigate(self):
        context = SimpleNamespace(run_task=Mock())
        with patch('dungeons.DungeonNavigator') as ctor:
            argv = SimpleNamespace(custom_action_param='{"red_count":0,"green_count":0}')
            self.assertTrue(DungeonSkip().run(context, argv))
            ctor.assert_not_called()
            context.run_task.assert_not_called()

    def test_incomplete_first_group_does_not_start_second(self):
        context = SimpleNamespace(run_task=Mock())
        for result in (0, RuntimeError('红票不足')):
            with self.subTest(result=result), patch('dungeons.DungeonNavigator') as ctor:
                ctor.return_value.party_matches.return_value = True
                ctor.return_value.skip.side_effect = [result]
                self.assertFalse(DungeonSkip().run(context, SimpleNamespace(custom_action_param='{}')))
                self.assertEqual(ctor.return_value.skip.call_count, 1)
                context.run_task.assert_not_called()

    def test_cli_preserves_legacy_and_supports_split_plan(self):
        from run_startup import dungeon_params
        args = SimpleNamespace(dungeon=None, count=None, red_dungeon=None, green_dungeon=None,
                               red_count=4, green_count=2, refill_red=False, refill_green=False, refill_cat=True)
        self.assertEqual([n for _, n in parse_skip_plan(dungeon_params(args), self.catalog)], [4, 2])
        args.dungeon = 'moon_forest_h'
        with self.assertRaisesRegex(ValueError, '不能.*混用'):
            dungeon_params(args)
        args.red_count = args.green_count = None
        self.assertEqual([(t['id'], n) for t, n in parse_skip_plan(dungeon_params(args), self.catalog)],
                         [('moon_forest_h', 1)])

    def test_cli_route_flags_preserve_both_choices_and_legacy_choice(self):
        from run_startup import dungeon_params
        args = SimpleNamespace(dungeon=None, count=None, dungeon_route=None,
                               red_dungeon='red_id', green_dungeon='green_id', red_count=1, green_count=2,
                               red_route='red_route', green_route='green_route',
                               refill_red=False, refill_green=False, refill_cat=False)
        self.assertEqual(dungeon_params(args)['routes'], {'red_id': 'red_route', 'green_id': 'green_route'})
        args.dungeon = 'legacy_id'
        with self.assertRaisesRegex(ValueError, '不能.*混用'):
            dungeon_params(args)
        args.red_dungeon = args.green_dungeon = args.red_count = args.green_count = None
        args.red_route = args.green_route = None
        args.dungeon_route = 'legacy_route'
        self.assertEqual(dungeon_params(args)['routes'], {'legacy_id': 'legacy_route'})


class DungeonCatalog(unittest.TestCase):
    def test_action_calls_hidden_entrance_and_passes_refill_options(self):
        context = SimpleNamespace(run_task=Mock(return_value=SimpleNamespace(
            status=SimpleNamespace(succeeded=True), nodes=[SimpleNamespace(name='DungeonMenuReady')]
        )))
        params = {'target': 'snake_damak_vh', 'count': 2, 'refill_cat': True}
        with patch('dungeons.DungeonNavigator') as ctor:
            ctor.return_value.party_matches.return_value = False
            ctor.return_value.skip.return_value = 2
            self.assertTrue(DungeonSkip().run(context, SimpleNamespace(custom_action_param=json.dumps(params))))
            context.run_task.assert_called_once_with('DungeonEntrance')
            self.assertEqual(ctor.return_value.skip.call_args.args[2],
                             {'red': False, 'green': False, 'cat': True})

    def test_failed_entrance_never_submits_skip(self):
        context = SimpleNamespace(run_task=Mock(return_value=SimpleNamespace(
            status=SimpleNamespace(succeeded=False), nodes=[SimpleNamespace(name='DungeonMenuReady')]
        )))
        with patch('dungeons.DungeonNavigator') as ctor:
            ctor.return_value.party_matches.return_value = False
            self.assertFalse(DungeonSkip().run(context, SimpleNamespace(custom_action_param='{"target":"snake_damak_vh"}')))
            ctor.return_value.skip.assert_not_called()

    def test_available_options_have_complete_paths_and_valid_requests(self):
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / 'agent/data/dungeons.json').read_text(encoding='utf-8'))
        interface = json.loads((root / 'assets/interface.json').read_text(encoding='utf-8'))
        ids = [v['id'] for v in catalog['dungeons']]
        self.assertEqual(len(ids), len(set(ids)))
        available = {v['id'] for v in catalog['dungeons'] if v['can_enter'] and v['can_skip']}
        cases = interface['option']['DungeonTarget']['cases']
        self.assertEqual(available, {v['name'] for v in cases})
        self.assertEqual(len(cases), len({v['label'] for v in cases}))
        for ticket in ('red', 'green'):
            prefix = 'Dungeon' + ticket.title()
            option = interface['option'][prefix + 'Target']
            expected = {v['id'] for v in catalog['dungeons'] if v['id'] in available and v['ticket'] == ticket}
            self.assertEqual({v['name'] for v in option['cases']}, expected)
            self.assertIn(option['default_case'], expected)
            for case in option['cases']:
                self.assertEqual(case['pipeline_override']['DungeonSkipOption_' + prefix + 'Target']['attach'],
                                 {ticket + '_target': case['name']})
                target = next(v for v in catalog['dungeons'] if v['id'] == case['name'])
                if target.get('skip_routes'):
                    self.assertEqual(len(case['option']), 1)
                    routes = interface['option'][case['option'][0]]
                    self.assertEqual(routes['default_case'], target['default_route'])
                    self.assertEqual([(v['name'], v['label']) for v in routes['cases']],
                                     [(v['id'], v['name']) for v in target['skip_routes']])
                    for route in routes['cases']:
                        override = route['pipeline_override']['DungeonSkipOption_' + case['option'][0]]['attach']
                        selected, _ = parse_request({'target': target['id'], **override}, catalog)
                        self.assertEqual(selected['skip_route_id'], route['name'])
                else:
                    self.assertNotIn('option', case)
            count_option = interface['option'][prefix + 'Count']
            self.assertEqual(count_option['inputs'][0]['default'], '4')
            self.assertEqual(count_option['pipeline_override']['DungeonSkipOption_' + prefix + 'Count']['attach'],
                             {ticket + '_count': '{count}'})
        for ident in available:
            target, count = parse_request({'target':ident, 'count':2}, catalog)
            self.assertEqual(count, 2)
            region = next(m for m in catalog['maps'] if [m['era'],m['region']] == target['path'][:2])
            self.assertIn(target['path'][2], region['points'])
            for depth in range(3, len(target['path'])):
                parent = next(m for m in catalog['nested_maps'] if m['path'] == target['path'][:depth])
                self.assertIn(target['path'][depth], parent['points'])

if __name__=='__main__':unittest.main()
