"""体育场海报与普通对话的原生截图回放；不连接设备。"""
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


def samples():
    result = {}
    with np.load(ROOT / 'tools/fixtures/cat_diary_poster.npz') as data:
        for name in ('page1', 'page2', 'world', 'ordinary', 'map', 'diary'):
            frame = np.zeros((720, 1280, 3), np.uint8)
            for i, (x, y, w, h) in enumerate(data['rois']):
                frame[y:y+h, x:x+w] = data[f'{name}_{i}']
            result[name] = frame
    return result


class Replay(CustomController):
    def __init__(self, frames):
        self.frames, self.index, self.clicks = frames, 0, []
        super().__init__()

    def connect(self): return True
    def request_uuid(self): return 'cat-diary-dialogue-offline-replay'
    def get_features(self): return 0
    def screencap(self): return self.frames[self.index].copy()
    def click(self, x, y):
        assert (x, y) == (320, 665), (x, y)
        self.clicks.append((x, y))
        self.index = min(self.index + 1, len(self.frames)-1)
        return True


class Check(CustomAction):
    def __init__(self, mode, controller, images):
        self.mode, self.controller, self.images = mode, controller, images
        super().__init__()

    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            if self.mode == 'world':
                for name in ('page1', 'page2', 'ordinary'):
                    assert runner.reco('CatDiaryDialogue', self.images[name]), name
                assert not runner.reco('CatDiaryStadiumPoster', self.images['ordinary'])
                for name in ('world', 'map', 'diary'):
                    assert not runner.reco('CatDiaryDialogue', self.images[name]), name
                for x, y, w, h in ((140, 10, 85, 86), (460, 26, 370, 44)):
                    missing = self.images['page1'].copy()
                    missing[y:y+h, x:x+w] = 0
                    assert not runner.reco('CatDiaryDialogue', missing)
                assert not runner.reco('CatDiaryDialogue', self.images['page1']//2)
                runner.world()
                assert len(self.controller.clicks) == 2
            elif self.mode == 'interact':
                # 翻过海报仅恢复场景，不能当成猫已完成。
                assert runner.interact() is False
                assert len(self.controller.clicks) == 2
            else:
                method = runner.world if self.mode == 'world_limit' else runner.interact
                try:
                    method()
                except RuntimeError as exc:
                    assert '20 页' in str(exc), exc
                else:
                    raise AssertionError('不变的说明页必须有界停止')
                assert len(self.controller.clicks) == 20
            print('PASS', self.mode, flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-dialogue-tests')
    resource = Resource()
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    images = samples()
    for mode in ('world', 'interact', 'world_limit', 'interact_limit'):
        frames = [images['page1']] if mode.endswith('limit') else [images[k] for k in ('page1', 'page2', 'world')]
        controller = Replay(frames)
        assert controller.post_connection().wait().succeeded
        name = 'CheckDialogue' + mode
        resource.register_custom_action(name, Check(mode, controller, images))
        tasker = Tasker()
        assert tasker.bind(resource, controller)
        assert tasker.post_task(name, {name: {'action': 'Custom', 'custom_action': name}}).wait().succeeded
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
