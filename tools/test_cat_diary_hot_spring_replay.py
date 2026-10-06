"""温泉浴场招牌外观变化的原生回放；离线控制器禁止设备输入。"""
import sys
import traceback
from pathlib import Path

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


class CheckHotSpring(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/cat_diary_hot_spring.npz') as samples:
                frame = np.zeros((720, 1280, 3), np.uint8)
                frame[:360] = samples['bath_alternate']
                old_only = {'CatDiaryHotSpringBath': {'template': 'CatDiary/HotSpringBath.png'}}
                assert not runner.reco('CatDiaryHotSpringBath', frame, old_only)
                result = runner.reco('CatDiaryHotSpringBath', frame)
                assert result and result.best_result.box == [527, 180, 67, 74], result
                assert result.best_result.score > 0.99
                for node in ('CatDiaryHotSpringEntrance', 'CatDiaryHotSpringTree'):
                    assert not runner.reco(node, frame), node
                print('PASS observed alternate: old template misses, new template confirms bath only', flush=True)

                for key in ('negative_world', 'negative_diary'):
                    frame[:360] = samples[key]
                    assert not runner.reco('CatDiaryHotSpringBath', frame), key
                    print('PASS wrong scene', key, flush=True)

            # 保留既有外观；另检查入口岩壁和树木不会被识别成浴场阶段。
            for name, expected in [('Bath', True), ('Entrance', False), ('Tree', False)]:
                frame[:] = 0
                crop = cv2.imread(str(ROOT / f'assets/resource/image/CatDiary/HotSpring{name}.png'))
                h, w = crop.shape[:2]
                frame[90:90+h, 150:150+w] = crop
                result = runner.reco('CatDiaryHotSpringBath', frame)
                assert bool(result) == expected, name
                if result:
                    assert result.best_result.box == [150, 90, 67, 74]
                print('PASS existing landmark crop', name, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-hot-spring-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckHotSpring', CheckHotSpring())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckHotSpring', {'CheckHotSpring': {
        'action': 'Custom', 'custom_action': 'CheckHotSpring'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
