"""柯尼姆西侧无图连接路标志和蛇首完整标题的原生离线回放。"""
from pathlib import Path
import sys
import traceback

import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'agent'))
from cat_diary import CatDiaryRunner
from minimap_navigation import MiniMapNavigator, read_map_name


class CheckIgoma(CustomAction):
    def run(self, context, argv):
        try:
            runner = CatDiaryRunner(context)
            nodes = ['CatDiaryKoniumWestFlag', 'CatDiaryKoniumWestSkull']
            with np.load(ROOT/'tools/fixtures/cat_diary_igoma.npz') as data:
                def scene(name):
                    frame = np.zeros((720,1280,3), np.uint8)
                    for i,(x,y,w,h) in enumerate(data['rois']):
                        frame[y:y+h,x:x+w] = data[f'{name}_{i}']
                    return frame
                for kind, node in zip(['flag','skull'], nodes):
                    positions = []
                    for i in range(2):
                        result = runner.reco(node, scene(f'{kind}_{i}'))
                        assert result, (kind,i)
                        positions.append(result.best_result.box[0])
                    assert positions[1] - positions[0] > 200, positions
                    print('PASS passage landmark', kind, positions, flush=True)
                for i in range(4):
                    for node in nodes:
                        assert not runner.reco(node, scene(f'negative_{i}')), (i,node)
                print('PASS head / diary / world map / town negatives', flush=True)
                for key, title in [('konium','魔兽村落柯尼姆'), ('igoma','蛇首伊格玛')]:
                    frame = np.zeros((720,1280,3), np.uint8)
                    frame[10:63,15:655] = data[key+'_title']
                    name = read_map_name(runner, frame, title)
                    assert name == title, (key,name)
                session = MiniMapNavigator(runner, '蛇首伊格玛', exact=True)
                assert session.accepts_name(name)
                for wrong in ['蛇首伊戈玛', '蛇首伊格玛2楼', '柯尼姆']:
                    assert not session.accepts_name(wrong), wrong
                print('PASS full Konium / Igoma titles and wrong-name rejection', flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT/'debug/cat-igoma-replay')
    controller = OfflineController()
    assert controller.post_connection().wait().succeeded
    resource = Resource()
    resource.register_custom_action('CheckIgoma', CheckIgoma())
    assert resource.post_bundle(ROOT/'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('CheckIgoma', {'CheckIgoma': {'action':'Custom', 'custom_action':'CheckIgoma'}}).wait()
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
