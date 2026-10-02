"""原生回放：已在游戏内时不重复启动；桌面入口启动一次并核验画面。"""
from pathlib import Path

from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_startup_recovery import Replay as StageReplay, samples

ROOT = Path(__file__).resolve().parents[1]
INTENT = 'com.xd.anothereden/net.wrightflyer.toybox.AppActivity'


class Replay(StageReplay):
    def __init__(self, frames):
        self.starts = []
        super().__init__(frames)

    def request_uuid(self):
        return 'startup-entry-offline-replay'

    def start_app(self, intent):
        assert intent == INTENT, intent
        self.starts.append(intent)
        self.index = min(self.index + 1, len(self.frames) - 1)
        return True

    def click(self, x, y):
        raise RuntimeError(f'入口回放不应点击：{x}, {y}')


def main():
    Toolkit.init_option(ROOT / 'debug/startup-entry-tests')
    resource = Resource()
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    images = samples()
    cases = (
        ('world', [images['world']], True, 0, ['StartUp', 'StartUpWorldReady']),
        ('desktop to world', [images['desktop'], images['world']], True, 1,
         ['StartUp', 'StartUpLaunch', 'StartUpWorldReady']),
        ('unchanged desktop', [images['desktop']], False, 1, None),
    )
    for name, frames, expected_success, expected_starts, expected_nodes in cases:
        controller = Replay(frames)
        assert controller.post_connection().wait().succeeded
        tasker = Tasker()
        assert tasker.bind(resource, controller)
        job = tasker.post_task('StartUp', {
            'StartUp': {'timeout': 1000},
            'StartUpLaunch': {'timeout': 1000},
        }).wait()
        nodes = [node.name for node in job.get().nodes if node.name]
        assert job.succeeded == expected_success, (name, nodes)
        assert len(controller.starts) == expected_starts, (name, controller.starts)
        if expected_nodes is not None:
            assert nodes == expected_nodes, (name, nodes)
        else:
            assert nodes == ['StartUp', 'StartUpLaunch'], (name, nodes)
        print(f'PASS {name}: starts={len(controller.starts)}, nodes={nodes}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
