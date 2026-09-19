"""真实失败标题的离线 OCR 回归；只使用无输入能力的控制器，不连接游戏。"""

from pathlib import Path
import sys
import traceback

import numpy as np
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import read_map_name


class OfflineController(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'minimap-title-offline-replay'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720,1280,3), np.uint8)
    def forbidden(self, *args): raise RuntimeError('离线回归不允许发送输入')
    start_app = stop_app = click = swipe = touch_down = touch_move = touch_up = forbidden
    click_key = input_text = key_down = key_up = forbidden


class CheckTitles(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT / 'tools/fixtures/minimap_titles.npz') as samples:
                for key, expected in [('kms','旧KMS总部副入口'), ('acid','酸性沼泽'), ('tower','时之塔1楼')]:
                    frame = np.zeros((720,1280,3), np.uint8)
                    frame[10:63,15:655] = samples[key]
                    assert read_map_name(runner, frame, expected) == expected, key
                    if key == 'tower':
                        assert read_map_name(runner, frame, '时之塔2楼') != '时之塔2楼'
                    print('PASS', key, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/minimap/ocr-tests')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckTitles', CheckTitles())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckTitles', {'CheckTitles': {'action':'Custom', 'custom_action':'CheckTitles'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
