"""实机裁片在 Maa 原生识别器上的回归；不连接或操作游戏。"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
from maa.controller import CustomController
from maa.context import ContextEventSink
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from phantom import PhantomJackpot, PhantomRunner


class ImageController(CustomController):
    inputs = 0
    def connect(self): return True
    def request_uuid(self): return 'phantom-offline-fixtures'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720, 1280, 3), dtype=np.uint8)
    def forbidden(self, *args):
        self.inputs += 1
        raise RuntimeError('离线幻璃境检查不允许发送游戏输入')
    start_app = stop_app = click = swipe = touch_down = touch_move = touch_up = forbidden
    click_key = input_text = key_down = key_up = forbidden


class InspectFixtures(CustomAction):
    def run(self, context, argv):
        try:
            nav = PhantomRunner(context)
            for key, frame in self.frames.items():
                if key in ('first', 'second', 'third', 'fourth', 'baruoki_all', 'baruoki_middle', 'baruoki_balloon'):
                    self.results[key] = {
                        'events': nav.events(frame), 'cats': nav.loot_points(frame, 'cat'),
                        'black': bool(nav.reco('PhantomBlackCat', frame)),
                        'chests': nav.loot_points(frame, 'chest'),
                    }
                elif key == 'terminal_title':
                    self.results[key] = nav.title(frame)
                else:
                    node = {'white_warning': 'PhantomWhiteWarning', 'white_available': 'PhantomWhiteAvailable',
                            'no_white': 'PhantomWhiteAvailable', 'black_reference': 'PhantomBlackCat'}[key]
                    self.results[key] = bool(nav.reco(node, frame))
            return True
        except Exception as exc:
            self.error = exc
            return False


class StopAtTerminal(CustomAction):
    stopped = False

    def run(self, context, argv):
        nav = PhantomRunner(context)
        nav.title = Mock(return_value='last')
        nav.record = Mock()
        try:
            with patch('phantom.console_jackpot_alert'):
                nav.observe_room(None)
        except PhantomJackpot:
            self.stopped = True
            return False
        return False


class CaptureActions(ContextEventSink):
    def __init__(self):
        self.notifications = []

    def on_raw_notification(self, context, msg, details):
        self.notifications.append((msg, details))


class NativePhantomRecognition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Toolkit.init_option(ROOT / 'debug/phantom/offline-recognition')
        cls.probe = InspectFixtures()
        with np.load(ROOT / 'tools/fixtures/phantom_samples.npz', allow_pickle=False) as samples:
            cls.probe.frames = {key: cv2.imdecode(samples[key], cv2.IMREAD_COLOR) for key in samples.files}
        cls.probe.results, cls.probe.error = {}, None
        cls.resource = Resource()
        assert cls.resource.register_custom_action('InspectPhantomFixtures', cls.probe)
        assert cls.resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
        cls.controller = ImageController()
        assert cls.controller.post_connection().wait().succeeded
        cls.tasker = Tasker()
        assert cls.tasker.bind(cls.resource, cls.controller)
        job = cls.tasker.post_task('InspectPhantomFixtures', {'InspectPhantomFixtures': {
            'action': 'Custom', 'custom_action': 'InspectPhantomFixtures'}}).wait()
        assert job.succeeded, cls.probe.error

    def test_white_ticket_signals_and_absence(self):
        for key in ('white_warning', 'white_available'):
            self.assertTrue(self.probe.results[key], key)
        self.assertFalse(self.probe.results['no_white'])

    def test_multiple_icon_sizes_and_backgrounds(self):
        for key, count in [('first', 3), ('second', 3), ('third', 4), ('fourth', 1)]:
            with self.subTest(key=key):
                self.assertEqual(len(self.probe.results[key]['events']), count, self.probe.results[key])

    def test_normal_cats_never_match_black_cat_reference(self):
        for key in ('second', 'third', 'fourth'):
            with self.subTest(key=key):
                self.assertEqual(len(self.probe.results[key]['cats']), 1, self.probe.results[key])
                self.assertFalse(self.probe.results[key]['black'])
        self.assertTrue(self.probe.results['black_reference'])

    def test_baruoki_middle_chest_and_balloon_exit_stay_distinct(self):
        self.assertEqual(self.probe.results['baruoki_all']['chests'], [(543, 150), (657, 131), (793, 150)])
        self.assertEqual(self.probe.results['baruoki_middle']['chests'], [(657, 131)])
        self.assertEqual(self.probe.results['baruoki_balloon']['chests'], [(1052, 131)])
        self.assertIn((450, 161), self.probe.results['baruoki_balloon']['events'])
        for key in ('baruoki_all', 'baruoki_middle', 'baruoki_balloon'):
            self.assertFalse(self.probe.results[key]['black'], key)

    def test_real_terminal_title(self):
        self.assertEqual(self.probe.results['terminal_title'], 'last')

    def test_terminal_stop_returns_from_native_callback_and_emits_focus(self):
        stop = StopAtTerminal()
        sink = CaptureActions()
        self.resource.register_custom_action('StopAtPhantomTerminal', stop)
        sink_id = self.tasker.add_context_sink(sink)
        try:
            job = self.tasker.post_task('StopAtPhantomTerminal', {'StopAtPhantomTerminal': {
                'action': 'Custom', 'custom_action': 'StopAtPhantomTerminal', 'next': ['PhantomComplete']}})
            deadline = time.monotonic() + 5
            while not job.done and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(job.done, '终境停止在原生 Custom 回调中未返回')
            self.assertTrue(stop.stopped)
            self.assertEqual(self.controller.inputs, 0)
            # Maa 5.12.3 的 post_stop 可能把外层 task 标为 succeeded；
            # 停机契约是后续节点不执行，而不是外层状态枚举的取值。
            self.assertFalse(any(details.get('name') == 'PhantomComplete'
                                 for _, details in sink.notifications), sink.notifications)
            self.assertTrue(any(msg == 'Node.Action.Starting' and
                                (details.get('focus') or {}).get('aborted') is True and
                                (details.get('focus') or {}).get('Node.Action.Starting', {}).get('content') == '你撞大运了'
                                for msg, details in sink.notifications), sink.notifications)
        finally:
            self.tasker.remove_context_sink(sink_id)


if __name__ == '__main__':
    unittest.main()
