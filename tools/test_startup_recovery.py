"""已知选关页恢复的真实截图回放；控制器仅在内存中翻页，不连接设备。"""
from pathlib import Path
import traceback

import numpy as np
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
NODE = 'StartUpCloseMenasStages'


def samples():
    result = {}
    with np.load(ROOT / 'tools/fixtures/startup_menas_recovery.npz') as data:
        for name in ('stages', 'world', 'diary', 'desktop'):
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
    def request_uuid(self): return 'startup-menas-offline-replay'
    def get_features(self): return 0
    def screencap(self): return self.frames[self.index].copy()
    def click(self, x, y):
        if not (1190 <= x < 1280 and 0 <= y < 45):
            raise RuntimeError(f'错误点击，不能进入挑战：{x}, {y}')
        self.clicks.append((x, y))
        self.index = min(self.index + 1, len(self.frames)-1)
        return True


class Check(CustomAction):
    def run(self, context, argv):
        try:
            images = samples()
            assert context.run_recognition(NODE, images['stages']).hit
            for name in ('world', 'diary', 'desktop'):
                assert not context.run_recognition(NODE, images[name]).hit, name
            for x, y, w, h in ((550, 0, 185, 40), (935, 155, 215, 130), (1190, 0, 90, 45)):
                missing = images['stages'].copy()
                missing[y:y+h, x:x+w] = 0
                assert not context.run_recognition(NODE, missing).hit, (x, y)
            assert not context.run_recognition(NODE, images['stages']//2).hit
            print('PASS stage / world / diary / desktop / missing title, SS, close / dimmed stage', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/startup-recovery-tests')
    resource = Resource()
    resource.register_custom_action('CheckRecovery', Check())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    images = samples()
    for frames in ([images['stages'], images['world']], [images['stages']]):
        controller = Replay(frames)
        assert controller.post_connection().wait().succeeded
        tasker = Tasker()
        assert tasker.bind(resource, controller)
        if len(frames) == 2:
            assert tasker.post_task('CheckRecovery', {'CheckRecovery': {
                'action': 'Custom', 'custom_action': 'CheckRecovery'}}).wait().succeeded
        job = tasker.post_task('StartUp', {
            'StartUp': {'action': 'DoNothing', 'timeout': 1000},
            NODE: {'timeout': 1000},
        }).wait()
        nodes = [node.name for node in job.get().nodes]
        if len(frames) == 2:
            assert job.succeeded and nodes == ['StartUp', NODE, 'StartUpWorldReady'], nodes
            assert len(controller.clicks) == 1
            print('PASS stage -> one close click -> world', flush=True)
        else:
            assert job.failed and 'StartUpWorldReady' not in nodes, nodes
            assert len(controller.clicks) == 2, controller.clicks
            print('PASS unchanged stage stops after two clicks', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
