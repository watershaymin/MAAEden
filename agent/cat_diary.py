"""猫咪日记：线索解析、道路规划、移动图例追踪及游戏端进度复核。"""

import heapq
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from maa.custom_action import CustomAction

from navigation import DIRECTIONS, Navigator, marker_position


LOG = logging.getLogger(__name__)
DATA = Path(__file__).parent / "data" / "cat_diary.json"
SLOT_ROIS = ([435, 145, 494, 72], [435, 253, 494, 72], [435, 361, 494, 72])


class DiaryOpened(RuntimeError):
    """猫的事件对话结束后，游戏可能自动返回日记。"""


def compact(text):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text)


def load_catalog(path=DATA):
    entries = json.loads(path.read_text(encoding="utf-8"))["locations"]
    ids = set()
    for entry in entries:
        if entry["id"] in ids or not entry["clues"]:
            raise ValueError("猫咪日记地点目录存在重复 ID 或空线索")
        ids.add(entry["id"])
    return entries


def match_clue(text, catalog):
    """按有区分度的原文片段匹配；不以低置信度模糊匹配决定传送目的地。"""
    normalized = compact(text)
    matches = [e for e in catalog if any(compact(c) in normalized for c in e["clues"])]
    destinations = {(e["era"], e["region"], e["location"]) for e in matches}
    if len(destinations) != 1:
        raise ValueError(f"日记线索{'不唯一' if matches else '无法匹配'}：{text}")
    return matches[0]


@dataclass(frozen=True)
class DiaryState:
    # 固定三个猫槽位，不能将某条 OCR 漏识别当成该猫已完成。
    targets: tuple
    stamps: int


def count_stamps(frame):
    count = 0
    # 第七枚盖在礼物图案上；下一次找到猫会从新卡第一枚开始。
    for x in (387, 462, 538, 614, 690, 766, 868):
        patch = frame[514:566, x - 29:x + 30].astype(np.int16)
        b, g, r = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        if np.count_nonzero((r > 130) & (r - g > 65) & (r - b > 65)) > 220:
            count += 1
    return count


def verify_change(before, after):
    if after.stamps < before.stamps and (before.stamps, after.stamps) != (7, 1):
        raise RuntimeError("日记印章减少，可能跨过刷新时间；停止本轮")
    if after == before:
        raise RuntimeError("交互后日记任务和印章均未变化，不能确认找到猫")
    if any(old is None and new is not None for old, new in zip(before.targets, after.targets)):
        raise RuntimeError("已结束的猫重新出现任务，可能进入新一轮日记")


def remaining_seconds(text):
    match = re.fullmatch(r"剩余(?:(\d+)小时)?(?:(\d+)分钟)?(?:(\d+)秒)?", compact(text))
    if not match or not any(match.groups()):
        raise ValueError(f"无法确认日记剩余时间：{text}")
    return sum(int(value or 0) * unit for value, unit in zip(match.groups(), (3600, 60, 1)))


def world_pan_points(pan, labels):
    """保留扫描方向和距离，但避开会吞掉拖动的地点按钮及固定界面。"""
    x1, y1, x2, y2 = pan
    dx, dy = x2 - x1, y2 - y1
    candidates = [(x1, y1)] + [(x, y) for y in range(240, 601, 30)
                              for x in range(80, 1101, 30)]
    valid = [(x, y) for x, y in candidates
             if 80 <= x + dx <= 1100 and 240 <= y + dy <= 600
             and not any(bx - 100 <= x <= bx + bw + 100
                         and by - 25 <= y <= by + bh + 25
                         for bx, by, bw, bh in labels)]
    if not valid:
        raise RuntimeError("世界地图没有可确认的拖动起点")
    x, y = min(valid, key=lambda point: (point[0] - x1) ** 2 + (point[1] - y1) ** 2)
    return [x, y], [x + dx, y + dy]


def erode(mask, radius):
    padded = np.pad(mask, radius)
    result = mask.copy()
    h, w = mask.shape
    for dy in range(radius * 2 + 1):
        for dx in range(radius * 2 + 1):
            result &= padded[dy:dy + h, dx:dx + w]
    return result


