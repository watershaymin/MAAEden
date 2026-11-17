"""安格尔西侧连接路标志、完整地图标题与东侧落点的原生回放。"""
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


class CheckWasteland(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            nodes = ['CatDiaryAngalWest' + name for name in ['Wall', 'WallEnd', 'Ruin', 'Log', 'Tree']]
            with np.load(ROOT / 'tools/fixtures/cat_diary_wasteland.npz') as data:
                stages = []
                for patch in data['passages']:
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[:350] = patch
                    matches = [i for i, node in enumerate(nodes) if runner.reco(node, frame)]
                    assert matches
                    stages.append(max(matches))
                assert stages == [0, 1, 2, 3, 4, 4, 4], stages
                print('PASS observed passage stages', stages, flush=True)
                frame[:350] = data['entry_offset']
                assert runner.reco(nodes[0], frame)
                assert not any(runner.reco(node, frame) for node in nodes[1:])
                print('PASS independently observed entry offset', flush=True)
                for key in ['negative_desktop', 'negative_world']:
                    frame[:350] = data[key]
                    assert not any(runner.reco(node, frame) for node in nodes), key
                print('PASS desktop and world-map negatives', flush=True)
                for key, title in [('source_title', '再生村落安格尔'), ('target_title', '沉淀之地')]:
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[10:63, 15:655] = data[key]
                    assert read_map_name(runner, frame, title) == title
                    session = MiniMapNavigator(runner, title, exact=True)
                    assert session.accepts_name(title)
                    assert not session.accepts_name(title + '2楼')
                patches = data['landing_frames']
                frames = np.zeros((len(patches), 720, 1280, 3), np.uint8)
                frames[:, 260:380, 940:1070] = patches
                position = pulse_position(frames, MAP_ROI)
                assert math.dist(position, (1002, 316)) < 5, position
                print('PASS exact titles and independent landing', position, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-wasteland-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    assert resource.register_custom_action('CheckWasteland', CheckWasteland())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckWasteland', {'CheckWasteland': {
        'action': 'Custom', 'custom_action': 'CheckWasteland',
    }}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
