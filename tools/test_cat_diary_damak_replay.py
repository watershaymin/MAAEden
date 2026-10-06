"""蛇肝达玛克的蛇骨岛分区入口与完整传送标签原生回放。"""
import sys
import traceback
from pathlib import Path

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner, compact


class CheckDamak(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            entry = next(e for e in runner.catalog if e['id'] == 'cat_30')
            assert entry['world_entry'] == '蛇骨岛'
            assert entry['world_panel'] == 'CatDiarySnakeIsland'
            assert entry['world_names'] == ['蛇肝达玛克']
            with np.load(ROOT / 'tools/fixtures/cat_diary_damak.npz') as data:
                frame = data['island']
                assert runner.reco(entry['world_panel'], frame)
                pattern = r'^蛇\s*肝\s*达\s*玛\s*克$'
                result = runner.reco('CatDiaryIslandDestination', frame,
                                     {'CatDiaryIslandDestination': {'expected': [pattern]}})
                assert result and compact(result.best_result.text) == '蛇肝达玛克'
                assert 514 <= result.best_result.box[1] < 555
                print('PASS island panel and observed exact Damak button', flush=True)
                for wrong in ['^蛇肝达马克$', '^达玛克$']:
                    assert not runner.reco('CatDiaryIslandDestination', frame,
                                           {'CatDiaryIslandDestination': {'expected': [wrong]}})
                print('PASS old spelling and shortened destination are rejected', flush=True)
                assert not runner.reco(entry['world_panel'], data['outer'])
                assert not runner.reco('CatDiaryIslandDestination', data['outer'],
                                       {'CatDiaryIslandDestination': {'expected': [pattern]}})
                print('PASS mainland is not the island panel or Damak destination', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-diary-damak-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckDamak', CheckDamak())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckDamak', {'CheckDamak': {
        'action': 'Custom', 'custom_action': 'CheckDamak'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
