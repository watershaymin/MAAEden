"""船墓出口、完整标题与库尔奇海湾落点的实机原图回放。"""
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
from minimap_navigation import MAP_ROI, MiniMapNavigator, pulse_position, read_map_name


class CheckBay(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_bay.npz') as data:
                for key, title in [('ship_title', '船墓第一只中型船船底'), ('bay_title', '库尔奇海湾')]:
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[10:63, 15:655] = data[key]
                    assert read_map_name(runner, frame, title) == title
                    session = MiniMapNavigator(runner, title, exact=True)
                    assert session.accepts_name(title)
                    assert not session.accepts_name(title + '2楼')
                    print('PASS exact title', title, flush=True)
                for patch in data['exit_frames']:
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[500:620, 570:710] = patch
                    assert runner.reco('CatDiaryShipGraveyardExit', frame)
                print('PASS two independently captured ship exits', flush=True)
                for key in ['negative_world', 'negative_bay', 'negative_diary']:
                    frame[500:620, 570:710] = data[key]
                    assert not runner.reco('CatDiaryShipGraveyardExit', frame), key
                print('PASS world, bay and diary negatives', flush=True)
                patches = data['landing_frames']
                frames = np.zeros((len(patches), 720, 1280, 3), np.uint8)
                x, y = data['landing_origin']
                h, w = patches.shape[1:3]
                frames[:, y:y+h, x:x+w] = patches
                point = pulse_position(frames, MAP_ROI)
                assert math.dist(point, (248, 572)) < 5, point
                print('PASS independently observed bay landing', point, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-bay-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    assert resource.register_custom_action('CheckBay', CheckBay())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckBay', {'CheckBay': {'action': 'Custom', 'custom_action': 'CheckBay'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
