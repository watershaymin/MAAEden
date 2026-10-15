"""那古萨无连接路标志、红叶街道上缘角色与羽毛的实机回放。"""
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
sys.path.insert(0, str(ROOT/'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import MAP_ROI, LocalizationLost, pulse_position, read_map_name


class CheckVermilion(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            nodes = ['CatDiaryNagsham'+name for name in ('Pillar', 'Vine', 'Tree')]
            with np.load(ROOT/'tools/fixtures/cat_diary_vermilion.npz') as data:
                previous = None
                for i in range(1, 9):
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[:280] = data[f'passage_{i}']
                    matches = [(j, r.best_result.box[0]) for j, node in enumerate(nodes)
                               if (r := runner.reco(node, frame))]
                    assert matches, i
                    stage, x = max(matches)
                    assert previous is None or stage > previous[0] or (stage == previous[0] and x < previous[1]-100), (i, previous, stage, x)
                    previous = stage, x
                for i in range(3):
                    frame[:280] = data[f'negative_{i}']
                    assert not any(runner.reco(node, frame) for node in nodes), i
                frames = np.zeros((len(data['top_frames']), 720, 1280, 3), np.uint8)
                frames[:, 80:150, 165:1120] = data['top_frames']
                try:
                    pulse_position(frames, (165, 130, 955, 490))
                except LocalizationLost:
                    pass
                else:
                    raise AssertionError('旧范围应漏掉上缘角色环')
                position = pulse_position(frames, MAP_ROI)
                assert abs(position[0]-637) < 3 and abs(position[1]-117) < 3, position
                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[70:150, 165:1120] = data['marker']
                marker = runner.reco('CatDiaryMarker', frame)
                assert marker and 760 < marker.best_result.box[0] < 800
                frame[10:65, 15:655] = data['title']
                assert read_map_name(runner, frame, '红叶街道') == '红叶街道'
                print('PASS 8 passage scenes, 3 negatives, upper-edge pulse, feather and exact title', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT/'debug/cat-vermilion-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckVermilion', CheckVermilion())
    assert resource.post_bundle(ROOT/'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckVermilion', {'CheckVermilion': {'action': 'Custom', 'custom_action': 'CheckVermilion'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
