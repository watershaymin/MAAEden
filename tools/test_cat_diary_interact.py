"""移动猫交互：点击前必须用当前画面重新确认按钮。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from cat_diary import CatDiaryRunner


def button(box):
    return SimpleNamespace(best_result=SimpleNamespace(box=box))


class MovingCatTests(unittest.TestCase):
    def setUp(self):
        self.runner=CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        self.runner.frame=Mock()
        self.runner.click=Mock()
        self.runner.diary_ready=Mock(return_value=False)

    def test_clicks_fresh_position_and_requires_return_to_diary(self):
        r=self.runner
        old,new=button([852,207,28,40]),button([893,208,28,40])
        r.frame=Mock(side_effect=['old','fresh','diary'])
        r.diary_ready=Mock(side_effect=lambda frame: frame=='diary')
        def recognize(node,frame,override=None):
            if node=='StartUpWorldReady': return True
            if node=='CatDiaryInteract': return old if frame=='old' else new
            return None
        r.reco=Mock(side_effect=recognize)
        with patch('cat_diary.time.sleep'):
            self.assertTrue(r.interact())
        r.click.assert_called_once_with(new)
        self.assertEqual(r.frame.call_count,3)

    def test_disappeared_button_does_not_click_stale_position(self):
        r=self.runner
        r.frame=Mock(side_effect=['old','fresh'])
        r.reco=Mock(side_effect=lambda node,frame,override=None:
                    True if node=='StartUpWorldReady' else
                    button([1053,227,21,30]) if node=='CatDiaryInteract' and frame=='old' else None)
        self.assertFalse(r.interact())
        r.click.assert_not_called()

    def test_changed_scene_does_not_match_or_click_old_button(self):
        r=self.runner
        r.frame=Mock(return_value='dialogue')
        r.reco=Mock(return_value=None)
        self.assertIsNone(r.refresh_cat_button(button([800,200,28,40])))
        r.reco.assert_called_once_with('StartUpWorldReady','dialogue')
        r.click.assert_not_called()

    def test_fresh_search_stays_in_scene_bounds_at_both_edges(self):
        r=self.runner
        for old in ([0,100,13,18],[1265,550,15,30]):
            with self.subTest(box=old):
                r.reco=Mock(return_value=True)
                r.refresh_cat_button(button(old))
                x,y,w,h=r.reco.call_args.args[2]['CatDiaryInteract']['roi']
                self.assertTrue(0<=x<x+w<=1280)
                self.assertTrue(100<=y<y+h<=580)
                self.assertLessEqual(w,268)
                self.assertLessEqual(h,160)

    def test_repeated_clicks_without_diary_still_fail(self):
        r=self.runner
        fixed=button([800,200,28,40])
        r.reco=Mock(side_effect=lambda node,*args:
                    fixed if node=='CatDiaryInteract' else node=='StartUpWorldReady')
        with patch('cat_diary.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'连续点击落空'):
                r.interact()
        self.assertEqual(r.click.call_count,10)


if __name__=='__main__':
    unittest.main()
