"""传送确认行重叠字框、完整目的地及必需确认控件的原生回放。"""
from pathlib import Path
import sys
import traceback
from unittest.mock import Mock, patch

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT / 'tools')]
from cat_diary import CatDiaryRunner, compact
from test_cat_diary_museum_replay import OfflineController


class CheckConfirmation(CustomAction):
    passed = False

    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            frame = np.zeros((720, 1280, 3), np.uint8)
            with np.load(ROOT / 'tools/fixtures/cat_diary_confirm.npz') as samples:
                frame[282:470, 200:1080] = samples['nagsham_overlap']
                raw = runner.reco('CatDiaryConfirmText', frame)
                assert raw and any(row.text == '1' for row in raw.all_results)
                assert compact(runner.text('CatDiaryConfirmText', frame, single_line=True)) == '即将移动到辰之国那古萨无'
                runner.frame = Mock(return_value=frame)
                runner.click = Mock()
                assert runner.wait_confirm('辰之国 那古萨无', '^辰之国那古萨无$', ['辰之国 那古萨无'])
                runner.click.assert_not_called()
                print('PASS real overlapping glyph reread and exact Nagsham confirmation', flush=True)

                def rejected(sample, names):
                    runner.frame = Mock(return_value=sample)
                    with patch('cat_diary.time.monotonic', side_effect=[0, 0, 11]):
                        try:
                            runner.wait_confirm(names[0], '^.+$', names)
                        except RuntimeError as exc:
                            assert '确认文字不符' in str(exc)
                        else:
                            raise AssertionError('Unexpected confirmation: ' + repr(names))
                    runner.click.assert_not_called()

                for name in ['猫神神社', '辰之国 那古萨无1', '辰之国 那古萨']:
                    rejected(frame, [name])
                print('PASS wrong destination, extra digit and partial name rejected', flush=True)
                for y1, y2, x1, x2 in [(324, 359, 540, 734), (385, 470, 660, 910)]:
                    missing = frame.copy()
                    missing[y1:y2, x1:x2] = 0
                    rejected(missing, ['辰之国 那古萨无'])
                print('PASS missing question or Yes rejected', flush=True)
                for key in ['desktop', 'world_map']:
                    negative = np.zeros_like(frame)
                    negative[282:470, 200:1080] = samples[key]
                    rejected(negative, ['辰之国 那古萨无'])
                print('PASS real desktop and unconfirmed world map rejected', flush=True)
            self.passed = True
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-confirm-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    check = CheckConfirmation()
    resource.register_custom_action('CheckConfirmation', check)
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckConfirmation', {'CheckConfirmation': {
        'action': 'Custom', 'custom_action': 'CheckConfirmation'}}).wait()
    return 0 if job.succeeded and check.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
