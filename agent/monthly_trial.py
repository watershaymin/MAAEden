"""星天引导之证的每月 200 胜：进度读取、晓之塔路线和结算计数。"""

import json
import logging
import math
import re
import time
from dataclasses import dataclass

import numpy as np

from maa.custom_action import CustomAction

from navigation import Navigator, DIRECTIONS, marker_position, route_step


LOG = logging.getLogger(__name__)


def compact(text):
    return re.sub(r"\s+", "", text).translate(str.maketrans("（）巣", "()巢"))


def parse_progress(rows):
    """只接受同一卡片内的星天标题和 200 胜分数，拒绝普通试炼和其他档位。"""
    titles = [r for r in rows if "星天" in compact(r.text) and "战士的考验" in compact(r.text)]
    matches = []
    for row in rows:
        text = compact(row.text)
        match = re.fullmatch(r"获得200场战斗的胜利\((\d{1,3})/200\)", text)
        completed = text == "获得200场战斗的胜利" and any(
            compact(reward.text) == "领取奖励" and 30 <= reward.box[1] - row.box[1] <= 90
            and reward.box[0] - row.box[0] >= 300 for reward in rows)
        if not match and not completed:
            continue
        if not any(25 <= row.box[1] - title.box[1] <= 80 for title in titles):
            continue
        # 达成后游戏隐藏 n/200，以同一卡片的“领取奖励”按钮表示已完成。
        value = int(match[1]) if match else 200
        if not 0 <= value <= 200:
            raise ValueError("200 胜进度超出范围")
        matches.append(value)
    if len(matches) > 1:
        raise ValueError("200 胜试炼卡片不唯一")
    return matches[0] if matches else None


def parse_period(rows):
    text = "".join(compact(r.text) for r in rows)
    match = re.search(r"(\d{4}/\d{2}/\d{2})23:59", text)
    if not match:
        raise ValueError("无法读取试炼截止日期")
    return match[1]


@dataclass
class VictoryCounter:
    wins: int = 0
    fighting: bool = False
    rewarded: bool = False

    def observe(self, state):
        if state == "battle":
            self.fighting = True
        elif state == "rewards":
            self.rewarded = True
        elif state == "world":
            if self.fighting and not self.rewarded:
                raise RuntimeError("战斗结束但未确认胜利结算，停止核查")
            if self.rewarded:
                self.wins += 1
            self.fighting = self.rewarded = False
        return self.wins


def verify_progress(previous, current, old_period, period):
    if old_period != period:
        raise RuntimeError("试炼月份发生变化，请重新运行")
    if current < previous:
        raise RuntimeError("游戏内胜场倒退，请检查试炼月份或识别结果")
    if current == previous and current < 200:
        raise RuntimeError("战斗后试炼进度没有增长，停止刷怪")


def nest_player_position(frame):
    """巢穴已知直路内的金色环补充识别，适配与出口箭头重叠的动画。"""
    patch = frame[386:423, 650:735].astype(np.int16)
    blue, green, red = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    mask = (red > 150) & (green > 105) & (blue < 175) & (red - green > 8) & (green - blue > 35)
    remaining = set(zip(*np.where(mask)))
    candidates = []
    while remaining:
        seed = remaining.pop()
        stack, pixels = [seed], [seed]
        while stack:
            y, x = stack.pop()
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                neighbor = y + dy, x + dx
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    pixels.append(neighbor)
        ys, xs = zip(*pixels)
        width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if not (len(pixels) >= 30 and 9 <= width <= 30 and 9 <= height <= 30
                and 0.65 <= width / height <= 1.4 and 0.12 <= len(pixels) / (width * height) <= 0.6):
            continue
        center = (float(min(xs) + max(xs)) / 2 + 650, float(min(ys) + max(ys)) / 2 + 386)
        if 662 <= center[0] <= 718 and 398 <= center[1] <= 406:
            candidates.append((width * height, center))
    if not candidates:
        return None
    # 内环优先；重叠的外环可以共存，分离的两个金色物体则拒绝。
    position = min(candidates)[1]
    if any(math.dist(position, center) > 5 for _, center in candidates):
        return None
    return position


