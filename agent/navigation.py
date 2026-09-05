"""区域地图闭环移动。页面识别和操作定义位于 navigation.json。"""

import json
import logging
import math
import time

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
                if attacks >= 30:
                    raise RuntimeError("战斗攻击超过 30 次")
                self.action("NavigationBattle")
                attacks += 1
            elif self.reco("NavigationRewards", frame):
                self.action("NavigationRewards")
            time.sleep(0.15)
        raise RuntimeError("未恢复可操作主界面")

    def position(self, expected_map=None):
        self.world()
        self.action("NavigationToggleLocalMap")
        frame = self.wait("NavigationLocalMap")
        try:
            # 标记有明灭动画，标题出现不等于标记已可见；限定时间等到可识别帧。
            frame = self.wait("NavigationPlayer", seconds=4)
            name = self.reco("NavigationMapName", frame)
            marker = self.reco("NavigationPlayer", frame)
            if not name or not marker:
                raise RuntimeError("无法唯一确认地图名称或角色标记")
            map_name = name.best_result.text.replace(" ", "")
            if expected_map and expected_map not in map_name:
                raise RuntimeError(f"地图不符：预期 {expected_map}，实际 {map_name}")
            return map_name, marker_position(marker)
        finally:
            # 用户停止时不继续发送操作；否则恢复主界面。
            if not self.context.tasker.stopping:
                self.action("NavigationToggleLocalMap")
                self.wait("StartUpWorldReady")

    def move(self, direction, duration, expected_map, previous):
        self.world()
        dx, dy = DIRECTIONS[direction]
        self.action("NavigationSwipe", {"NavigationSwipe": {
            "begin": [640, 450], "end": [640 + dx * 180, 450 + dy * 180],
            "duration": duration,
        }})
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
            return True
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            LOG.error("NavigationBaruokiRoute 失败：%s", exc)
            return False
        except Exception:
            LOG.exception("NavigationBaruokiRoute 未预期异常")
            return False


def register(resource):
    """命令行直接注册与 AgentServer 共用同一实现。"""
    return (resource.register_custom_action("NavigationMove", NavigationMove())
            and resource.register_custom_action("NavigationBaruokiRoute", NavigationBaruokiRoute()))
