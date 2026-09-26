"""图书区子菜单、严格传送确认及完整区域标题的原生离线回放。"""
from pathlib import Path
import sys
import traceback
from unittest.mock import Mock, patch

import numpy as np
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import MiniMapNavigator, read_map_name


class OfflineController(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'cat-diary-museum-offline-replay'
    def get_features(self): return 0
    def screencap(self): return np.zeros((720,1280,3), np.uint8)
    def forbidden(self, *args): raise RuntimeError('离线回放不允许输入')
    start_app = stop_app = click = swipe = touch_down = touch_move = touch_up = forbidden
    click_key = input_text = key_down = key_up = forbidden


class CheckMuseum(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            entry = next(e for e in runner.catalog if e['id'] == 'cat_41')
            pattern = r'^博\s*物\s*馆\s*图\s*书\s*区$'
            with np.load(ROOT / 'tools/fixtures/cat_diary_museum.npz') as samples:
                menu = np.zeros((720,1280,3), np.uint8)
                menu[200:648,660:1231] = samples['menu']
                assert runner.reco('CatDiarySubmenu', menu)
                label = runner.reco('CatDiarySubDestination', menu,
                                    {'CatDiarySubDestination': {'expected': [pattern]}})
                assert label and label.best_result.text.replace(' ', '') == '博物馆图书区'
                assert 410 <= label.box.y <= 475, label.box
                print('PASS exact library submenu item (not Nierva or museum)', flush=True)

                confirm = np.zeros((720,1280,3), np.uint8)
                confirm[282:470,200:1080] = samples['confirm']
                runner.frame = Mock(side_effect=[menu, menu, menu, confirm])
                runner.click = Mock()
                yes = runner.wait_confirm('尼尔瓦', pattern, entry['world_names'])
                assert yes and runner.click.call_count == 1
                print('PASS stale submenu frames cannot click through Yes', flush=True)

                runner.frame = Mock(return_value=confirm)
                for name in ['尼尔瓦', '马克米纳尔博物馆']:
                    with patch('cat_diary.time.monotonic', side_effect=[0,0,11]):
                        try:
                            runner.wait_confirm(name, pattern, [name])
                        except RuntimeError as exc:
                            assert '确认文字不符' in str(exc)
                        else:
                            raise AssertionError('accepted wrong destination: ' + name)
                    print('PASS rejects confirmation alias', name, flush=True)

                frame = np.zeros((720,1280,3), np.uint8)
                frame[10:63,15:655] = samples['library_title']
                name = read_map_name(runner, frame, entry['map_names'][0])
                session = MiniMapNavigator(runner, entry['map_names'][0])
                assert session.accepts_name(name), name
                for wrong in ['马克米纳尔博物馆', '马克米纳尔博物馆庭园', '马克米纳尔图书馆']:
                    assert not session.accepts_name(wrong)
                print('PASS full library title and wrong-region rejection', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT / 'debug/cat-diary-museum-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckMuseum', CheckMuseum())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckMuseum', {'CheckMuseum': {'action':'Custom', 'custom_action':'CheckMuseum'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
