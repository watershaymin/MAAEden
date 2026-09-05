"""蓝门副本选择与结算计数；副本目录独立存储在 data/dungeons.json。"""

import json
import logging
import re
import time
from pathlib import Path

import numpy as np
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from navigation import Navigator


LOG = logging.getLogger(__name__)
CATEGORIES = {"古代": (85, 110), "现代": (200, 110), "未来": (325, 110),
              "???": (450, 110), "虚时层": (580, 110), "封域": (1050, 110), "异境": (1190, 110)}


def normalize(text):
    return re.sub(r"\s+", "", text).translate(str.maketrans({"（": "(", "）": ")", "，": ","}))


def parse_request(params, catalog):
    if not isinstance(params, dict):
        raise ValueError("副本参数必须是对象")
    count = params.get("count", 1)
    if isinstance(count, str) and re.fullmatch(r"[1-9][0-9]{0,2}", count):
        count = int(count)
    if type(count) is not int or not 1 <= count <= 999:
        raise ValueError("跳过次数必须是 1～999 的整数")
    matches = [v for v in catalog["dungeons"] if v["id"] == params.get("target")]
    if len(matches) != 1:
        raise ValueError("副本标识无效或不唯一")
    target = matches[0]
    if not target.get("can_enter") or not target.get("can_skip"):
        raise ValueError("该目录项尚未确认可以进入并跳过")
    if (target.get("ticket") not in ("red", "green")
            or type(target.get("ticket_cost")) is not int or target["ticket_cost"] <= 0):
        raise ValueError("缺少已验证的票种或票数")
    return target, count


def verify_party(text, target):
    text = normalize(text)
    ticket = {"red": "红", "green": "绿"}[target["ticket"]]
    cost = f"消耗{target['ticket_cost']}个{ticket}色解锁卡"
    destination = "移动到" + normalize(target.get("confirmation_name", target["name"]))
    destination += "(" + target["difficulty"] + ")"
    return cost in text and destination in text and "克洛诺斯" not in text


def proof_refill_allowed(text, ticket=None):
    """补票必须正向识别允许消耗的道具；石头优先否决。"""
    text = normalize(text)
    if "克洛诺斯" in text or "之石" in text:
        return False
    offer = re.search(r"要使用1次导证之力,?回复([红绿])色解锁卡吗", text)
    remaining = re.search(r"导证之力[:：]?剩余([0-9]+)次", text)
    return bool(offer and remaining and int(remaining[1]) > 0
                and (ticket is None or offer[1] == {"red": "红", "green": "绿"}[ticket]))


def blank_map_point(rows):
    candidates = [(350, 400), (500, 350), (150, 350), (500, 500),
                  (150, 500), (350, 550), (500, 250), (150, 250)]
    candidates += [(x, y) for y in (220, 280, 340, 400, 460, 520, 580)
                   for x in (100, 200, 300, 400, 500, 600)]
    for x, y in candidates:
        if not any(v.box[0] - 140 <= x <= v.box[0] + v.box[2] + 140
                   and v.box[1] - 40 <= y <= v.box[1] + v.box[3] + 40 for v in rows):
            return x, y
    raise RuntimeError("未找到详情页外侧的地图空白区域")


