"""四条猫咪日记列表的完整读取与滚动定位原生回放。"""
import sys
import traceback
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner, DiaryState, diary_scrollbar


class CheckDiaryList(CustomAction):
    def run(self, context, argv):
        try:
            with np.load(ROOT / 'tools/fixtures/cat_diary_list.npz') as data:
                pages = {key: data[key] for key in ('top', 'bottom', 'three_visible_done')}
            for key in ('top', 'bottom'):
                top, bottom, count = diary_scrollbar(pages[key])
                assert count == 4
                assert (top <= 139) == (key == 'top')
                assert (bottom >= 449) == (key == 'bottom')
                print('PASS real four-row scrollbar', key, top, bottom, flush=True)
            assert diary_scrollbar(pages['three_visible_done'])[2] == 4
            print('PASS three visible claws do not imply a three-row list', flush=True)

            runner = CatDiaryRunner(context)
            current = ['bottom']
            scrolls = []
            runner.frame = Mock(side_effect=lambda: pages[current[0]].copy())
            runner.open_diary = Mock()

            def scroll(node, override):
                assert node == 'CatDiaryScrollList'
                begin = override[node]['begin']
                current[0] = 'top' if begin == (780, 175) else 'bottom'
                scrolls.append(current[0])

            runner.action = scroll
            assert runner.read_diary() == DiaryState((None, 'cat_25', 'cat_54', 'cat_19'), 4)
            assert scrolls == ['top', 'bottom', 'top'], scrolls
            print('PASS native OCR reads all four in canonical order and restores top', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-diary-list-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckDiaryList', CheckDiaryList())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckDiaryList', {'CheckDiaryList': {
        'action': 'Custom', 'custom_action': 'CheckDiaryList'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
