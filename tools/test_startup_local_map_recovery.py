"""登录后展开区域地图的原生离线回放；只在内存中切换画面。"""
from pathlib import Path
import traceback

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_startup_recovery import Replay as StageReplay, samples as stage_samples

ROOT = Path(__file__).resolve().parents[1]
NODE = 'StartUpCloseLocalMap'


def samples():
    result = {}
    with np.load(ROOT/'tools/fixtures/startup_local_map_recovery.npz') as data:
        for name in ('local_map', 'long_map', 'world', 'diary', 'world_map', 'download', 'desktop'):
            frame = np.zeros((720,1280,3), np.uint8)
            for i, (x,y,w,h) in enumerate(data['rois']):
                frame[y:y+h,x:x+w] = data[f'{name}_{i}']
            result[name] = frame
    result['stages'] = stage_samples()['stages']
    return result


class Replay(StageReplay):
    def request_uuid(self): return 'startup-local-map-offline-replay'
    def click(self, x, y):
        if (x,y) != (1150,140):
            raise RuntimeError(f'错误的地图切换位置：{x}, {y}')
        self.clicks.append((x,y))
        self.index = min(self.index+1, len(self.frames)-1)
        return True


class Check(CustomAction):
    def run(self, context, argv):
        try:
            images = samples()
            for name in ('local_map', 'long_map'):
                assert context.run_recognition(NODE, images[name]).hit, name
            for name in ('world', 'diary', 'world_map', 'download', 'desktop', 'stages'):
                assert not context.run_recognition(NODE, images[name]).hit, name
            for x,y,w,h in ((0,0,318,70), (318,52,53,26)):
                missing = images['local_map'].copy()
                missing[y:y+h,x:x+w] = 0
                assert not context.run_recognition(NODE, missing).hit, (x,y)
            assert not context.run_recognition(NODE, images['local_map']//2).hit
            print('PASS two local maps / six other scenes / missing title or decoration / dimmed map', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT/'debug/startup-local-map-recovery-tests')
    resource = Resource()
    resource.register_custom_action('CheckLocalMapRecovery', Check())
    assert resource.post_bundle(ROOT/'assets/resource').wait().succeeded
    images = samples()
    for frames in ([images['local_map'], images['world']], [images['local_map']]):
        controller = Replay(frames)
        assert controller.post_connection().wait().succeeded
        tasker = Tasker()
        assert tasker.bind(resource, controller)
        if len(frames) == 2:
            assert tasker.post_task('CheckLocalMapRecovery', {'CheckLocalMapRecovery': {
                'action': 'Custom', 'custom_action': 'CheckLocalMapRecovery'}}).wait().succeeded
        job = tasker.post_task('StartUp', {
            'StartUp': {'action': 'DoNothing', 'timeout': 1000},
            NODE: {'timeout': 1000},
        }).wait()
        nodes = [node.name for node in job.get().nodes]
        if len(frames) == 2:
            assert job.succeeded and nodes == ['StartUp', NODE, 'StartUpWorldReady'], nodes
            assert len(controller.clicks) == 1
            print('PASS local map -> one close click -> world', flush=True)
        else:
            assert job.failed and 'StartUpWorldReady' not in nodes, nodes
            assert len(controller.clicks) == 1, controller.clicks
            print('PASS unchanged local map fails without toggling again', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
