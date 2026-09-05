"""无需连接设备的参数、到达判定和停止保护测试。"""

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from navigation import NavigationBaruokiRoute, NavigationMove, Navigator, marker_position, parse_move, route_step


class NavigationTests(unittest.TestCase):
    def test_overlapping_templates_are_not_two_players(self):
        box = SimpleNamespace(x=585, y=242, w=30, h=24)
        near = SimpleNamespace(box=[595, 244, 19, 19])
        marker = SimpleNamespace(box=box, filtered_results=[near])
        self.assertEqual(marker_position(marker), (600, 254))
        marker.filtered_results.append(SimpleNamespace(box=[700, 300, 19, 19]))
        with self.assertRaises(RuntimeError):
            marker_position(marker)

    def test_unexpected_exception_cannot_escape_ctypes_callback(self):
        with patch("navigation.Navigator", side_effect=AttributeError("unexpected")):
            self.assertFalse(NavigationMove().run(None, SimpleNamespace(custom_action_param='{}')))
            self.assertFalse(NavigationBaruokiRoute().run(None, None))

    def test_invalid_input_never_moves(self):
        for params in ({"direction": "diagonal"}, {"duration": True}, {"duration": 0}, {"duration": 5000}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                parse_move(params)
        with patch("navigation.Navigator") as navigator:
            self.assertFalse(NavigationMove().run(None, SimpleNamespace(custom_action_param='{"duration":0}')))
            navigator.assert_not_called()

    def test_waypoint_and_overshoot(self):
        self.assertIsNone(route_step((599, 255), (600, 254)))
        self.assertIsNone(route_step((598, 255), (600, 254), 5))
        self.assertEqual(route_step((603, 339), (600, 339), 2)[0], "left")
        self.assertEqual(route_step((610, 339), (600, 339))[0], "left")
        self.assertEqual(route_step((590, 339), (600, 339))[0], "right")
        self.assertEqual(route_step((600, 339), (600, 254))[0], "up")
        self.assertLessEqual(route_step((1200, 339), (600, 339))[1], 600)

    def test_blocked_and_wrong_direction_are_failures(self):
        nav = Navigator(SimpleNamespace(tasker=SimpleNamespace(stopping=False)))
        nav.world = Mock()
        nav.action = Mock()
        for point in [(600, 339), (605, 339), (600, 330)]:
            nav.position = Mock(return_value=("巴尔沃基", point))
            with self.subTest(point=point), self.assertRaises(RuntimeError):
                nav.move("left", 600, "巴尔沃基", (600, 339))

    def test_stopping_and_timeout_send_no_action(self):
        context = SimpleNamespace(tasker=SimpleNamespace(stopping=True), run_action=Mock())
        nav = Navigator(context)
        with self.assertRaises(RuntimeError):
            nav.action("NavigationSwipe")
        context.run_action.assert_not_called()
        context.tasker.stopping = False
        nav.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError):
            nav.action("NavigationSwipe")
        context.run_action.assert_not_called()

    def test_route_rejects_other_road(self):
        with patch("navigation.Navigator") as navigator:
            navigator.return_value.position.return_value = ("巴尔沃基", (445, 424))
            self.assertFalse(NavigationBaruokiRoute().run(None, None))
            navigator.return_value.move.assert_not_called()

    def test_route_does_not_succeed_when_unreachable(self):
        with patch("navigation.Navigator") as navigator:
            navigator.return_value.position.return_value = ("巴尔沃基", (649, 339))
            navigator.return_value.move.return_value = (649, 339)
            self.assertFalse(NavigationBaruokiRoute().run(None, None))
            self.assertEqual(navigator.return_value.move.call_count, 20)


if __name__ == "__main__":
    unittest.main()
