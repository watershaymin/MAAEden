"""无滚动条三条日记的原生识别、完整 OCR 与四条列表负例回放。"""
from pathlib import Path
import sys
import traceback
from unittest.mock import Mock

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'agent'))
from cat_diary import CatDiaryRunner, DiaryState, diary_scrollbar


class CheckStaticList(CustomAction):
    passed = False

    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            with np.load(ROOT/'tools/fixtures/cat_diary_static_list.npz') as data:
                pages = {key: data[key] for key in data.files}
            for key in ('before','after_down','after_up'):
                assert runner.reco('CatDiaryStaticList',pages[key]),key
                try:
                    diary_scrollbar(pages[key])
                except ValueError:
                    pass
                else:
                    raise AssertionError('旧滚动条规则应无法读取静态布局')
            for key in ('four_top','four_bottom','four_three_visible_done'):
                assert not runner.reco('CatDiaryStaticList',pages[key]),key
                assert diary_scrollbar(pages[key])[2] == 4
            for height in (20,100,200,240,320):
                frame = pages['before'].copy()
                frame[134:134+height,962:966] = [53,80,103]
                assert not runner.reco('CatDiaryStaticList',frame),height
            assert not runner.reco('CatDiaryStaticList',np.zeros_like(pages['before']))
            print('PASS 3 live static pages, 3 live four-row pages, 5 rail sizes and blank negative',flush=True)

            current = ['before']
            gestures = []
            runner.frame = Mock(side_effect=lambda:pages[current[0]].copy())
            runner.open_diary = Mock()
            def action(node,override):
                assert node == 'CatDiaryScrollList',node
                begin = override[node]['begin']
                current[0] = 'after_down' if begin == (780,430) else 'after_up'
                gestures.append(current[0])
            runner.action = action
            state = runner.read_diary()
            assert state == DiaryState(('cat_74','cat_35','cat_76'),5),state
            assert gestures == ['after_down','after_up'],gestures
            assert runner.diary_unscrollable
            print('PASS native OCR, all three clues, stamps and both unchanged-page checks',flush=True)
            self.passed = True
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT/'debug/cat-diary-static-list-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    check = CheckStaticList()
    resource.register_custom_action('CheckStaticList',check)
    assert resource.post_bundle(ROOT/'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource,controller)
    job = tasker.post_task('CheckStaticList',{'CheckStaticList':{'action':'Custom','custom_action':'CheckStaticList'}}).wait()
    return 0 if job.succeeded and check.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