class MonthlyNavigator(Navigator):
    def __init__(self, context, max_minutes=180):
        super().__init__(context)
        self.deadline = time.monotonic() + max_minutes * 60
        self.counter = VictoryCounter()

    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("用户停止任务")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("月度试炼超过运行时间上限")

    def pipeline(self, entry):
        self.check()
        result = self.context.run_task(entry)
        if not result or not result.status.succeeded:
            raise RuntimeError(f"页面导航失败：{entry}")

    def click_match(self, node, result):
        self.check()
        box = result.box
        detail = self.context.run_action(node, box=(box.x, box.y, box.w, box.h))
        if not detail or not detail.success:
            raise RuntimeError(f"点击识别结果失败：{node}")

    def rows(self, node, frame):
        result = self.reco(node, frame)
        return [r for r in result.all_results if r.score >= 0.85] if result else []

    def world(self):
        deadline = min(self.deadline, time.monotonic() + 180)
        attacks = rewards = 0
        before = self.counter.wins
        while time.monotonic() < deadline:
            frame = self.frame()
            # 结算和战斗优先，防止透过遮罩把背景识别为世界。
            if self.reco("MonthlyRewards", frame):
                if rewards >= 12:
                    raise RuntimeError("单场结算超过 12 次操作")
                self.counter.observe("rewards")
                self.action("MonthlyRewards")
                rewards += 1
            elif self.reco("MonthlyAttack", frame):
                if attacks >= 30:
                    raise RuntimeError("单场战斗超过 30 次攻击")
                self.counter.observe("battle")
                self.action("MonthlyAttack")
                attacks += 1
            elif self.reco("StartUpWorldReady", frame):
                self.counter.observe("world")
                if self.counter.wins != before:
                    LOG.warning("MonthlyStarTrial 已确认结算 %s 场", self.counter.wins)
                return frame
            time.sleep(0.2)
        raise RuntimeError("180 秒内未恢复主界面；保留未知画面")

    def position(self, expected_map=None):
        # 放大的地图也不暂停明雷；读取标题和标记期间仍可能进入战斗。
        for _ in range(5):
            self.world()
            self.action("MonthlyToggleLocalMap")
            wait_until = min(self.deadline, time.monotonic() + 10)
            previous_color = None
            while time.monotonic() < wait_until:
                frame = self.frame()
                if self.reco("MonthlyAttack", frame) or self.reco("MonthlyRewards", frame):
                    self.world()
                    break
                if not self.reco("MonthlyLocalMap", frame) or not self.reco("MonthlyTowerMapTitle", frame):
                    time.sleep(0.15)
                    continue
                name = "".join(compact(r.text) for r in self.rows("MonthlyReadMap", frame))
                if not name:
                    time.sleep(0.15)
                    continue
                if expected_map and expected_map not in name:
                    raise RuntimeError(f"晓之塔地图不符：预期 {expected_map}，实际 {name}")
                roi = [563, 289, 173, 144] if "魔物巢穴" in name else [385, 170, 520, 405]
                marker = self.reco("MonthlyPlayer", frame, {"MonthlyPlayer": {"roi": roi}})
                if marker:
                    position = marker_position(marker)
                elif "魔物巢穴" in name:
                    color = nest_player_position(frame)
                    if color is None or previous_color is None or math.dist(color, previous_color) > 4:
                        previous_color = color
                        continue
                    position = color
                    LOG.warning("MonthlyStarTrial 金色环连续两帧定位 %s", position)
                else:
                    time.sleep(0.1)
                    continue
                self.action("MonthlyCloseLocalMap")
                self.world()
                return name, position
            else:
                raise RuntimeError("无法确认晓之塔地图和唯一角色标记，保留现场")
        raise RuntimeError("定位连续被战斗打断 5 次，保留现场")

    def route(self, points, map_name):
        _, position = self.position(map_name)
        for target, tolerance in points:
            for _ in range(20):
                step = route_step(position, target, tolerance)
                if step is None:
                    break
                position = self.move(*step, map_name, position)
            if route_step(position, target, tolerance) is not None:
                raise RuntimeError(f"路点 {target} 超过 20 步")
            LOG.warning("MonthlyStarTrial 路点 %s / %s", map_name, position)
        return position

    def move(self, direction, duration, expected_map, previous):
        self.world()
        before = self.counter.wins
        dx, dy = DIRECTIONS[direction]
        # 连接路会在滑动结束后自动走入；立即打开地图会把换道动作中断。
        settle = 1500 if direction in ("up", "down") else 200
        self.action("MonthlySwipe", {"MonthlySwipe": {
            "begin": [200, 450], "end": [200 + dx * 180, 450 + dy * 180], "duration": duration,
            "post_delay": settle,
        }})
        _, position = self.position(expected_map)
        distance = (position[0] - previous[0]) * dx + (position[1] - previous[1]) * dy
        if distance < max(3, min(6, duration * 0.01)):
            if self.counter.wins > before and math.dist(position, previous) <= 5:
                LOG.warning("MonthlyStarTrial 移动被战斗打断，在同一路点继续")
                return position
            raise RuntimeError(f"未确认 {direction} 位移：{previous} -> {position}")
        LOG.warning("MonthlyStarTrial 移动 %s %sms: %s -> %s", direction, duration, previous, position)
        return position

    def open_trials(self):
        # 菜单本身不暂停明雷：逐页识别，点击后若开战则先结算再恢复导航。
        transitions = 0
        pending = None
        pending_until = 0
        tab_retries = 0
        destinations = {"MonthlyOpenMenu": "MonthlyOpenRecords",
                        "MonthlyOpenRecords": "MonthlyOpenMedals",
                        "MonthlyOpenMedals": "MonthlySelectTrials",
                        "MonthlySelectTrials": "MonthlyTrialsReady"}
        until = min(self.deadline, time.monotonic() + 180)
        while time.monotonic() < until and transitions < 30:
            frame = self.frame()
            if self.reco("MonthlyTrialsReady", frame):
                break
            if pending:
                if self.reco(pending, frame):
                    pending = None
                elif self.reco("MonthlyRewards", frame) or self.reco("MonthlyAttack", frame):
                    self.world()
                    pending = None
                    continue
                elif time.monotonic() < pending_until:
                    time.sleep(0.15)
                    continue
                elif pending == "MonthlyTrialsReady" and tab_retries < 2 and self.reco("MonthlySelectTrials", frame):
                    # 勋章列表入场动画中标签已经可见，但第一次点击可能被游戏忽略。
                    # 标签选择可重复；仅在仍确认勋章页时重试，不重复切换主菜单。
                    self.action("MonthlySelectTrials")
                    tab_retries += 1
                    pending_until = min(until, time.monotonic() + 10)
                    continue
                else:
                    raise RuntimeError(f"菜单跳转未完成：{pending}")
            for node in ("MonthlyOpenRecords", "MonthlyOpenMenu", "MonthlyOpenMedals", "MonthlySelectTrials",
                         "MonthlyCloseWorldMap", "MonthlyCloseLocalMap"):
                if self.reco(node, frame):
                    self.action(node)
                    transitions += 1
                    pending = destinations.get(node)
                    pending_until = min(until, time.monotonic() + 10)
                    break
            else:
                if self.reco("MonthlyRewards", frame) or self.reco("MonthlyAttack", frame):
                    self.world()
                else:
                    time.sleep(0.15)
        else:
            raise RuntimeError("无法在遇敌间隙打开记录菜单")
        self.wait("MonthlyTrialsReady")

    def read_progress(self):
        self.open_trials()
        period = parse_period(self.rows("MonthlyReadPeriod", self.frame()))
        previous = None
        for _ in range(18):
            frame = self.frame()
            if not self.reco("MonthlyTrialsReady", frame):
                raise RuntimeError("试炼页不可见")
            rows = self.rows("MonthlyReadRows", frame)
            current = parse_progress(rows)
            if current is not None:
                time.sleep(0.3)
                second = parse_progress(self.rows("MonthlyReadRows", self.frame()))
                if second == current:
                    LOG.warning("MonthlyStarTrial 游戏进度 %s/200，截止 %s", current, period)
                    return current, period
                raise RuntimeError("两次读取的试炼进度不一致")
            # 顶部标题被裁掉时把该卡片稍微向下拉，重新确认标题归属。
            if any("获得200场战斗的胜利" in compact(r.text) for r in rows):
                self.action("MonthlyScrollTrialsUp")
                continue
            fingerprint = tuple(compact(r.text) for r in rows)
            if fingerprint == previous:
                raise RuntimeError("试炼列表到底，未找到星天 200 胜卡片")
            previous = fingerprint
            self.action("MonthlyScrollTrials")
        raise RuntimeError("试炼列表超过 18 次滚动")

    def close_progress(self):
        self.wait("MonthlyTrialsReady")
        self.action("MonthlyCloseTrials")
        self.world()

    def teleport(self):
        for _ in range(6):
            frame = self.frame()
            if self.reco("MonthlyWorldMap", frame):
                break
            self.world()
            self.action("MonthlyOpenWorldMap")
            until = min(self.deadline, time.monotonic() + 10)
            while time.monotonic() < until:
                frame = self.frame()
                if self.reco("MonthlyWorldMap", frame):
                    break
                if self.reco("MonthlyAttack", frame) or self.reco("MonthlyRewards", frame):
                    break
                time.sleep(0.15)
            if self.reco("MonthlyWorldMap", frame):
                break
        else:
            raise RuntimeError("无法在遇敌间隙打开世界地图")
        self.pipeline("MonthlySelectHollow")
        for _ in range(4):
            frame = self.frame()
            label = self.reco("MonthlyTowerLabel", frame)
            if label:
                self.click_match("MonthlyClick", label)
                self.wait("MonthlyConfirmTower")
                self.action("MonthlyConfirmTower")
                self.world()
                return
            if not self.reco("MonthlyCatMapReady", frame):
                raise RuntimeError("未确认猫人世界地图")
            self.action("MonthlyPanCatMap")
        raise RuntimeError("猫人世界地图中未找到晓之塔")

    def enter_nest(self):
        self.teleport()
        frame = self.wait("MonthlyTowerPortal")
        self.click_match("MonthlyTowerPortal", self.reco("MonthlyTowerPortal", frame))
        self.wait("MonthlyFloorArrived", seconds=20)
        self.world()
        _, position = self.position("第1层")
        if math.dist(position, (653, 530)) > 9:
            raise RuntimeError(f"进塔起点不符：{position}")
        self.route([((653, 445), 5), ((474, 445), 2), ((474, 531), 5)], "第1层")
        # 靠近巢穴图例后角色标记会重叠，最后一段改用真实门按钮确认到达。
        for _ in range(3):
            frame = self.world()
            door = self.reco("MonthlyNestDoor", frame)
            if door:
                self.click_match("MonthlyNestDoor", door)
                self.wait("MonthlyNestArrived", seconds=20)
                self.world()
                _, position = self.position("魔物巢穴")
                if math.dist(position, (711, 402)) > 10:
                    raise RuntimeError(f"巢穴起点不符：{position}")
                return
            self.action("MonthlySwipe", {"MonthlySwipe": {
                "begin": [200, 450], "end": [20, 450], "duration": 500,
            }})
        raise RuntimeError("没有找到左下角巢穴入口")

    def farm(self, count):
        target = self.counter.wins + count
        idle_deadline = time.monotonic() + 120
        while self.counter.wins < target:
            before = self.counter.wins
            self.world()
            if self.counter.wins > before:
                idle_deadline = time.monotonic() + 120
            elif time.monotonic() >= idle_deadline:
                raise RuntimeError("驻点 120 秒没有新的胜利，检查位置或怪物刷新")
            time.sleep(0.3)


