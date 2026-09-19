"""区域地图闭环移动。页面识别和操作定义位于 navigation.json。"""

import json
import logging
import math
import time
from pathlib import Path

from maa.custom_action import CustomAction


LOG = logging.getLogger(__name__)
DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}


def parse_move(params):
    if not isinstance(params, dict):
        raise ValueError("移动参数必须是对象")
    direction = params.get("direction", "left")
    duration = params.get("duration", 600)
    if direction not in DIRECTIONS:
        raise ValueError("direction 必须为 left/right/up/down")
    if type(duration) is not int or not 150 <= duration <= 1200:
        raise ValueError("duration 必须为 150～1200 毫秒的整数")
    return direction, duration


def route_step(position, target, tolerance=5):
    """已知路段的轴向微调；不把未知地图上的直线视为可通行道路。"""
    dx, dy = target[0] - position[0], target[1] - position[1]
    if math.hypot(dx, dy) <= tolerance:
        return None
    if abs(dx) >= abs(dy):
        direction, distance = ("right" if dx > 0 else "left"), abs(dx)
    else:
        direction, distance = ("down" if dy > 0 else "up"), abs(dy)
    # 巴尔沃基实测 600ms 约 24 地图像素；靠近路点时缩短步长。
    return direction, max(150, min(600, round(distance * 18)))


def marker_position(marker):
    box = marker.box
    position = (box.x + box.w / 2, box.y + box.h / 2)
    # 同一标记可同时命中不同尺寸模板；仅接受中心接近的重叠候选。
    for candidate in marker.filtered_results:
        box = candidate.box
        # RecognitionResult.box 是列表，RecognitionDetail.box 才是 Rect。
        center = (box[0] + box[2] / 2, box[1] + box[3] / 2)
        if math.dist(position, center) > 8:
            raise RuntimeError("角色标记不唯一")
    return position


class Navigator:
    def __init__(self, context):
        self.context = context
        self.deadline = time.monotonic() + 180
        self.navigation_session = None
        self.navigation_key = None
        self.navigation_movement = None
        self.navigation_epoch = 0
        map_data = json.loads((Path(__file__).parent / 'data/cat_diary_maps.json').read_text(encoding='utf-8'))
        self.maps = map_data['maps']
        self.horizontal_slopes = map_data.get('horizontal_slopes', {})
        self.map_anchors = map_data.get('anchors', {})

    def reset_navigation(self):
        """传送、换层或无小地图过渡后，不沿用旧机位和同名地图模型。"""
        self.navigation_session = None
        self.navigation_key = None
        self.navigation_movement = None

    def text(self, node, frame, roi=None, single_line=False):
        result = self.reco(node, frame, {node: {'roi': roi}} if roi else None)
        rows = [r for r in result.all_results if r.score >= .8] if result else []
        if single_line and rows:
            height = max(r.box[3] for r in rows)
            rows = [r for r in rows if r.box[3] >= height * .5]
        order = (lambda r: r.box[0]) if single_line else (lambda r: (r.box[1], r.box[0]))
        return ''.join(r.text for r in sorted(rows, key=order))

    def navigation_interrupted(self, frame):
        return bool(self.reco('NavigationBattle', frame) or self.reco('NavigationRewards', frame))

    def localize(self, aliases=(), road_key=None, movement=None, exact=False, audit=False):
        from minimap_navigation import MiniMapNavigator, NavigationInterrupted
        key = (tuple(aliases), road_key, exact)
        for _ in range(5):
            self.check()
            if self.navigation_session is None or self.navigation_key != key:
                self.navigation_session = MiniMapNavigator(self, aliases[0] if aliases else None,
                                                          aliases=aliases, road_key=road_key,
                                                          exact=exact, allow_full_map=True)
                self.navigation_key = key
            session = self.navigation_session
            try:
                if session.atlas is None or audit:
                    session.calibrate(audit=audit)
                else:
                    session.locate(movement)
                return session
            except NavigationInterrupted:
                # 使用原任务的恢复逻辑，尤其保留月度试炼的结算计数。
                # 普通遇战不会换图；已完成的静态模型仍可重新配准，丢弃本次
                # 采集即可。首次建模被打断才重建会话，避免驻怪点反复长留。
                if session.atlas is None:
                    self.reset_navigation()
                self.world()
        raise RuntimeError('定位连续被战斗打断 5 次，保留现场')

    def audit_navigation(self, target, tolerance):
        if self.navigation_session is None:
            raise RuntimeError('尚未建立导航会话，不能确认到达')
        session = self.localize(*self.navigation_key[:2], exact=self.navigation_key[2], audit=True)
        if math.dist(session.last_map_position, target) > tolerance:
            raise RuntimeError(f'终点整图复核未到达：{session.last_map_position} / {target}')
        return session.position

    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("用户停止任务")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("移动超过 180 秒上限")

    def frame(self):
        self.check()
        frame = self.context.tasker.controller.post_screencap().wait().get()
        if frame is None or frame.shape[:2] != (720, 1280):
            raise RuntimeError("需要 1280×720 控制器截图")
        return frame

    def reco(self, node, frame, override=None):
        result = self.context.run_recognition(node, frame, override or {})
        return result if result and result.hit else None

    def action(self, node, override=None):
        self.check()
        result = self.context.run_action(node, pipeline_override=override or {})
        if not result or not result.success:
            raise RuntimeError(f"动作失败：{node}")

    def wait(self, node, seconds=10):
        deadline = min(self.deadline, time.monotonic() + seconds)
        while time.monotonic() < deadline:
            frame = self.frame()
            if self.reco(node, frame):
                return frame
            time.sleep(0.1)
        raise RuntimeError(f"等待画面超时：{node}")

    def world(self):
        """仅处理已识别战斗/结算；未知弹窗保持不动并超时。"""
        deadline = min(self.deadline, time.monotonic() + 90)
        attacks = 0
        while time.monotonic() < deadline:
            frame = self.frame()
            if self.reco("StartUpWorldReady", frame):
                return frame
            if self.reco("NavigationBattle", frame):
                self.navigation_epoch += 1
                if attacks >= 30:
                    raise RuntimeError("战斗攻击超过 30 次")
                self.action("NavigationBattle")
                attacks += 1
            elif self.reco("NavigationRewards", frame):
                self.navigation_epoch += 1
                self.action("NavigationRewards")
            time.sleep(0.15)
        raise RuntimeError("未恢复可操作主界面")

    def position(self, expected_map=None):
        aliases = (expected_map,) if expected_map else ()
        # 初次无指定名称的单步移动，在读到全名后复用同一会话。
        if self.navigation_session and expected_map == self.navigation_session.map_name:
            aliases = self.navigation_key[0]
        movement, self.navigation_movement = self.navigation_movement, None
        session = self.localize(aliases, movement=movement)
        return session.map_name, session.position

    def move(self, direction, duration, expected_map, previous):
        self.world()
        dx, dy = DIRECTIONS[direction]
        self.action("NavigationSwipe", {"NavigationSwipe": {
            "begin": [200, 450], "end": [200 + dx * 180, 450 + dy * 180],
            "duration": duration, "post_delay": 1500 if dy else 200,
        }})
        self.navigation_movement = direction
        name, position = self.position(expected_map)
        delta = (position[0] - previous[0], position[1] - previous[1])
        LOG.warning("Navigation %s %sms: %s -> %s (%s)", direction, duration, previous, position, name)
        # 标记缩放动画可带来约 2～3px 中心抖动，不能当作真实行走。
        if delta[0] * dx + delta[1] * dy < max(3, min(6, duration * 0.01)):
            raise RuntimeError("未确认预期方向的位移，可能撞墙、路口未对齐或定位失败")
        return position


