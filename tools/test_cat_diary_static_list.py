"""无滚动条三条布局的完整性复核，不能将隐藏条目当成完成。"""
import unittest
from unittest.mock import Mock

import test_cat_diary as helpers
from cat_diary import DiaryState


class StaticDiaryTests(unittest.TestCase):
    setUp = helpers.CatDiaryTests.setUp
    runner = helpers.CatDiaryTests.runner

    def static_runner(self):
        runner = self.runner()
        runner.open_diary = Mock()
        runner.diary_unscrollable = True
        runner.action = Mock()
        return runner

    def test_static_list_requires_both_swipes_and_matching_full_reads(self):
        runner = self.static_runner()
        page = (('cat_74', 'cat_35', 'cat_76'), 5, 3)
        runner.read_diary_page = Mock(side_effect=[(page, 7200), (page, 7198), (page, 7196)])
        self.assertEqual(runner.read_diary(), DiaryState(page[0], 5))
        actions = [c.args[1]['CatDiaryScrollList'] for c in runner.action.call_args_list]
        self.assertEqual([(c['begin'], c['end']) for c in actions],
                         [((780,430),(780,175)), ((780,175),(780,430))])
        self.assertEqual([c.args[0] for c in runner.read_diary_page.call_args_list], ['top']*3)

    def test_static_list_rejects_changed_clue_stamp_or_hidden_fourth(self):
        page = (('cat_01','cat_02','cat_03'), 5, 3)
        for changed in [(('cat_02','cat_03','cat_04'),5,3), (page[0],6,3), (page[0],5,4)]:
            for stage in (1,2):
                runner = self.static_runner()
                values = [(page,7200)]*stage+[(changed,7199)]
                runner.read_diary_page = Mock(side_effect=values)
                with self.assertRaisesRegex(RuntimeError, '内容或布局变化'):
                    runner.read_diary()
                self.assertEqual(runner.action.call_count, stage)

    def test_layout_change_with_identical_text_is_rejected(self):
        runner = self.static_runner()
        page = ((None,None,None),5,3)
        def read(_):
            runner.diary_unscrollable = runner.read_diary_page.call_count == 1
            return page,7200
        runner.read_diary_page = Mock(side_effect=read)
        with self.assertRaisesRegex(RuntimeError, '内容或布局变化'):
            runner.read_diary()
        self.assertEqual(runner.action.call_count,1)

    def test_stop_and_expiry_prevent_static_scroll(self):
        for stopped in (True,False):
            runner = self.static_runner()
            runner.read_diary_page = Mock(return_value=((('cat_01','cat_02','cat_03'),5,3),7200))
            if stopped:
                runner.context.tasker.stopping = True
            else:
                runner.round_deadline = 0
            with self.assertRaisesRegex(RuntimeError, '用户停止|刷新时间'):
                runner.read_diary()
            runner.action.assert_not_called()

    def test_existing_three_row_scrollbar_does_not_use_static_fallback(self):
        runner = self.runner()
        runner.open_diary = Mock()
        runner.action = Mock()
        runner.read_diary_page = Mock(return_value=(((None,None,None),5,3),7200))
        self.assertEqual(runner.read_diary(),DiaryState((None,None,None),5))
        runner.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