class MonthlyStarTrial(CustomAction):
    def run(self, context, argv):
        try:
            params = json.loads(argv.custom_action_param)
            if not isinstance(params, dict):
                raise ValueError("月度试炼参数必须是对象")
            minutes = params.get("max_minutes", 180)
            if type(minutes) is not int or not 10 <= minutes <= 360:
                raise ValueError("运行上限必须为 10～360 分钟的整数")
            nav = MonthlyNavigator(context, minutes)
            progress, period = nav.read_progress()
            if progress == 200:
                return True
            accounted = nav.counter.wins
            nav.close_progress()
            nav.enter_nest()
            nav.route([((670, 402), 5)], "魔物巢穴")
            # 寻路过程的胜场也计入；之后每 25 场读取一次游戏端权威计数。
            while progress < 200:
                observed = nav.counter.wins - accounted
                nav.farm(max(0, min(25, 200 - progress) - observed))
                # 入口一侧没有驻点处的持续贴脸怪，退回后再打开记录，避免反复抢菜单。
                nav.route([((707, 403), 5)], "魔物巢穴")
                current, new_period = nav.read_progress()
                verify_progress(progress, current, period, new_period)
                progress = current
                accounted = nav.counter.wins
                if progress < 200:
                    nav.close_progress()
                    nav.route([((670, 402), 5)], "魔物巢穴")
            return True
        except (ValueError, TypeError, RuntimeError) as exc:
            LOG.error("MonthlyStarTrial 失败：%s", exc)
            return False
        except Exception:
            LOG.exception("MonthlyStarTrial 未预期异常")
            return False


def register(resource):
    return resource.register_custom_action("MonthlyStarTrial", MonthlyStarTrial())