class RoadMap:
    """从同一机位主界面/区域图的差分提取实际道路，不跨越没有道路的空白。"""

    scale = 4

    @classmethod
    def from_segments(cls, segments, horizontal_slopes=()):
        road = cls.__new__(cls)
        mask = np.zeros((720, 1280), dtype=bool)
        for x1, y1, x2, y2 in segments:
            if x1 != x2 and y1 != y2:
                raise ValueError("地图中心线只接受轴向路段")
            mask[min(y1, y2) - 6:max(y1, y2) + 7, min(x1, x2) - 6:max(x1, x2) + 7] = True
        slope_mask = np.zeros_like(mask)
        for x1, y1, x2, y2 in horizontal_slopes:
            if x1 == x2 or abs(y2 - y1) > abs(x2 - x1) * 0.5:
                raise ValueError("横向斜坡须由实际横移验证，且坡度不超过 1:2")
            for x in range(min(x1, x2), max(x1, x2) + 1):
                y = round(y1 + (x - x1) * (y2 - y1) / (x2 - x1))
                slope_mask[y - 6:y + 7, x - 6:x + 7] = True
        mask |= slope_mask
        road.slope_mask = slope_mask
        road.raw = mask.reshape(180, 4, 320, 4).mean(axis=(1, 3)) >= 0.5
        road.grid = road.raw
        road.clearance = road.grid.astype(np.int16) + erode(road.grid, 1)
        return road

    def __init__(self, base, overlay, occlusions=(), anchor=None):
        # 实机区域图将场景亮度约减半，半透明道路在其上增加亮度。
        delta = overlay.astype(np.float32) - base.astype(np.float32) * 0.5
        mask = np.min(delta, axis=2) > 20
        mask[:140] = mask[610:] = False
        mask[:, :165] = mask[:, 1120:] = False
        # 仅在已经识别的图例遮挡框内补齐同一直线两端的道路；不跨空白补路。
        hidden = np.zeros(mask.shape, dtype=bool)
        for x, y, w, h in occlusions:
            hidden[max(140, y - 4):min(610, y + h + 6), max(165, x - 4):min(1120, x + w + 4)] = True
        # 图例本身的白色/金色也会在差分中变亮，必须先剔除，不能当作宽路或岔路。
        mask[hidden] = False
        for source, covered in ((mask, hidden), (mask.T, hidden.T)):
            for row in np.where(covered.any(axis=1))[0]:
                starts = np.flatnonzero(source[row, :-1] & ~source[row, 1:]) + 1
                ends = np.flatnonzero(~source[row, :-1] & source[row, 1:]) + 1
                for start in starts:
                    following = ends[ends > start]
                    if not len(following):
                        continue
                    end = following[0]
                    if end - start <= 240 and covered[row, start:end].all():
                        source[row, start:end] = True
        if anchor is not None:
            # 角色站在路端时，环会挡住整段末端，没有第二个可见路端可供补齐。
            # 只把已定位角色连接到其遮挡框内、同轴且有路面宽度支持的可见道路。
            # 不向角色以外延伸，也不跨越未被图例遮挡的空白。
            ax, ay = map(round, anchor)
            original = mask.copy()
            for dx, dy in DIRECTIONS.values():
                for distance in range(1, 49):
                    x, y = ax + dx * distance, ay + dy * distance
                    if not (171 <= x < 1114 and 146 <= y < 604):
                        break
                    support = original[y - 8:y + 9, x] if dx else original[y, x - 8:x + 9]
                    if support.mean() >= 0.8:
                        if dx:
                            mask[ay - 8:ay + 9, min(ax, x):max(ax, x) + 1] = True
                        else:
                            mask[min(ay, y):max(ay, y) + 1, ax - 8:ax + 9] = True
                        break
                    if not hidden[y, x]:
                        break
        # 取 4x4 块的大多数像素，随后去除细小装饰和道路边缘。
        self.raw = mask.reshape(180, 4, 320, 4).mean(axis=(1, 3)) >= 0.8
        self.grid = erode(self.raw, 1)
        self.clearance = self.grid.astype(np.int16)
        for radius in (2, 3):
            self.clearance += erode(self.raw, radius)

    def nearest(self, point, limit=24):
        ys, xs = np.where(self.grid)
        if not len(xs):
            raise RuntimeError("区域图道路提取失败")
        distances = (xs * self.scale + 2 - point[0]) ** 2 + (ys * self.scale + 2 - point[1]) ** 2
        best = int(np.argmin(distances))
        if distances[best] > limit ** 2:
            raise RuntimeError(f"标记附近没有已确认道路：{point}")
        return int(xs[best]), int(ys[best])

    def path(self, start, goal):
        source, target = self.nearest(start), self.nearest(goal, 36)
        queue, costs, previous = [(0, source)], {source: 0}, {}
        while queue:
            cost, point = heapq.heappop(queue)
            if cost != costs[point]:
                continue
            if point == target:
                path = [point]
                while point != source:
                    point = previous[point]
                    path.append(point)
                return [(x * 4 + 2, y * 4 + 2) for x, y in reversed(path)]
            x, y = point
            for dx, dy in DIRECTIONS.values():
                neighbor = x + dx, y + dy
                nx, ny = neighbor
                if not (0 <= nx < 320 and 0 <= ny < 180 and self.grid[ny, nx]):
                    continue
                candidate = cost + 1 + (3 - int(self.clearance[ny, nx])) * 0.35
                if candidate < costs.get(neighbor, float("inf")):
                    costs[neighbor] = candidate
                    previous[neighbor] = point
                    heapq.heappush(queue, (candidate, neighbor))
        raise RuntimeError("猫图例与角色之间没有连续的可确认道路")

    def step(self, position, goal):
        path = self.path(position, goal)
        if len(path) < 2 or math.dist(position, goal) <= 10:
            return None
        # 纳兹里克的已标定斜坡由左右输入通过；像素路径在坡面上的阶梯形
        # 折线不能触发上下换道。仅合并本段已标定斜坡，真实纵向连接路仍单独处理。
        slope_mask = getattr(self, "slope_mask", None)
        if slope_mask is not None:
            slope_end = path[0]
            for point in path:
                if not slope_mask[point[1], point[0]]:
                    break
                slope_end = point
            slope_dx = slope_end[0] - path[0][0]
            slope_dy = slope_end[1] - path[0][1]
            if abs(slope_dx) >= 12 and abs(slope_dx) > abs(slope_dy):
                return "right" if slope_dx > 0 else "left", max(150, min(600, round(abs(slope_end[0] - position[0]) * 18)))
        # 忽略距离起点很近的投影抖动；只走本条轴向道路，转弯后重新截图。
        origin = path[0]
        segment = path[1]
        dx, dy = segment[0] - origin[0], segment[1] - origin[1]
        for point in path[2:]:
            if (point[0] - segment[0], point[1] - segment[1]) != (dx, dy):
                break
            segment = point
        # 区域图路面有宽度，角色环也会偏移。道路内部 4～8px 的纵向投影
        # 不能发成上下滑动：游戏会将其解释为整段换道，而不是几像素微调。
        if dx == 0 and abs(segment[1] - position[1]) <= 8:
            turn = path.index(segment)
            if turn + 1 < len(path) and path[turn + 1][1] == segment[1]:
                origin = segment
                segment = path[turn + 1]
                dx, dy = segment[0] - origin[0], 0
                for point in path[turn + 2:]:
                    if (point[0] - segment[0], point[1] - segment[1]) != (dx, dy):
                        break
                    segment = point
        elif dx and abs(segment[0] - position[0]) <= 8:
            # 破晓之岛的最短横移也有约 14px，不能用它校正路口处 4～8px
            # 的误差。只有下一段确实是纵向连接路时才直接换道，排除路宽内
            # 几像素的投影折线；实机从 x=551 向上会自动对齐 x=547 的路口。
            turn = path.index(segment)
            if turn + 1 < len(path) and path[turn + 1][0] == segment[0]:
                following = path[turn + 1]
                next_dy = following[1] - segment[1]
                for point in path[turn + 2:]:
                    if (point[0] - following[0], point[1] - following[1]) != (0, next_dy):
                        break
                    following = point
                if abs(following[1] - segment[1]) > 8:
                    segment, dx, dy = following, 0, next_dy
        direction = ("right" if dx > 0 else "left") if dx else ("down" if dy > 0 else "up")
        distance = abs(segment[0] - position[0]) if dx else abs(segment[1] - position[1])
        return direction, max(150, min(600, round(distance * 18)))


