"""幻璃境：依据标题、事件与奖励画面推进，终境保留给玩家。"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from maa.custom_action import CustomAction

from navigation import Navigator

LOG = logging.getLogger(__name__)
ROOM_NAMES = {
    "壹之境": "first", "贰之境": "second", "貳之境": "second",
    "叁之境": "third", "參之境": "third", "肆之境": "fourth",
    "伍之境": "baruoki", "陆之境": "sixth", "陸之境": "sixth",
    "终之境": "last", "終之境": "last", "猫之境": "cats", "貓之境": "cats",
    "稻草人之境": "scarecrows",
}


class PhantomJackpot(RuntimeError):
    """终境已停机；调用方不得重试、回城或继续耗票。"""


def console_jackpot_alert():
    """独立命令行没有 GUI focus 消息接收者时，使用 Windows 原生提示。"""
    if sys.platform == "win32" and os.environ.get("MAAEDEN_CONSOLE_ALERT") == "1":
        subprocess.Popen([
            sys.executable, "-X", "utf8", "-c",
            "import ctypes; ctypes.windll.user32.MessageBoxW(0, '你撞大运了', 'MAAEden · 幻璃境', 0x10040)",
        ], creationflags=subprocess.CREATE_NO_WINDOW)


def room_from_text(text):
    text = re.sub(r"\s+", "", text)
    if "此岸" in text or "地牢" in text:
        return "dungeon"
    # 终境优先，不按访问次数推算：猫之境等随机分支会增加层数。
    for title in ("终之境", "終之境", *ROOM_NAMES):
        if title in text:
            return ROOM_NAMES[title]
    return None


def distinct_points(result):
    points = []
    if result:
        for hit in sorted(result.filtered_results, key=lambda h: h.score, reverse=True):
            x, y, w, h = hit.box
            point = (x + w // 2, y + h // 2)
            if all(abs(point[0] - old[0]) + abs(point[1] - old[1]) > 28 for old in points):
                points.append(point)
    return sorted(points)


def verify_white_party(text):
    text = re.sub(r"\s+", "", text).replace("（", "(").replace("）", ")")
    return ("消耗1个白色解锁卡" in text and "移动到幻璃境(困难)" in text
            and "克洛诺斯" not in text)


def stationary_scene(before, after):
    """只用本次两帧判断是否碰到边界，不按滑动时间累计位置。"""
    a = cv2.cvtColor(before[100:350, 80:1200], cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(after[100:350, 80:1200], cv2.COLOR_BGR2GRAY).astype(np.float32)
    (dx, dy), score = cv2.phaseCorrelate(a, b)
    return score >= .3 and abs(dx) < 3 and abs(dy) < 3


class PhantomRunner(Navigator):
    def __init__(self, context):
        super().__init__(context)
        self.deadline = time.monotonic() + 600
        self.room = None
        self.visited = []
        self.out = Path("debug/phantom")
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.sequence = 0
        self.chests_opened = 0
        self.cat_collected = False
        self.baruoki_left_checked = False

    def record(self, label, frame=None, **fields):
        self.out.mkdir(parents=True, exist_ok=True)
        self.sequence += 1
        name = f"{self.run_id}-{self.sequence:03d}-{label}"
        if frame is not None:
            cv2.imwrite(str(self.out / (name + ".png")), frame)
        row = dict(time=time.time(), run=self.run_id, room=self.room, event=label, **fields)
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        LOG.warning("Phantom %s", json.dumps(row, ensure_ascii=False))

    def title(self, frame):
        result = self.reco("PhantomTitle", frame)
        text = " ".join(h.text for h in result.all_results if h.score >= .75) if result else ""
        room = room_from_text(text)
        if not room and self.reco("PhantomSceneFirst", frame):
            room = "first"
        return room

    def observe_room(self, frame):
        room = self.title(frame)
        if room and room != self.room:
            self.room = room
            self.visited.append(room)
            self.chests_opened = 0
            self.cat_collected = False
            self.baruoki_left_checked = False
            self.record("room", frame, visited=self.visited)
        if self.room == "last":
            self.record("jackpot", frame)
            # focus 在 GUI 中显示通知；post_stop 不在 Custom 回调内等待，避免死锁。
            self.context.run_action("PhantomJackpot")
            self.context.tasker.post_stop()
            console_jackpot_alert()
            raise PhantomJackpot("你撞大运了")
        return room

    def events(self, frame):
        return distinct_points(self.reco("PhantomEvent", frame))

    def click(self, point):
        self.action("PhantomClick", {"PhantomClick": {"target": list(point)}})

    def enter(self):
        from dungeons import DungeonNavigator
        nav = DungeonNavigator(self.context)
        nav.deadline = self.deadline
        entrance = self.context.run_task("DungeonEntrance")
        if not entrance or not entrance.status.succeeded or entrance.nodes[-1].name != "DungeonMenuReady":
            raise RuntimeError("幻璃境：蓝门前置未完成")
        if not self.reco("PhantomWhiteAvailable", self.frame()):
            raise RuntimeError("幻璃境：未确认持有白色解锁卡")
        nav.select_category("???")
        frame = nav.frame()
        if not nav.label(nav.text(frame), "幻璃境"):
            if nav.reco("DungeonOpenWide", frame):
                nav.action("DungeonOpenWide")
                nav.settle()
            nav.select_label("幻象界")
        nav.select_label("幻璃境")
        nav.select_label("困难", allow_pan=False)
        frame = self.frame()
        header = " ".join(v.text for v in nav.text(frame) if v.box[1] < 100)
        if not verify_white_party(header):
            raise RuntimeError(f"幻璃境：白票、目标或难度核对失败：{header}")
        move = nav.label(nav.text(frame), "移动", minimum_y=550)
        if not move:
            raise RuntimeError("幻璃境：没有识别到移动按钮")
        self.record("enter", frame)
        self.click(move)
        return self.wait_room()

    def wait_room(self, allow_world=False):
        deadline = min(self.deadline, time.monotonic() + 35)
        stable = 0
        last_events = []
        while time.monotonic() < deadline:
            frame = self.frame()
            self.observe_room(frame)
            if allow_world and self.reco("StartUpWorldReady", frame):
                return frame
            events = self.events(frame)
            same = len(events) == len(last_events) and all(
                abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 8 for a, b in zip(events, last_events))
            stable = stable + 1 if same and self.reco("PhantomWorld", frame) else 0
            if self.room and stable >= 3:
                self.record("ready", frame, points=events)
                return frame
            last_events = events
            time.sleep(.12)
        self.record("unknown-room", self.frame())
        raise RuntimeError("幻璃境：35 秒内未确认层标题和稳定事件点")

    def run(self, enter=True):
        frame = self.enter() if enter else self.wait_room()
        moves = 0
        search_direction = -1
        stationary = 0
        boundaries = 0
        previous_room = self.room
        for _ in range(120):
            if self.room != previous_room:
                moves = 0
                search_direction = -1
                stationary = 0
                boundaries = 0
                previous_room = self.room
            if self.room == "first":
                right = [p for p in self.events(frame) if p[0] > 640]
                if not right:
                    raise RuntimeError("幻璃境壹之境：未发现右侧出口，避开左侧统计")
                frame = self.interact(right[-1], "exit")
                continue
            if self.room == "dungeon":
                self.run_dungeon(frame)
                self.record("complete", self.frame(), visited=self.visited)
                return tuple(self.visited)
            if self.room not in ("second", "third", "fourth", "baruoki", "sixth"):
                self.record("survey", frame, points=self.events(frame))
                raise RuntimeError(f"幻璃境：尚未确认 {self.room} 的事件规则，已保留现场并停止")
            special_cat_room = self.room in ("baruoki", "sixth")
            black_objects = distinct_points(self.reco("PhantomBlackCat", frame)) if special_cat_room else []
            black_events = [p for p in self.events(frame) if any(
                abs(p[0] - q[0]) <= 50 and 50 <= q[1] - p[1] <= 240 for q in black_objects)]
            if self.chests_opened >= 3 and black_events:
                frame = self.interact(black_events[0], "black-cat")
                continue
            cats = [p for p in self.loot_points(frame, "cat") if p not in black_events]
            if cats and not self.cat_collected:
                frame = self.interact(cats[0], "cat")
                continue
            chests = self.loot_points(frame, "chest")
            if chests and self.chests_opened < 3:
                frame = self.interact(chests[0], "chest")
                continue
            if (self.chests_opened >= 3 and (self.cat_collected or special_cat_room)
                    and (not special_cat_room or self.baruoki_left_checked)):
                points = self.events(frame)
                if points:
                    frame = self.interact(points[0], "exit")
                    continue
            if moves >= 18:
                self.record("survey-limit", frame)
                raise RuntimeError("幻璃境：搜索 18 次后仍未确认箱子、猫或出口，保留现场")
            objects = black_objects if self.chests_opened >= 3 else []
            if not objects and not self.cat_collected:
                objects = distinct_points(self.reco("PhantomCat", frame))
            if not objects and self.chests_opened < 3:
                objects = distinct_points(self.reco("PhantomChest", frame))
            objects.sort(key=lambda p: abs(p[0] - 640))
            direction = (1 if objects[0][0] > 640 else -1) if objects else search_direction
            self.record("search", frame, direction=direction, chests=self.chests_opened, cat=self.cat_collected)
            self.action("PhantomMove", {"PhantomMove": {"end": [640 + 190 * direction, 520],
                                                       "duration": 200 if objects else 400}})
            previous = frame
            frame = self.wait_room()
            stationary = stationary + 1 if stationary_scene(previous, frame) else 0
            if stationary >= 2:
                if direction == -1 and special_cat_room:
                    self.baruoki_left_checked = True
                boundaries += 1
                if boundaries >= 2:
                    self.record("unrecognized-reward", frame)
                    raise RuntimeError("幻璃境：两侧边界均已检查，仍缺少奖励或出口识别")
                search_direction = -direction
                stationary = 0
            moves += 1
        raise RuntimeError("幻璃境：超过 120 次事件和移动上限")

    def run_dungeon(self, frame):
        """此岸之境出生在左侧，奖励从左到右，最后由右侧离开。"""
        for _ in range(24):
            if self.reco("StartUpWorldReady", frame):
                return
            points = self.events(frame)
            if points:
                frame = self.interact(points[0], "chest" if self.chests_opened < 3 else "leave")
                continue
            self.record("dungeon-right", frame, chests=self.chests_opened)
            self.action("PhantomMove", {"PhantomMove": {"end": [830, 520], "duration": 300}})
            frame = self.wait_room(allow_world=True)
        self.record("dungeon-exit-unknown", frame)
        raise RuntimeError("此岸之境：没有确认右侧出口")

    def loot_points(self, frame, kind):
        objects = distinct_points(self.reco("PhantomChest" if kind == "chest" else "PhantomCat", frame))
        events = self.events(frame)
        points = [p for p in events if any(abs(p[0] - q[0]) <= 45 and 60 <= q[1] - p[1] <= 210
                                           for q in objects)]
        # 不能只凭高度推断宝箱：巴尔沃基的气球出口与箱子几乎同高，
        # 中间箱又比两侧更小、更高。遮挡时移动重新观察箱体，不猜事件类型。
        return points

    def interact(self, point, kind):
        before = self.room
        self.record("click-" + kind, self.frame(), point=point)
        self.click(point)
        deadline = min(self.deadline, time.monotonic() + 35)
        reward = False
        while time.monotonic() < deadline:
            frame = self.frame()
            self.observe_room(frame)
            if kind == "leave" and self.reco("StartUpWorldReady", frame):
                return frame
            if kind == "leave" and self.reco("PhantomCongratulations", frame):
                self.record("exit-reward", frame)
                self.action("PhantomCongratulations")
                continue
            if self.room != before:
                if kind in ("chest", "cat"):
                    self.record("unexpected-transition", frame, kind=kind, previous=before)
                    raise RuntimeError("领取事件发生了意外换层，停止以检查事件分类")
                return self.wait_room()
            if self.reco("PhantomReward", frame):
                self.record("reward", frame, kind=kind)
                self.action("PhantomReward")
                reward = True
                continue
            if self.reco("PhantomStamp", frame):
                self.record("stamp", frame)
                self.action("PhantomStamp")
                reward = True
                continue
            if reward and self.reco("PhantomWorld", frame):
                if kind == "chest":
                    self.chests_opened += 1
                elif kind == "cat":
                    self.cat_collected = True
                return self.wait_room()
            time.sleep(.12)
        self.record("interaction-timeout", self.frame(), kind=kind)
        raise RuntimeError(f"幻璃境：{kind} 事件后没有确认奖励或换层")


class PhantomRealm(CustomAction):
    def run(self, context, argv):
        try:
            PhantomRunner(context).run()
            return True
        except PhantomJackpot:
            LOG.warning("你撞大运了，已停止任务，等待玩家接管")
            return False
        except Exception:
            LOG.exception("PhantomRealm 失败")
            return False


def register(resource):
    return resource.register_custom_action("PhantomRealm", PhantomRealm())
