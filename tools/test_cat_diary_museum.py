"""图书区直达：父入口和目的地分离、子菜单动画防连点、严格确认。"""
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from cat_diary import CatDiaryRunner


class MuseumTeleportTests(unittest.TestCase):
    def setUp(self):
        self.runner = CatDiaryRunner(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        self.entry = next(e for e in self.runner.catalog if e['id'] == 'cat_41')
        self.runner.frame = Mock()
        self.runner.click = Mock()
        self.pattern = r'^博\s*物\s*馆\s*图\s*书\s*区$'

    def test_outer_entry_is_not_the_final_destination(self):
        runner = self.runner
        outer = SimpleNamespace(best_result=SimpleNamespace(text='尼尔瓦'))
        yes = object()
        runner.world = Mock()
        runner.wait = Mock()
        runner.action = Mock()
        runner.select_region = Mock()
        runner.wait_world_destination = Mock(side_effect=AssertionError('不应展开蛇骨岛式地图'))
        runner.wait_confirm = Mock(return_value=yes)

        def recognize(node, frame, override=None):
            if node == 'CatDiaryDestination':
                pattern = override[node]['expected'][0]
                self.assertRegex('尼尔瓦', pattern)
                self.assertIsNone(re.fullmatch(pattern, '博物馆图书区'))
                return outer
            return node in ('CatDiaryEraSelected', 'CatDiaryWorldMap')

        runner.reco = Mock(side_effect=recognize)
        runner.teleport(self.entry)
        target, pattern, names = runner.wait_confirm.call_args.args
        self.assertRegex('博物馆 图书区', pattern)
        self.assertIsNone(re.fullmatch(pattern, '尼尔瓦'))
        self.assertIsNone(re.fullmatch(pattern, '马克米纳尔博物馆'))
        self.assertEqual(names, ['博物馆 图书区'])
        self.assertEqual([c.args[0] for c in runner.click.call_args_list], [outer, yes])
        self.assertFalse(any(c.args[0] == 'CatDiarySwipe' for c in runner.action.call_args_list))

    def test_old_submenu_frames_cannot_click_through_confirmation(self):
        runner = self.runner
        label = SimpleNamespace(best_result=SimpleNamespace(text='博物馆图书区'))
        yes = object()
        runner.frame = Mock(side_effect=['submenu', 'submenu', 'submenu', 'confirmation'])
        runner.text = Mock(side_effect=lambda node, frame, **kw:
                           '即将移动到博物馆 图书区。' if frame == 'confirmation' else '')
        def recognize(node, frame, override=None):
            if node == 'CatDiarySubmenu':
                return frame == 'submenu'
            if node == 'CatDiarySubDestination':
                return label
            return yes if frame == 'confirmation' else None
        runner.reco = Mock(side_effect=recognize)
        result = runner.wait_confirm('尼尔瓦', self.pattern, self.entry['world_names'])
        self.assertIs(result, yes)
        runner.click.assert_called_once_with(label)

    def test_wrong_confirmation_cannot_accept_parent_or_museum(self):
        runner = self.runner
        runner.reco = Mock(return_value=True)
        for name in ['尼尔瓦', '马克米纳尔博物馆', '博物馆图书区深处']:
            with self.subTest(name=name):
                runner.text = Mock(return_value='即将移动到' + name)
                with patch('cat_diary.time.monotonic', side_effect=[0, 0, 11]):
                    with self.assertRaisesRegex(RuntimeError, '确认文字不符'):
                        runner.wait_confirm('尼尔瓦', self.pattern, self.entry['world_names'])
        runner.click.assert_not_called()

    def test_missing_library_item_times_out_without_clicking_other_entries(self):
        runner = self.runner
        runner.text = Mock(return_value='')
        runner.reco = Mock(side_effect=lambda node, *args: node == 'CatDiarySubmenu')
        with patch('cat_diary.time.monotonic', side_effect=[0, 0, 11]):
            with self.assertRaisesRegex(RuntimeError, '确认文字不符'):
                runner.wait_confirm('尼尔瓦', self.pattern, self.entry['world_names'])
        runner.click.assert_not_called()

    def test_unresponsive_submenu_is_not_clicked_repeatedly(self):
        runner = self.runner
        runner.text = Mock(return_value='')
        label = SimpleNamespace(best_result=SimpleNamespace(text='博物馆图书区'))
        runner.reco = Mock(side_effect=lambda node, *args:
                           label if node == 'CatDiarySubDestination' else node == 'CatDiarySubmenu')
        with patch('cat_diary.time.monotonic', side_effect=[0, 0, 1, 2, 11]):
            with self.assertRaisesRegex(RuntimeError, '确认文字不符'):
                runner.wait_confirm('尼尔瓦', self.pattern, self.entry['world_names'])
        runner.click.assert_called_once_with(label)


if __name__ == '__main__':
    unittest.main()