def player_ring(frame, previous=None, excluded=(), max_distance=65):
    """金色角色环补充定位，排除羽毛；仅接受紧凑、独立的标记候选。"""
    patch = frame[140:610, 165:1120].astype(np.int16)
    b, g, r = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    mask = (r > 170) & (g > 115) & (b < 190) & (r - g > 8) & (g - b > 35)
    for x, y, w, h in excluded:
        mask[max(0, y - 140):max(0, y + h - 140), max(0, x - 165):max(0, x + w - 165)] = False
    remaining = set(zip(*np.where(mask)))
    candidates = []
    while remaining:
        seed = remaining.pop()
        stack, component = [seed], [seed]
        while stack:
            y, x = stack.pop()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = y + dy, x + dx
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        ys, xs = zip(*component)
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if len(component) < 25 or not (10 <= w <= 48 and 10 <= h <= 40):
            continue
        # 环附带方向箭头，整体框中心存在少量偏移；连续帧/位移容差共同约束。
        center = ((min(xs) + max(xs)) / 2 + 165, (min(ys) + max(ys)) / 2 + 140)
        if previous is None or math.dist(previous, center) < max_distance:
            candidates.append(center)
    if not candidates or any(math.dist(candidates[0], other) > 12 for other in candidates):
        return None
    return candidates[0]


