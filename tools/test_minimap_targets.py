"""真实小地图羽毛的离线识别与整图投影；控制器禁止所有输入。"""
import math
from pathlib import Path
import sys
import traceback

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from test_minimap_ocr import OfflineController
from cat_diary import CatDiaryRunner
from minimap_navigation import MAP_ROI, MapAtlas, feather_points, project_point, pulse_position


class CheckTargets(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/minimap_targets.npz') as samples:
                for key in ['palace', 'castle', 'isiya']:
                    base, full = samples[key+'_base'], samples[key+'_map']
                    targets = feather_points(runner, full)
                    atlas = MapAtlas(base, [full]*4, key, samples[key+'_player'], targets)
                    atlas.excluded = feather_points(runner, base, True)
                    assert len(atlas.excluded) == len(targets) == 1, key
                    observed = atlas.register(base, samples[key+'_mini_player'])
                    projected = project_point(observed, atlas.excluded[0])
                    error = math.dist(projected, targets[0])
                    assert error < 5, (key, error)
                    # 没有羽毛的空白小图不能沿用上一个图例。
                    blank = base.copy()
                    blank[20:175,1020:1262] = 0
                    assert not feather_points(runner, blank, True), key
                    print(f'PASS {key}: {error:.2f}px', flush=True)
                assert runner.reco('CatDiaryXenoDoor', samples['xeno_gold'])
                for key in ['palace', 'isiya']:
                    assert not runner.reco('CatDiaryXenoDoor', samples[key+'_base'], {
                        'CatDiaryXenoDoor': {'template': ['CatDiary/XenoDoorGold.png']}})
                print('PASS xeno gold door / negatives', flush=True)
            with np.load(ROOT / 'tools/fixtures/cat_diary_sami.npz') as samples:
                frames = np.zeros((len(samples['player']),720,1280,3), np.uint8)
                frames[:,369:439,620:690] = samples['player']
                frames[:,170:240,714:796] = samples['feather']
                marker = runner.reco('CatDiaryMarker', frames[-1])
                assert marker, '佐见移动羽毛未识别'
                boxes = [match.box for match in marker.filtered_results]
                position = pulse_position(frames, MAP_ROI, excluded=boxes)
                assert math.dist(position, (653,403)) < 1, position
                print('PASS sami moving feather / player separation', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/minimap/target-tests')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckTargets', CheckTargets())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckTargets', {'CheckTargets': {'action': 'Custom', 'custom_action': 'CheckTargets'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
