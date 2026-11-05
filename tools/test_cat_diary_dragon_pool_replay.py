"""龙神池下层环道真实场景羽毛、入口负样本和严格地图名原生回放。"""
from pathlib import Path
import sys
import traceback

import numpy as np
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from maa.custom_action import CustomAction

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import read_map_name
from test_cat_diary_museum_replay import OfflineController


class CheckDragonPool(CustomAction):
    passed = False

    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_dragon_pool.npz') as samples:
                for i in range(2):
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[180:360, 300:1000] = samples[f'button_{i}']
                    result = runner.reco('CatDiaryInteract', frame)
                    assert result and result.best_result.score >= 0.9, ('button', i)
                    print('PASS lower-ring scene feather', i, result.best_result.score, flush=True)
                for i in range(2):
                    frame[180:360, 300:1000] = samples[f'negative_{i}']
                    assert not runner.reco('CatDiaryInteract', frame), ('negative', i)
                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[10:65, 15:655] = samples['title']
                assert read_map_name(runner, frame, '龙神池') == '龙神池'
                assert read_map_name(runner, frame, '浩奇星森林') != '浩奇星森林'
            self.passed = True
            print('PASS two absent-button scenes and exact Dragon Pool title', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-dragon-pool-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    check = CheckDragonPool()
    resource.register_custom_action('CheckDragonPool', check)
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckDragonPool', {'CheckDragonPool': {
        'action': 'Custom', 'custom_action': 'CheckDragonPool'}}).wait()
    return 0 if job.succeeded and check.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