class CatDiaryRunner(Navigator):
    def __init__(self, context, max_minutes=45, max_steps=240):
        super().__init__(context)
        self.deadline = time.monotonic() + max_minutes * 60
        self.max_steps = max_steps
        self.catalog = load_catalog()
        map_data = json.loads(DATA.with_name("cat_diary_maps.json").read_text(encoding="utf-8"))
        self.maps = map_data["maps"]
        self.search_points = map_data.get("search_points", {})
        self.horizontal_slopes = map_data.get("horizontal_slopes", {})
        self.map_anchors = map_data.get("anchors", {})
        self.round_deadline = None

    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("用户停止猫咪日记")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("猫咪日记超过运行时间上限")
        if self.round_deadline is not None and time.monotonic() >= self.round_deadline:
            raise RuntimeError("本轮猫咪日记已到刷新时间，停止追踪旧线索")

    def click(self, result):
        self.check()
        box = result.box
        # MaaFramework 会在矩形内随机取点。OCR 框可能包含按钮外的留白，
        # 如破晓之岛标签高 86px 而实际按钮不足 50px，需限定到识别框中心。
        point = (round(box.x + box.w / 2), round(box.y + box.h / 2), 1, 1)
        action = self.context.run_action("CatDiaryClick", box=point)
        if not action or not action.success:
            raise RuntimeError("猫咪日记点击失败")

    def text(self, node, frame, roi=None, single_line=False):
        result = self.reco(node, frame, {node: {"roi": roi}} if roi else None)
        if not result:
            return ""
        rows = [r for r in result.all_results if r.score >= 0.8]
        if single_line and rows:
            # 埃尔吉昂确认句末的句号会单独 OCR 成小号“2”。仅保留与正文同字号的框，
            # 不直接删除数字，避免把真正不同的目的地归并成同一名称。
            height = max(r.box[3] for r in rows)
            rows = [r for r in rows if r.box[3] >= height * 0.5]
        order = (lambda r: r.box[0]) if single_line else (lambda r: (r.box[1], r.box[0]))
        return "".join(r.text for r in sorted(rows, key=order))

    def world(self):
        until = min(self.deadline, time.monotonic() + 90)
        dialogues = attacks = announcements = 0
        diary_since = None
        while time.monotonic() < until:
            frame = self.frame()
            if self.diary_ready(frame):
                if diary_since is None:
                    diary_since = time.monotonic()
                elif time.monotonic() - diary_since >= 1:
                    raise DiaryOpened("游戏已自动返回猫咪日记")
                time.sleep(0.1)
                continue
            diary_since = None
            announcement = self.reco("StartUpCloseAnnouncement", frame)
            if announcement:
                if announcements >= 3:
                    raise RuntimeError("公告连续出现超过三次")
                self.click(announcement)
                announcements += 1
            elif self.reco("CatDiaryDialogue", frame):
                if dialogues >= 20:
                    raise RuntimeError("普通对话超过 20 页，保留现场")
                self.action("CatDiaryDialogue")
                dialogues += 1
            elif self.reco("NavigationRewards", frame):
                self.action("NavigationRewards")
            else:
                battle = self.reco("NavigationBattle", frame)
                if battle:
                    if attacks >= 30:
                        raise RuntimeError("寻猫途中战斗超过 30 轮")
                    self.click(battle)
                    attacks += 1
                elif self.reco("StartUpWorldReady", frame):
                    return frame
            time.sleep(0.1)
        raise RuntimeError("猫咪日记未恢复可操作主界面")

    def diary_ready(self, frame):
        return self.reco("CatDiaryPanel", frame) and self.reco("CatDiaryTitle", frame)

    def open_diary(self):
        frame = self.frame()
        if self.diary_ready(frame):
            return
        if self.reco("NavigationLocalMap", frame):
            self.action("NavigationToggleLocalMap")
        try:
            self.world()
        except DiaryOpened:
            return
        self.action("CatDiaryOpen")
        self.wait("CatDiaryTitle")

    def read_diary(self):
        self.open_diary()
        last = None
        until = min(self.deadline, time.monotonic() + 25)
        reason = "日记尚未稳定"
        while time.monotonic() < until:
            frame = self.frame()
            if not self.diary_ready(frame):
                last = None
                time.sleep(0.1)
                continue
            toast = self.reco("CatDiaryRewardToast", frame)
            if toast:
                self.action("CatDiaryDismissToast")
                last = None
                continue
            if not self.reco("CatDiaryCloseButton", frame):
                last = None
                time.sleep(0.1)
                continue
            try:
                targets = []
                for slot, roi in enumerate(SLOT_ROIS):
                    done_roi = [390, 180 + slot * 108, 54, 48]
                    if self.reco("CatDiarySlotDone", frame, {"CatDiarySlotDone": {"roi": done_roi}}):
                        targets.append(None)
                    else:
                        content = self.text("CatDiaryReadClue", frame, roi)
                        if not content:
                            raise ValueError("某个猫槽位没有文字，不能当成完成")
                        targets.append(match_clue(content, self.catalog)["id"])
                state = DiaryState(tuple(targets), count_stamps(frame))
                if state == last:
                    if any(target is not None for target in state.targets):
                        ttl = remaining_seconds(self.text("CatDiaryRemaining", frame))
                        # 采用显示值的保守下界；后续读取不能延长本轮截止时间。
                        expires = time.monotonic() + ttl
                        self.round_deadline = min(self.round_deadline or expires, expires)
                        self.check()
                    LOG.warning("CatDiary 日记 %s，印章 %s/7", state.targets, state.stamps)
                    return state
                last = state
            except ValueError as exc:
                reason = str(exc)
                last = None
            time.sleep(0.2)
        raise RuntimeError(reason)

    def close_diary(self):
        if not self.diary_ready(self.frame()):
            raise RuntimeError("关闭前未确认猫咪日记页面")
        until = min(self.deadline, time.monotonic() + 20)
        clicks = 0
        while time.monotonic() < until:
            frame = self.frame()
            if not self.diary_ready(frame):
                self.world()
                return
            # 红爪印可能先出现，奖励动画随后才开始；期间右上关闭键会隐藏。
            if self.reco("CatDiaryRewardToast", frame):
                self.action("CatDiaryDismissToast")
            elif self.reco("CatDiaryCloseButton", frame):
                if clicks >= 3:
                    raise RuntimeError("日记关闭按钮连续三次未生效")
                self.action("CatDiaryClose")
                clicks += 1
            time.sleep(0.3)
        raise RuntimeError("日记奖励动画或关闭状态超时")

    def teleport(self, entry):
        if entry.get("approach") == "xeno_research":
            self.teleport({key: value for key, value in entry.items() if key != "approach"})
            self.walk_xeno_research(entry)
            return
        if entry.get("approach") == "nazrik_east":
            source = next(e for e in self.catalog if e["id"] == "cat_43")
            self.teleport(source)
            self.walk_nazrik_east(source)
            return
        self.world()
        self.action("NavigationOpenWorldMap")
        self.wait("CatDiaryWorldMap")
        self.wait("CatDiaryDomain")
        # 大陆切换顺序根据实际世界地图：时代 -> 广域 -> 大陆 -> 地点。
        era = entry["era"]
        # 冥峡界属于“???”时代下的广域分区。
        era_x = {"古代": 82, "现代": 203, "未来": 325, "冥峡界": 447}[era]
        selected_roi = {"CatDiaryEraSelected": {"roi": [era_x - 22, 40, 44, 35]}}
        for _ in range(3):
            # 当前时代图标有透明区域，重复点击可能穿过图标选中后方的城镇标签。
            if self.reco("CatDiaryEraSelected", self.frame(), selected_roi):
                break
            self.action("CatDiarySelectEra", {"CatDiarySelectEra": {"target": [era_x, 115]}})
            selected_until = min(self.deadline, time.monotonic() + 3)
            while time.monotonic() < selected_until:
                if self.reco("CatDiaryEraSelected", self.frame(), selected_roi):
                    break
            else:
                continue
            break
        else:
            raise RuntimeError(f"世界地图未切换到{era}")
        self.select_region("冥峡界" if era == "冥峡界" else entry["region"])
        target = entry["teleport"]
        names = entry.get("world_names", [target])
        expected = "^(?:" + "|".join(r"\s*".join(re.escape(c) for c in compact(name)) for name in names) + ")$"
        outer_expected = ("^" + r"\s*".join(re.escape(c) for c in compact(entry["world_entry"])) + "$"
                          if "world_entry" in entry else expected)
        # 往东、西、上下扫描已观察的世界地图可拖动区域；每次都重新 OCR。
        # 先到西北边界，再逐行扫描；只横扫一次会漏掉南北方向的城镇。
        left = (1100, 430, 420, 430)
        right = (420, 430, 1100, 430)
        north = (900, 270, 900, 600)
        south = (900, 600, 900, 270)
        pans = [right] * 5 + [north] * 5
        for row in range(5):
            pans.extend([left if row % 2 == 0 else right] * 4)
            if row < 4:
                pans.append(south)
        for attempt in range(len(pans) + 1):
            frame = self.frame()
            if not self.reco("CatDiaryWorldMap", frame):
                raise RuntimeError("选择目的地时世界地图不可见")
            label = self.reco("CatDiaryDestination", frame, {"CatDiaryDestination": {"expected": [outer_expected]}})
            if label:
                self.click(label)
                if "world_entry" in entry:
                    # 蛇骨岛先展开独立地图；入口名称不能作为最终传送目的地的别名。
                    label = self.wait_world_destination(entry, expected)
                    self.click(label)
                selected = label.best_result.text
                confirm = self.wait_confirm(selected, expected, names)
                self.click(confirm)
                self.world()
                return
            if attempt == len(pans):
                break
            labels = self.reco("CatDiaryDestination", frame,
                               {"CatDiaryDestination": {"expected": [".+"]}})
            if not labels:
                raise RuntimeError("世界地图标签不可读，无法选择拖动起点")
            begin, end = world_pan_points(pans[attempt], [r.box for r in labels.all_results])
            self.action("CatDiaryPan", {"CatDiaryPan": {"begin": begin, "end": end}})
        raise RuntimeError(f"世界地图未找到已解锁的传送点：{target}（{era}/{entry['region']}）")

    def wait_world_destination(self, entry, expected):
        until = min(self.deadline, time.monotonic() + 10)
        while time.monotonic() < until:
            frame = self.frame()
            # 弹图展开时地形和标签陆续出现；同帧确认分区与最终标签后才点击。
            if self.reco(entry["world_panel"], frame):
                label = self.reco("CatDiaryDestination", frame,
                                  {"CatDiaryDestination": {"expected": [expected]}})
                if label:
                    return label
            time.sleep(0.1)
        raise RuntimeError(f"{entry['world_entry']} 分区或传送点未就绪：{entry['teleport']}")

    def crossing_map_name(self):
        """跨图连接路可能没有小地图；已有地图但标题读不到时不能继续移动。"""
        self.world()
        self.action("NavigationToggleLocalMap")
        until = min(self.deadline, time.monotonic() + 2)
        visible = False
        while time.monotonic() < until:
            frame = self.frame()
            if self.reco("NavigationLocalMap", frame):
                visible = True
                name = compact(self.text("CatDiaryMapName", frame, single_line=True))
                if name:
                    self.action("NavigationToggleLocalMap")
                    self.world()
                    return name
            time.sleep(0.1)
        if visible:
            raise RuntimeError("跨区域地图标题无法确认，保留现场")
        return None

    def walk_nazrik_east(self, source):
        self.check()
        _, position, _, _ = self.locate(source)
        if math.dist(position, (943, 284)) > 35:
            raise RuntimeError(f"纳兹里克东侧路线起点不符：{position}")
        # 实机验证此处沿右侧道路、斜坡和无小地图连接路到达冻时领域东侧。
        # 路线限定起点；每步核验地图或连接路灯具，不将固定步数当成到达。
        for step in range(19):
            self.check()
            name = self.crossing_map_name()
            if name == "冻时领域":
                LOG.warning("CatDiary 已从纳兹里克东侧进入冻时领域，移动 %s 步", step)
                return
            if name is not None and name not in ("影之镇纳兹里克", "影之镇纳茲里克"):
                raise RuntimeError(f"纳兹里克东侧路线出现意外地图：{name}")
            if name is None and not self.reco("CatDiaryNazrikEastPassage", self.world()):
                raise RuntimeError("未确认纳兹里克东侧连接路，停止移动")
            if step == 18:
                break
            self.action("CatDiarySwipe", {"CatDiarySwipe": {
                "begin": [200, 450], "end": [380, 450], "duration": 600, "post_delay": 200,
            }})
        raise RuntimeError("纳兹里克东侧路线超过 18 步，未确认进入冻时领域")

    def walk_xeno_research(self, entry):
        stages = [
            ("异元晶控制所入口", "异元晶控制所入口", (535, 412), (740, 309)),
            ("异元晶控制所研究中心", "异元晶控制所研究中心下层", (564, 462), (760, 258)),
        ]
        for title, road_key, start, target in stages:
            stage = dict(entry, map_names=[title], road_map=road_key)
            previous = movement = None
            stalled = 0
            for step in range(40):
                self.check()
                name, position, _, road = self.locate(stage, previous, movement)
                if name != title or (previous is None and math.dist(position, start) > 20):
                    raise RuntimeError(f"异元晶控制所跨层起点不符：{name} {position}")
                if math.dist(position, target) <= 10:
                    break
                if previous is not None:
                    dx, dy = DIRECTIONS[movement]
                    progress = (position[0] - previous[0]) * dx + (position[1] - previous[1]) * dy
                    stalled = stalled + 1 if progress < 3 else 0
                    if stalled >= 3:
                        raise RuntimeError("异元晶控制所跨层连续三步没有预期位移")
                next_step = road.step(position, target)
                if next_step is None:
                    raise RuntimeError("异元晶控制所尚未到达出口位置")
                movement, duration = next_step
                dx, dy = DIRECTIONS[movement]
                LOG.warning("CatDiary 跨层 %s 第%s步：%s，%s %sms", road_key, step + 1, position, movement, duration)
                self.action("CatDiarySwipe", {"CatDiarySwipe": {
                    "begin": [200, 450], "end": [200 + dx * 180, 450 + dy * 180],
                    "duration": duration, "post_delay": 1500 if dy else 200,
                }})
                previous = position
            else:
                raise RuntimeError(f"异元晶控制所跨层超过 40 步：{road_key}")
            frame = self.wait("CatDiaryXenoDoor")
            door = self.reco("CatDiaryXenoDoor", frame)
            self.click(door)
            self.wait_xeno_transition()
        # 两层同名，必须核验扶梯后的独立落点；旧层出口不能视为跨层完成。
        name, position, _, _ = self.locate(entry)
        if name != "异元晶控制所研究中心" or math.dist(position, (498, 462)) > 20:
            raise RuntimeError(f"未确认进入研究中心深处：{name} {position}")
        LOG.warning("CatDiary 已确认进入异元晶控制所研究中心深处")

    def wait_xeno_transition(self):
        until = min(self.deadline, time.monotonic() + 10)
        while time.monotonic() < until:
            if not self.reco("StartUpWorldReady", self.frame()):
                self.world()
                return
            time.sleep(0.1)
        raise RuntimeError("控制所出口点击后未开始切换场景")

    def select_region(self, region):
        # 每次先展开广域再选大陆，避免沿用上次停留的东方或本土地图。
        # 时代指针先于右下广域按钮恢复；等待按钮就绪并复用同帧识别结果。
        frame = self.wait("CatDiaryDomain")
        button = self.reco("CatDiaryDomain", frame)
        if not button:
            raise RuntimeError("未识别广域入口")
        self.click(button)
        if region == "冥峡界":
            self.wait("CatDiaryUnderworldRegion")
            label = self.reco("CatDiaryUnderworldRegion", self.frame())
            if not label:
                raise RuntimeError("广域地图中未识别冥峡界入口")
            self.click(label)
        else:
            self.wait("CatDiaryRegionMap")
            labels = self.reco("CatDiaryRegionLabels", self.frame())
            prefix = "嘉路" if region == "东方" else "米古"
            matches = [r for r in labels.filtered_results if compact(r.text).startswith(prefix)] if labels else []
            if len(matches) != 1:
                raise RuntimeError(f"广域地图中无法唯一识别{region}大陆")
            self.action("CatDiarySelectRegion", {"CatDiarySelectRegion": {"target": matches[0].box}})
        self.wait("CatDiaryDomain")

    def wait_confirm(self, target, expected, names=None):
        until = min(self.deadline, time.monotonic() + 10)
        while time.monotonic() < until:
            frame = self.frame()
            # 城镇前缀与名称可能被 OCR 分成多个框；只读取确认框第一行，按横坐标合并。
            destination = compact(self.text("CatDiaryConfirmText", frame, single_line=True))
            accepted = {compact(f"即将移动到{name}") for name in (names or [target])}
            question = self.reco("CatDiaryConfirmQuestion", frame)
            confirm = self.reco("CatDiaryConfirmYes", frame)
            if confirm and destination in accepted and question:
                return confirm
            if not confirm and self.reco("CatDiarySubmenu", frame):
                label = self.reco("CatDiarySubDestination", frame, {"CatDiarySubDestination": {"expected": [expected]}})
                if label:
                    target = label.best_result.text
                    self.click(label)
        raise RuntimeError(f"传送确认文字不符：{target}")

    def locate(self, expected, previous=None, movement=None):
        base = self.world()
        self.action("NavigationToggleLocalMap")
        until = min(self.deadline, time.monotonic() + 8)
        road = None
        reason = "区域地图尚未展开"
        while time.monotonic() < until:
            frame = self.frame()
            if not self.reco("NavigationLocalMap", frame):
                continue
            name = compact(self.text("CatDiaryMapName", frame, single_line=True))
            # 日记地点中可带城镇前缀，落地名称须包含传送标签。
            aliases = expected.get("map_names", [expected["teleport"], expected["location"]])
            if not name or not any(compact(alias) in name for alias in aliases):
                reason = f"地图名不符：预期 {expected['location']}，识别 {name or '空白'}"
                time.sleep(0.1)
                continue
            map_key = name if name in self.maps else compact(expected.get("road_map", expected["location"]))
            known_road = (RoadMap.from_segments(self.maps[map_key], self.horizontal_slopes.get(map_key, []))
                          if map_key in self.maps else None)
            offset = (0, 0)
            anchor_config = self.map_anchors.get(map_key)
            if anchor_config:
                # 纳兹里克的区域图随坡面高度整体纵移，固定图例用于恢复标定坐标。
                anchor = self.reco(anchor_config["node"], frame)
                if not anchor:
                    reason = f"{name} 未识别地图定位锚点"
                    continue
                anchor_position = marker_position(anchor)
                offset = tuple(a - b for a, b in zip(anchor_position, anchor_config["point"]))
                if abs(offset[0]) > 8 or abs(offset[1]) > 45:
                    reason = f"{name} 地图锚点偏移超出已验证范围：{offset}"
                    continue
            marker = self.reco("CatDiaryMarker", frame)
            player = self.reco("CatDiaryPlayer", frame)
            position = None
            if player:
                try:
                    position = marker_position(player)
                except RuntimeError:
                    pass
            if position is None:
                excluded = [r.box for r in marker.filtered_results] if marker else []
                quests = self.reco("CatDiaryQuestIcon", frame)
                if quests:
                    # 黄色任务菱形也符合金色范围，且会与角色环连成一块；先剔除任务图标。
                    excluded.extend(r.box for r in quests.filtered_results)
                screen_previous = tuple(a + b for a, b in zip(previous, offset)) if previous else None
                position = player_ring(frame, screen_previous, excluded, 135 if movement in ("up", "down") else 65)
            if position is None:
                reason = f"{name} 未能确认角色标记"
                time.sleep(0.1)
                continue
            screen_position = position
            position = tuple(a - b for a, b in zip(position, offset))
            if known_road is not None:
                try:
                    known_road.nearest(position)
                except RuntimeError:
                    # 伊杜依斯的背景灯笼可短暂命中角色环；已标定地图要求角色在道路附近。
                    reason = f"{name} 角色候选不在已确认道路附近：{position}"
                    time.sleep(0.1)
                    continue
            if previous is not None and math.dist(previous, position) > 70:
                # 上下连接道路会自动换道，600ms 滑动可跨过整段约 85px 的连接路。
                if movement not in ("up", "down") or abs(position[0] - previous[0]) > 12 or abs(position[1] - previous[1]) > 135:
                    raise RuntimeError("角色标记出现不合理跳变")
            obstructions = self.reco("CatDiaryMapIcons", frame)
            boxes = [r.box for r in obstructions.filtered_results] if obstructions else []
            boxes += [r.box for r in marker.filtered_results] if marker else []
            boxes.append([round(screen_position[0] - 40), round(screen_position[1] - 32), 80, 64])
            road = known_road if known_road is not None else RoadMap(base, frame, boxes, position)
            targets = []
            if marker:
                for match in marker.filtered_results:
                    x, y, w, h = match.box
                    point = (x + w / 2 - offset[0], y + h / 2 + 18 - offset[1])
                    if not any(math.dist(point, other) < 12 for other in targets):
                        targets.append(point)
            self.action("NavigationToggleLocalMap")
            self.world()
            return name, position, targets, road
        raise RuntimeError(f"{reason}，保留现场")

    def interact(self):
        until = min(self.deadline, time.monotonic() + 40)
        clicks = 0
        dialogues = 0
        while time.monotonic() < until:
            frame = self.frame()
            if self.diary_ready(frame):
                return True
            if self.reco("CatDiaryDialogue", frame):
                if dialogues >= 20:
                    raise RuntimeError("猫附近普通对话超过 20 页")
                self.action("CatDiaryDialogue")
                dialogues += 1
                continue
            button = self.reco("CatDiaryInteract", frame) if self.reco("StartUpWorldReady", frame) else None
            if button:
                if clicks >= 10:
                    raise RuntimeError("猫交互按钮连续点击落空")
                self.click(button)
                clicks += 1
            elif not clicks:
                return False
            time.sleep(0.1)
        raise RuntimeError("猫交互后未进入日记，不能确认成功")

    def chase(self, entry):
        previous = None
        last_step = None
        last_road = None
        missing = stalled = 0
        map_key = compact(entry.get("road_map", entry["location"]))
        search_points = list(self.search_points.get(map_key, [])) if map_key in self.maps else []
        for step_index in range(self.max_steps):
            self.check()
            if self.interact():
                return
            try:
                name, position, targets, road = self.locate(entry, previous, last_step[0] if last_step else None)
            except DiaryOpened:
                return
            if previous is not None and last_step:
                dx, dy = DIRECTIONS[last_step[0]]
                displacement = (position[0] - previous[0]) * dx + (position[1] - previous[1]) * dy
                stalled = stalled + 1 if displacement < 3 else 0
                if stalled >= 3:
                    raise RuntimeError(f"连续三步没有预期位移，可能撞墙或路口未对齐：{name} {position}")
            searching = not targets and bool(search_points)
            if not targets:
                # 角色环与羽毛重叠时地图模板会漏识别，但场景内仍可交互。
                if self.interact():
                    return
                if searching:
                    # 仅沿实际标定的道路访问已观察到羽毛被遮挡的位置；不是找到猫的证据。
                    targets = [search_points[0]]
                    LOG.warning("CatDiary %s 暂未识别羽毛，沿已确认道路检查 %s", name, targets[0])
                else:
                    missing += 1
                    if missing >= 4:
                        raise RuntimeError(f"{name} 连续四帧没有日记图例；可能位于其他楼层/区域")
                    previous, last_step = position, None
                    continue
            missing = 0
            paths = []
            # 同一张区域图的道路不会随猫和角色移动。优先复用已经走出预期
            # 位移的道路，防止角色环遮住路口时改走另一条绕路、离开后又折返。
            # 旧道路无法规划或实际移动受阻时再使用本帧；猫的位置仍取本帧。
            candidates = []
            if last_road is not None and stalled == 0:
                candidates.append(last_road)
            candidates.append(road)
            for candidate in candidates:
                for target in targets:
                    try:
                        paths.append((len(candidate.path(position, target)), target))
                    except RuntimeError:
                        continue
                if paths:
                    road = candidate
                    break
            if not paths:
                raise RuntimeError(f"当前区域图上无法规划到猫的连续道路：{name}，角色 {position}，图例 {targets}")
            target = min(paths)[1]
            next_step = road.step(position, target)
            if next_step is None:
                # 展开/关闭地图期间猫还会移动，关闭后必须重新确认刚出现的交互按钮。
                if self.interact():
                    return
                if searching:
                    search_points.pop(0)
                    previous, last_step = position, None
                    continue
                raise RuntimeError("已接近日记图例但未发现交互按钮")
            direction, duration = next_step
            dx, dy = DIRECTIONS[direction]
            LOG.warning("CatDiary 追踪 %s 第%s步：%s -> %s，%s %sms", name, step_index + 1, position, target, direction, duration)
            self.action("CatDiarySwipe", {"CatDiarySwipe": {
                "begin": [200, 450], "end": [200 + dx * 180, 450 + dy * 180], "duration": duration,
                "post_delay": 1500 if dy else 200,
            }})
            previous, last_step, last_road = position, next_step, road
        raise RuntimeError("单个地点超过寻猫步数上限")

    def run(self):
        state = self.read_diary()
        for _ in range(24):
            self.check()
            active = [target for target in state.targets if target is not None]
            if not active:
                return
            # 每次重新读取游戏状态，不能用旧三项队列或“已访问地点”集合跳过刷新。
            entry = next(e for e in self.catalog if e["id"] == active[0])
            self.close_diary()
            self.teleport(entry)
            self.chase(entry)
            current = self.read_diary()
            verify_change(state, current)
            state = current
        raise RuntimeError("本轮日记超过 24 次交互上限，检查是否跨过刷新周期")


class CatDiary(CustomAction):
    def run(self, context, argv):
        try:
            params = json.loads(argv.custom_action_param)
            if not isinstance(params, dict):
                raise ValueError("猫咪日记参数必须为对象")
            minutes = params.get("max_minutes", 45)
            steps = params.get("max_steps", 240)
            if type(minutes) is not int or not 5 <= minutes <= 120:
                raise ValueError("运行上限必须为 5～120 分钟的整数")
            if type(steps) is not int or not 10 <= steps <= 600:
                raise ValueError("寻猫步数上限必须为 10～600 的整数")
            CatDiaryRunner(context, minutes, steps).run()
            return True
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            LOG.error("CatDiary 失败：%s", exc)
            return False
        except Exception:
            LOG.exception("CatDiary 未预期异常")
            return False


def register(resource):
    return resource.register_custom_action("CatDiary", CatDiary())
