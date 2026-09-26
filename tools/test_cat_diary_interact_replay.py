"""真实移动羽毛序列的局部重识别；离线控制器禁止输入。"""
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from test_cat_diary_museum_replay import OfflineController

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from cat_diary import CatDiaryRunner


class ReplayMovingButton(CustomAction):
    def run(self,context,argv):
        try:
            runner=CatDiaryRunner(context)
            with np.load(ROOT/'tools/fixtures/cat_diary_moving_button.npz') as data:
                for i in range(5):
                    frame=np.zeros((720,1280,3),np.uint8)
                    x,y,w,h=data[f'roi_{i}']
                    frame[y:y+h,x:x+w]=data[f'button_{i}']
                    frame[625:703,25:145]=data[f'menu_{i}']
                    frame[630:703,235:320]=data[f'map_{i}']
                    runner.frame=Mock(return_value=frame)
                    old=SimpleNamespace(best_result=SimpleNamespace(box=data[f'old_{i}'].tolist()))
                    result=runner.refresh_cat_button(old)
                    expected=data[f'expected_{i}'].tolist()
                    if expected:
                        assert result and result.best_result.box==expected, (i,result,expected)
                        assert result.best_result.box[0]-old.best_result.box[0]>=40
                    else:
                        assert result is None, '已消失的按钮不得复用旧坐标'
                    print('PASS moving button sample',i,flush=True)
            return True
        except Exception:
            traceback.print_exc()
            return False


def main():
    Toolkit.init_option(ROOT/'debug/cat-moving-button-replay')
    controller=OfflineController()
    assert controller.post_connection().wait().succeeded
    resource=Resource()
    resource.register_custom_action('ReplayMovingButton',ReplayMovingButton())
    assert resource.post_bundle(ROOT/'assets/resource').wait().succeeded
    tasker=Tasker()
    assert tasker.bind(resource,controller)
    job=tasker.post_task('ReplayMovingButton',{'ReplayMovingButton':{
        'action':'Custom','custom_action':'ReplayMovingButton'}}).wait()
    return 0 if job.succeeded else 1


if __name__=='__main__':
    raise SystemExit(main())
