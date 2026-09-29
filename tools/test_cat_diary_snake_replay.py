"""蛇头远景树受移动猫遮挡的原生回放；离线控制器禁止输入。"""
from pathlib import Path
import sys
import traceback

import cv2
import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner


class ReplaySnakeLandmark(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_snake_landmark.npz') as data:
                # 原尺寸模板在真实失败帧中受猫遮挡，复现低于 0.9 的得分。
                old_score = cv2.minMaxLoc(cv2.matchTemplate(
                    data['positive_2'], data['old_template'], cv2.TM_CCOEFF_NORMED))[1]
                assert old_score < .9, old_score
                for kind, count in [('positive', 15), ('negative', 16)]:
                    for i in range(count):
                        frame = np.zeros((720, 1280, 3), np.uint8)
                        frame[315:410, 280:540] = data[f'{kind}_{i}']
                        result = runner.reco('CatDiarySnakeHeadTree', frame)
                        if kind == 'positive':
                            assert result and list(result.best_result.box) == data[f'box_{i}'].tolist(), (kind, i, result)
                        else:
                            assert result is None, (kind, i, result)
                print('PASS 15 snake landmark positives, including moving-cat occlusion', flush=True)
                print('PASS 16 other-scene negatives', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-snake-landmark-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('ReplaySnakeLandmark', ReplaySnakeLandmark())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('ReplaySnakeLandmark', {'ReplaySnakeLandmark': {
        'action': 'Custom', 'custom_action': 'ReplaySnakeLandmark'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
