"""时之塔出口与克鲁利大道完整标题、落点的原生离线回放。"""
import math
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
from cat_diary import CatDiaryRunner
from minimap_navigation import MAP_ROI, MiniMapNavigator, read_map_name, pulse_position


class CheckCluri(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_cluri.npz') as data:
                for key, title in [('tower_title', '时之塔1楼'), ('cluri_title', '克鲁利大道')]:
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[10:63, 15:655] = data[key]
                    name = read_map_name(runner, frame, title)
                    assert name == title, (title, name)
                    session = MiniMapNavigator(runner, title, exact=True)
                    assert session.accepts_name(name)
                    for wrong in [title + '2楼', title.replace('1楼', '2楼'), '其他区域']:
                        if wrong != title:
                            assert not session.accepts_name(wrong), wrong
                    print('PASS exact title', title, flush=True)

                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[530:650, 570:710] = data['tower_exit']
                result = runner.reco('CatDiaryTimeTowerExit', frame)
                assert result
                print('PASS observed tower exit', result.best_result.score, flush=True)
                for key in ('negative_diary', 'negative_cluri'):
                    frame[530:650, 570:710] = data[key]
                    assert not runner.reco('CatDiaryTimeTowerExit', frame), key
                print('PASS diary and Cluri scene negatives', flush=True)

                patches = data['landing_frames']
                frames = np.zeros((len(patches), 720, 1280, 3), np.uint8)
                x, y = data['landing_origin']
                h, w = patches.shape[1:3]
                frames[:, y:y+h, x:x+w] = patches
                position = pulse_position(frames, MAP_ROI)
                assert math.dist(position, (226, 232)) < 5, position
                print('PASS independent landing pulse', position, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-cluri-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckCluri', CheckCluri())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckCluri', {'CheckCluri': {'action': 'Custom', 'custom_action': 'CheckCluri'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
