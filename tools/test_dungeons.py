"""副本参数和消耗约束的回归检查。"""
import sys
import json
import unittest
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'agent'))
from dungeons import DungeonNavigator, blank_map_point, parse_request, verify_party, proof_refill_allowed


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
        return node == frame

    def action(self, node, override=None):
        self.actions.append(node)

    def wait(self, node, seconds=10):
        self.actions.append(node)

    def refill(self, target, source_action, text):
        self.actions.append('refill:' + source_action)


class DungeonCounting(unittest.TestCase):
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
        nav = FakeDungeon(['DungeonContinuePage', 'DungeonProofRefill',
                           'DungeonProofRefill', 'DungeonCongratulations', 'DungeonContinuePage'])
        self.assertEqual(nav.skip({'id':'test'}, 2), 2)
        self.assertEqual(nav.actions.count('refill:DungeonContinueSkip'), 1)

    def test_repeated_refill_without_completion_stops(self):
        nav = FakeDungeon(['DungeonProofRefill', 'DungeonProofRefill'])
        with self.assertRaisesRegex(RuntimeError, '再次要求补票'):
            nav.skip({'id':'test'}, 1)
        self.assertEqual(nav.actions.count('refill:DungeonSkipActive'), 1)

class DungeonParameters(unittest.TestCase):
    def setUp(self):
        self.target = {'id':'snake','name':'蛇肝达玛克','difficulty':'非常困难','can_enter':True,'can_skip':True,'ticket':'red','ticket_cost':1}
        self.catalog={'dungeons':[self.target]}

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

class DungeonCatalog(unittest.TestCase):
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
        for ident in available:
            target, count = parse_request({'target':ident, 'count':2}, catalog)
            self.assertEqual(count, 2)
            region = next(m for m in catalog['maps'] if [m['era'],m['region']] == target['path'][:2])
            self.assertIn(target['path'][2], region['points'])
            for depth in range(3, len(target['path'])):
                parent = next(m for m in catalog['nested_maps'] if m['path'] == target['path'][:depth])
                self.assertIn(target['path'][depth], parent['points'])

if __name__=='__main__':unittest.main()