class DungeonNavigator(Navigator):
    def select_category(self, era):
        point = CATEGORIES[era]
        if era in ("封域", "异境"):
            self.click(point)
            return
        override = {"DungeonCategorySelected": {"roi": [point[0] - 25, 35, 50, 40]}}
        if not self.reco("DungeonCategorySelected", self.frame(), override):
            self.click(point)
        if not self.reco("DungeonCategorySelected", self.frame(), override):
            raise RuntimeError(f"未确认切换到时层：{era}")

    def dismiss_detail(self):
        for attempt in range(4):
            frame = self.frame()
            if not self.reco("DungeonCloseDetail", frame):
                if self.reco("DungeonMenuReady", frame) or self.reco("DungeonCloseNested", frame):
                    return True
                raise RuntimeError("关闭详情后未确认回到地图")
            if attempt == 3:
                break
            self.click(blank_map_point(self.text(frame)))
        raise RuntimeError("详情页经过 3 次空白处点击后仍未关闭")

    def text(self, frame):
        result = self.reco("DungeonReadText", frame)
        if not result:
            return []
        return [v for v in result.all_results if v.score >= 0.8]

    def click(self, point):
        self.action("DungeonClick", {"DungeonClick": {"target": list(point)}})
        self.settle()

    def settle(self):
        """等待地图移动或面板展开结束；背景的小面积特效不影响判断。"""
        old = self.frame()
        deadline = time.monotonic() + 8
        stable = 0
        while time.monotonic() < deadline:
            frame = self.frame()
            delta = np.abs(frame[200:610, 100:1100].astype(float)
                           - old[200:610, 100:1100].astype(float)).mean()
            stable = stable + 1 if delta < 1.5 else 0
            if stable >= 2 and self.text(frame):
                return
            old = frame
            time.sleep(0.2)
        raise RuntimeError("地图/面板动画未稳定")

    def label(self, rows, text, minimum_y=None):
        if minimum_y is None:
            minimum_y = getattr(self, "label_min_y", 190)
        expected = normalize(text)
        visible = [v for v in rows if v.box[1] >= minimum_y]
        matches = [list(v.box) for v in visible if normalize(v.text) == expected]
        for start in visible:
            joined = normalize(start.text)
            if not joined or joined == expected or not expected.startswith(joined):
                continue
            x, y, w, h = start.box
            right = x + w
            for _ in range(3):
                parts = [v for v in visible if 0 <= v.box[0] - right <= 60
                         and abs(v.box[1] + v.box[3] / 2 - (y + h / 2)) <= max(h, v.box[3]) * 0.7
                         and expected.startswith(joined + normalize(v.text))]
                if len(parts) != 1:
                    break
                part = parts[0]
                joined += normalize(part.text)
                right = part.box[0] + part.box[2]
                if joined == expected:
                    matches.append([x, min(y, part.box[1]), right - x,
                                    max(y + h, part.box[1] + part.box[3]) - min(y, part.box[1])])
                    break
        points = []
        for x, y, w, h in matches:
            point = (x + w // 2, y + h // 2)
            if all(abs(point[0] - old[0]) + abs(point[1] - old[1]) > 10 for old in points):
                points.append(point)
        if len(points) > 1:
            raise RuntimeError(f"同名入口不唯一：{text}")
        return points[0] if points else None

    def pan(self, direction, rows):
        dx, dy = {"R": (550, 0), "L": (-550, 0), "D": (0, 350), "U": (0, -350)}[direction]
        candidates = [(x, y) for y in [420, 500, 320, 550, 240]
                      for x in ([350, 450, 550, 650] if dx >= 0 else [950, 850, 750, 650])]
        safe = [(x, y) for x, y in candidates if 70 <= x + dx <= 1210 and 70 <= y + dy <= 670
                and not any(v.box[0] - 110 <= x <= v.box[0] + v.box[2] + 110
                            and v.box[1] - 25 <= y <= v.box[1] + v.box[3] + 25 for v in rows)]
        if not safe:
            raise RuntimeError("找不到地图空白拖动起点")
        x, y = safe[0]
        self.action("DungeonPan", {"DungeonPan": {"begin": [x, y], "end": [x + dx, y + dy]}})
        self.settle()

    def select_label(self, text, allow_pan=True):
        """先找当前视野；缺失时从地图边界逐行搜索，不能拖动副本详情卡片。"""
        def inspect():
            frame = self.frame()
            rows = self.text(frame)
            point = self.label(rows, text)
            if point:
                self.click(point)
                return True, frame, rows
            if any("推荐等级" in v.text or "将消耗" in v.text for v in rows):
                raise RuntimeError(f"当前是详情/确认页，目录路径无法继续：{text}")
            return False, frame, rows

        hit, frame, rows = inspect()
        if hit:
            return
        if not allow_pan:
            raise RuntimeError(f"未找到选项：{text}")

        def advance(direction):
            nonlocal frame, rows
            old = frame
            self.pan(direction, rows)
            hit, frame, rows = inspect()
            delta = np.abs(frame[210:610, 100:1100].astype(float)
                           - old[210:610, 100:1100].astype(float)).mean()
            return hit, delta > 1.5

        def origin():
            for direction in ["R", "D"]:
                for _ in range(10):
                    hit, changed = advance(direction)
                    if hit:
                        return True
                    if not changed:
                        break
                else:
                    raise RuntimeError("地图原点边界无法确认")
            return False

        if origin():
            return
        # 调查轨迹仅用于缩短搜索，仍逐帧核对标签；失效时退回完整扫描。
        hint = getattr(self, "search_routes", {}).get(text, [])
        for direction in hint:
            hit, _ = advance(direction)
            if hit:
                return
        if hint and origin():
            return
        for row in range(8):
            for _ in range(10):
                hit, changed = advance("L" if row % 2 == 0 else "R")
                if hit:
                    return
                if not changed:
                    break
            else:
                raise RuntimeError("地图横向边界无法确认")
            hit, changed = advance("U")
            if hit:
                return
            if not changed:
                break
        raise RuntimeError(f"遍历当前地图后仍未找到：{text}")

    def party_matches(self, target):
        frame = self.frame()
        text = " ".join(v.text for v in self.text(frame) if v.box[1] < 100)
        return verify_party(text, target) and bool(self.reco("DungeonSkipActive", frame))

    def choose(self, target):
        if self.party_matches(target):
            return
        path = target["path"]
        self.label_min_y = 190
        catalog = json.loads((Path(__file__).parent / "data" / "dungeons.json").read_text(encoding="utf-8"))
        regions = {m["region"]: m for m in catalog["maps"] if m["era"] == path[0]}
        self.select_category(path[0])
        if path[0] in ("封域", "异境"):
            rows = self.text(self.frame())
            headers = [normalize(v.text) for v in rows if v.box[1] < 170]
            levels = re.findall(r"非常困难|困难", " ".join(headers))
            if target["difficulty"] not in levels:
                self.click((1180, 110 if path[0] == "封域" else 126))
                rows = self.text(self.frame())
                if target["difficulty"] not in re.findall(r"非常困难|困难", " ".join(v.text for v in rows if v.box[1] < 170)):
                    raise RuntimeError("特殊副本难度切换未确认")
        elif len(path) > 1 and path[1] in regions:
            if self.reco("DungeonOpenWide", self.frame()):
                self.action("DungeonOpenWide")
                self.settle()

        for name in path[1:]:
            self.select_label(name, allow_pan=path[0] not in ("封域", "异境"))
            self.label_min_y = 90 if self.reco("DungeonCloseNested", self.frame()) else 190
            self.search_routes = {}
            if name in regions:
                self.search_routes = regions[name].get("search_routes", {})
        if path[0] not in ("封域", "异境"):
            self.select_label(target["difficulty"], allow_pan=False)
        frame = self.frame()
        text = " ".join(v.text for v in self.text(frame) if v.box[1] < 100)
        if not verify_party(text, target):
            raise RuntimeError(f"副本、难度或票数核对失败：{text}")
        if not self.reco("DungeonSkipActive", frame):
            raise RuntimeError("跳过按钮未启用；不会改为正常进入副本")

    def refill(self, target, source_action, text):
        if not proof_refill_allowed(text, target["ticket"]):
            raise RuntimeError("补票项目、票种或导证之力剩余次数未通过核对")
        LOG.warning("DungeonSkip %s: 申请使用 1 次导证之力补充 %s 票", target["id"], target["ticket"])
        self.action("DungeonProofRefill")
        color = {"red": "红", "green": "绿"}[target["ticket"]]
        override = {"DungeonProofReceived": {"expected": [f"^获得了{color}色解锁卡[1-9][0-9]*个.*$"]}}
        deadline = time.monotonic() + 20
        while not self.reco("DungeonProofReceived", self.frame(), override):
            if time.monotonic() >= deadline:
                raise RuntimeError("使用导证之力后未确认获得对应解锁卡")
        self.action("DungeonProofReceived")
        LOG.warning("DungeonSkip %s: 已确认 %s 票补充到账", target["id"], target["ticket"])
        # 补票会返回此前的队伍/继续页面，本身不会执行下一次跳过。
        self.wait(source_action, 15)
        if source_action == "DungeonSkipActive" and not self.party_matches(target):
            raise RuntimeError("补票返回后副本或队伍确认页发生变化")
        self.action(source_action)
        if source_action == "DungeonContinueSkip":
            self.leave_continue_page()

    def leave_continue_page(self):
        deadline = time.monotonic() + 10
        while self.reco("DungeonContinuePage", self.frame()):
            if time.monotonic() >= deadline:
                raise RuntimeError("继续跳过后页面未离开，停止避免重复提交")

    def skip(self, target, count):
        self.choose(target)
        self.action("DungeonSkipActive")
        source_action = "DungeonSkipActive"
        refills_for_run = 0
        completed = 0
        cycle_deadline = time.monotonic() + 90
        while completed < count:
            frame = self.frame()
            rows = self.text(frame)
            text = " ".join(v.text for v in rows)
            if "克洛诺斯" in text and any(v in text for v in ("消耗", "补充", "使用", "回复")):
                raise RuntimeError("检测到克洛诺斯之石补票窗口，停止且不确认")
            if "回复猫掌特急券" in normalize(text):
                raise RuntimeError(f"猫掌特急券不足，已完成 {completed}/{count} 次；仅自动补充红绿解锁卡")
            if self.reco("DungeonProofRefill", frame):
                if refills_for_run >= 1:
                    raise RuntimeError("本次跳过补票后仍再次要求补票，停止")
                self.refill(target, source_action, text)
                refills_for_run += 1
                cycle_deadline = time.monotonic() + 90
                continue
            if self.reco("DungeonContinuePage", frame):
                completed += 1
                refills_for_run = 0
                LOG.warning("DungeonSkip %s: 已完成 %s/%s", target["id"], completed, count)
                if completed == count:
                    self.action("DungeonEndSkip")
                    self.wait("StartUpWorldReady", 20)
                    return completed
                source_action = "DungeonContinueSkip"
                self.action(source_action)
                # 必须看到上一轮继续页离开，避免把未生效点击重复计数。
                self.leave_continue_page()
                cycle_deadline = time.monotonic() + 90
            elif self.reco("DungeonCongratulations", frame):
                self.action("DungeonCongratulations")
            elif self.reco("DungeonWhiteCardReward", frame):
                self.action("DungeonWhiteCardReward")
            elif time.monotonic() >= cycle_deadline:
                raise RuntimeError(f"结算超时，已确认完成 {completed}/{count} 次")
        return completed


class DungeonSkip(CustomAction):
    def run(self, context, argv):
        try:
            catalog = json.loads((Path(__file__).parent / "data" / "dungeons.json").read_text(encoding="utf-8"))
            target, count = parse_request(json.loads(argv.custom_action_param), catalog)
            nav = DungeonNavigator(context)
            if not nav.party_matches(target):
                entrance = context.run_task("DungeonEntrance")
                if not entrance or not entrance.nodes or entrance.nodes[-1].name != "DungeonMenuReady":
                    raise RuntimeError("蓝门前置未完成")
            nav.deadline = time.monotonic() + 600 + count * 90
            return nav.skip(target, count) == count
        except Exception:
            LOG.exception("DungeonSkip 失败")
            return False


class DungeonDismissDetail(CustomAction):
    def run(self, context, argv):
        try:
            return DungeonNavigator(context).dismiss_detail()
        except Exception:
            LOG.exception("DungeonDismissDetail 失败")
            return False


class DungeonMenuRecognition(CustomRecognition):
    def analyze(self, context, argv):
        try:
            base = context.run_recognition("DungeonMenuBase", argv.image)
            if not base or not base.hit:
                return None
            for node in ("DungeonReturnParty", "DungeonCloseDetail", "DungeonCloseNested"):
                overlay = context.run_recognition(node, argv.image)
                if overlay and overlay.hit:
                    return None
            return CustomRecognition.AnalyzeResult(box=(560, 0, 180, 40), detail={"screen": "dungeon_menu"})
        except Exception:
            LOG.exception("DungeonMenuRecognition 失败")
            return None


def register(resource):
    return (resource.register_custom_action("DungeonSkip", DungeonSkip())
            and resource.register_custom_action("DungeonDismissDetail", DungeonDismissDetail())
            and resource.register_custom_recognition("DungeonMenuReady", DungeonMenuRecognition()))
