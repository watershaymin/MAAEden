"""在已确认的入场队伍页切换预设栏位，每次点击后重新读取选中圆点。"""

import logging
import re
import time


LOG = logging.getLogger(__name__)
TEAM_CENTERS = (508, 537, 567, 596, 626, 655, 685, 714, 744, 774)


def parse_team(value=0):
    if isinstance(value, str) and re.fullmatch(r"[0-9]|10", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= 10:
        raise ValueError("队伍必须为 0～10 的整数，0 表示保持当前队伍")
    return value


def marker_team(result):
    """只接受一个选中标记，且须位于已实测的十个栏位之一。"""
    matches = result.filtered_results if result else []
    if len(matches) != 1:
        return None
    x, y, w, h = matches[0].box
    x, y = x + w / 2, y + h / 2
    if not 558 <= y <= 570:
        return None
    positions = [i + 1 for i, center in enumerate(TEAM_CENTERS) if abs(x - center) <= 3]
    return positions[0] if len(positions) == 1 else None


def read_team(nav, page_node):
    deadline = min(nav.deadline, time.monotonic() + 8)
    previous = None
    while time.monotonic() < deadline:
        frame = nav.frame()
        current = marker_team(nav.reco("TeamSelectionMarker", frame)) if nav.reco(page_node, frame) else None
        if current is not None and current == previous:
            return current
        previous = current
        time.sleep(0.1)
    raise RuntimeError("无法确认入场队伍页及唯一的队伍栏位，停止且不提交入场")


def select_team(nav, team, page_node):
    team = parse_team(team)
    if team == 0:
        return
    current = read_team(nav, page_node)
    right = (team - current) % 10
    left = (current - team) % 10
    direction, steps = (1, right) if right <= left else (-1, left)
    node = "TeamSelectionRight" if direction == 1 else "TeamSelectionLeft"
    for _ in range(steps):
        nav.action(node)
        expected = (current - 1 + direction) % 10 + 1
        observed = read_team(nav, page_node)
        if observed != expected:
            raise RuntimeError(f"队伍切换未确认：预期队伍 {expected}，实际队伍 {observed}，停止且不提交入场")
        current = observed
    LOG.warning("TeamSelection 已确认队伍 %s", current)
