"""离散机关连接：只有实走确认过的同图端点和按钮区域才可执行。"""

import json
from pathlib import Path
import time


def load_transitions(map_name):
    data = json.loads(Path(__file__).with_name('data').joinpath('minimap_transitions.json').read_text(encoding='utf-8'))
    return data['maps'].get(''.join(map_name.split()), [])


def add_landings(road, transitions):
    # 很短的平台会被角色和出口图例完全覆盖。只保留已实走确认的端点
    # 周围 12px 站立范围，不连起两端，也不把断续机关路径当作可滑动道路。
    for edge in transitions:
        for x, y in (edge['from'], edge['to']):
            gx, gy = round((x-2)/4), round((y-2)/4)
            road.grid[gy-1:gy+2, gx-1:gx+2] = True
            road.raw[gy-1:gy+2, gx-1:gx+2] = True
            road.clearance[gy-1:gy+2, gx-1:gx+2] = 1
    return road


def choose_transition(transitions, used, road, position, target):
    for index, edge in enumerate(transitions):
        if index in used:
            continue
        try:
            # 两侧必须各自有已确认道路；断续台阶本身不加入普通道路网格。
            road.path(position, edge['from'])
            road.path(edge['to'], target)
        except RuntimeError:
            continue
        return index, edge
    return None


def interact(runner, edge):
    frame = runner.world()
    button = runner.reco('NavigationMapInteraction', frame,
                         {'NavigationMapInteraction': {'roi': edge['roi']}})
    if not button:
        raise RuntimeError('已到达机关起点，但未确认交互按钮，停止导航')
    runner.click(button)
    # 确认交互确实开始，避免点击落空时立即把原场景当作完成；最多等 3 秒。
    for _ in range(15):
        time.sleep(.2)
        if not runner.reco('StartUpWorldReady', runner.frame()):
            runner.world()
            return
    raise RuntimeError('机关交互未进入过渡状态，停止导航')