class NavigationMove(CustomAction):
    def run(self, context, argv):
        try:
            params = json.loads(argv.custom_action_param)
            direction, duration = parse_move(params)
            nav = Navigator(context)
            name, position = nav.position()
            nav.move(direction, duration, name, position)
            nav.audit_navigation(nav.navigation_session.position, 8)
            return True
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            LOG.error("NavigationMove 失败：%s", exc)
            return False
        except Exception:
            # ctypes 回调不能让异常越过边界，否则返回值可能未定义。
            LOG.exception("NavigationMove 未预期异常")
            return False


class NavigationBaruokiRoute(CustomAction):
    def run(self, context, argv):
        try:
            nav = Navigator(context)
            _, position = nav.position("巴尔沃基")
            # 此路段仅适用于传送落点附近，先检查起点，防止从其他道路横穿。
            if not (610 <= position[0] <= 670 and abs(position[1] - 339) <= 8):
                raise RuntimeError(f"请先传送至巴尔沃基；当前位置不在路线起点：{position}")
            for target, tolerance in [((600, 339), 2), ((600, 254), 5)]:
                for _ in range(20):
                    step = route_step(position, target, tolerance)
                    if step is None:
                        break
                    position = nav.move(*step, "巴尔沃基", position)
                if route_step(position, target, tolerance) is not None:
                    raise RuntimeError(f"路点 {target} 超过 20 步")
            nav.audit_navigation((600, 254), 8)
            return True
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            LOG.error("NavigationBaruokiRoute 失败：%s", exc)
            return False
        except Exception:
            LOG.exception("NavigationBaruokiRoute 未预期异常")
            return False


class NavigationMiniMapRoute(CustomAction):
    def run(self, context, argv):
        try:
            from cat_diary import CatDiaryRunner
            from minimap_navigation import MiniMapNavigator, parse_route
            name, points, steps = parse_route(json.loads(argv.custom_action_param))
            runner = CatDiaryRunner(context, max_minutes=5)
            MiniMapNavigator(runner, name).follow(points, steps)
            return True
        except Exception:
            LOG.exception("NavigationMiniMapRoute 失败，保留现场")
            return False


def register(resource):
    """命令行直接注册与 AgentServer 共用同一实现。"""
    return (resource.register_custom_action("NavigationMove", NavigationMove())
            and resource.register_custom_action("NavigationBaruokiRoute", NavigationBaruokiRoute())
            and resource.register_custom_action("NavigationMiniMapRoute", NavigationMiniMapRoute()))
