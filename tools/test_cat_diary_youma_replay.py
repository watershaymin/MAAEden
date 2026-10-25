"""妖魔殿北门、错误场景、完整楼层名与室内羽毛的原生回放。"""
from pathlib import Path
import sys
import traceback
import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import read_map_name


class CheckYouma(CustomAction):
    passed = False

    def run(self, context, argv):
        try:
            nav = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_youma.npz') as data:
                for i in range(2):
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[220:350, 580:700] = data[f'door_{i}']
                    result = nav.reco('CatDiaryYoumaDoor', frame)
                    assert result and result.best_result.score >= 0.9, ('door', i)
                    print('door', i, result.best_result.score, flush=True)
                for i in range(4):
                    frame[220:350, 580:700] = data[f'negative_{i}']
                    assert not nav.reco('CatDiaryYoumaDoor', frame), ('negative', i)
                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[10:65, 15:655] = data['title_0']
                assert read_map_name(nav, frame, '妖魔殿一楼入口') == '妖魔殿一楼入口'
                for wrong in ('妖魔殿', '妖魔殿二楼入口', '妖魔殿一楼'):
                    assert read_map_name(nav, frame, wrong) != wrong
                frame[10:65, 15:655] = data['title_1']
                assert read_map_name(nav, frame, '妖魔殿一楼入口') == '妖魔殿'
                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[210:310, 700:800] = data['marker']
                assert nav.reco('CatDiaryMarker', frame)
            self.passed = True
            print('PASS 2 doors, 4 negatives, exact inside/outside titles and inside feather', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-youma-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    check = CheckYouma()
    resource.register_custom_action('CheckYouma', check)
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckYouma', {'CheckYouma': {'action': 'Custom', 'custom_action': 'CheckYouma'}}).wait()
    return 0 if job.succeeded and check.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
