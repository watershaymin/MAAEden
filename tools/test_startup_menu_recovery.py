"""主菜单恢复的原生离线回放；只在内存中切换页面，不连接设备。"""
from pathlib import Path
import traceback

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_startup_entry import Replay as EntryReplay
from test_startup_local_map_recovery import samples as local_samples

ROOT = Path(__file__).resolve().parents[1]
NODE = 'StartUpCloseMenu'


def samples():
    result = local_samples()
    with np.load(ROOT / 'tools/fixtures/startup_menu_recovery.npz') as data:
        for name in ('menu', 'menu_after_launch'):
            frame = np.zeros((720, 1280, 3), np.uint8)
            for i, (x, y, w, h) in enumerate(data['rois']):
                frame[y:y+h, x:x+w] = data[f'{name}_{i}']
            result[name] = frame
    return result


class Replay(EntryReplay):
    def __init__(self, frames):
        self.keys = []
        super().__init__(frames)

    def request_uuid(self):
        return 'startup-menu-offline-replay'

    def click_key(self, keycode):
        assert keycode == 4, keycode
        self.keys.append(keycode)
        self.index = min(self.index + 1, len(self.frames) - 1)
        return True


class Check(CustomAction):
    def run(self, context, argv):
        try:
            images = samples()
            for name in ('menu', 'menu_after_launch'):
                assert context.run_recognition(NODE, images[name]).hit, name
            print('PASS two real expanded menus', flush=True)
            for name in ('world', 'diary', 'desktop', 'local_map', 'world_map', 'download', 'stages'):
                assert not context.run_recognition(NODE, images[name]).hit, name
            print('PASS seven other scene samples', flush=True)
            with np.load(ROOT / 'tools/fixtures/startup_menu_recovery.npz') as data:
                for x, y, w, h in data['rois']:
                    missing = images['menu'].copy()
                    missing[y:y+h, x:x+w] = 0
                    assert not context.run_recognition(NODE, missing).hit, (x, y)
            assert not context.run_recognition(NODE, images['menu'] // 2).hit
            print('PASS missing each menu component and half brightness', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/startup-menu-recovery-tests')
    resource = Resource()
    resource.register_custom_action('CheckMenuRecovery', Check())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    images = samples()
    for frames in ([images['menu'], images['world']], [images['menu']]):
        controller = Replay(frames)
        assert controller.post_connection().wait().succeeded
        tasker = Tasker()
        assert tasker.bind(resource, controller)
        if len(frames) == 2:
            assert tasker.post_task('CheckMenuRecovery', {'CheckMenuRecovery': {
                'action': 'Custom', 'custom_action': 'CheckMenuRecovery'}}).wait().succeeded
        job = tasker.post_task('StartUp', {
            'StartUp': {'timeout': 1000}, NODE: {'timeout': 1000},
        }).wait()
        nodes = [node.name for node in job.get().nodes if node.name]
        assert controller.keys == [4], controller.keys
        assert not controller.starts, controller.starts
        if len(frames) == 2:
            assert job.succeeded and nodes == ['StartUp', NODE, 'StartUpWorldReady'], nodes
            print('PASS one back key -> independently verified world, no app launch', flush=True)
        else:
            assert job.failed and nodes == ['StartUp', NODE], nodes
            print('PASS unchanged menu fails after one back key, no repeated key or app launch', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
