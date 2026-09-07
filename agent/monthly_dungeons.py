"""从本期试炼卡片读取副本名称，复用副本目录和单次跳过流程。"""

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from maa.custom_action import CustomAction

from dungeons import DungeonNavigator, DungeonSkipUnavailable, parse_request
from monthly_trial import MonthlyNavigator, parse_period


LOG = logging.getLogger(__name__)
EXPECTED_CARDS = 3
MAX_SCROLLS = 64


def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text).translate(str.maketrans({
        "「": '"', "」": '"', "『": '"', "』": '"', "“": '"', "”": '"',
        "・": "·", "‧": "·", "．": "·",
    }))


@dataclass(frozen=True)
class DungeonTrial:
    title: str
    kind: str
    name: str
    difficulty: str
    completed: bool

    @property
    def key(self):
        return self.title, self.kind, self.name, self.difficulty


def text_lines(rows):
    """OCR 可能把名称或标题拆成横向相邻片段，先按文字行合并。"""
    lines = []
    for row in sorted(rows, key=lambda r: (r.box[1], r.box[0])):
        if row.score < 0.85:
            continue
        x, y, w, h = row.box
        group = next((line for line in lines
                      if abs(line[0].box[1] + line[0].box[3] / 2 - (y + h / 2)) <= 10), None)
        if group is None:
            lines.append([row])
        else:
            group.append(row)
    return [("".join(normalize(r.text) for r in sorted(line, key=lambda r: r.box[0])),
             min(r.box[1] for r in line)) for line in lines]


def parse_cards(rows):
    """标题、目标和按钮必须位于同一卡片；裁切的卡片交给重叠滚动补全。"""
    lines = text_lines([r for r in rows if 450 <= r.box[0] < 980])
    buttons = text_lines([r for r in rows if r.box[0] >= 980])
    titles = [(text, y) for text, y in lines
              if re.fullmatch(r"(?:星天[·.]?)?(?:开拓|踏破)的考验", text)]
    cards = []
    for title, y in titles:
        descriptions = [text for text, body_y in lines if 25 <= body_y - y <= 80]
        states = [text for text, button_y in buttons if 85 <= button_y - y <= 145
                  and text in ("未达成", "领取奖励", "已领取奖励")]
        if len(descriptions) != 1 or len(states) != 1:
            continue
        match = re.fullmatch(r'通关(平行迷宫|异境)"([^"\n]+)"(?:\((非常困难|困难)\))?', descriptions[0])
        if not match:
            continue
        card = DungeonTrial(title.replace("·", "").replace(".", ""), match[1], match[2],
                            match[3] or "", states[0] != "未达成")
        if any(old.key == card.key for old in cards):
            raise ValueError(f"同屏副本任务不唯一：{card.name}")
        cards.append(card)
    return cards


def match_dungeon(card, catalog):
    """只匹配完整名称和副本类型；同路径不同难度优先低票数、困难。"""
    matches = []
    for target in catalog["dungeons"]:
        path = target["path"]
        otherlands = path[0] == "异境"
        if otherlands != (card.kind == "异境"):
            continue
        names = [target["name"], target.get("confirmation_name", ""), path[-1]]
        if otherlands:
            names.append(path[1])
        if card.name not in {normalize(name) for name in names}:
            continue
        if card.difficulty and card.difficulty != target["difficulty"]:
            continue
        matches.append(target)
    if not matches:
        return None, "副本目录没有完整名称匹配"
    available = [v for v in matches if v.get("can_enter") and v.get("can_skip")]
    if not available:
        return None, "目录中没有可进入且可跳过的入口"
    # 异境地区目标允许其下任一已验证可跳过楼层；普通同名多路径不能猜测入口。
    if card.kind != "异境" and len({tuple(v["path"]) for v in available}) != 1:
        return None, "同名副本有多个入口路径，无法唯一匹配"
    target = min(available, key=lambda v: (v["ticket_cost"], v["difficulty"] != "困难", v["id"]))
    return parse_request({"target": target["id"], "count": 1}, catalog)[0], ""


def same_rows(left, right):
    """比较文字及位置，避免相似卡片重复文字导致误判到达列表边界。"""
    a = sorted((normalize(r.text), tuple(r.box)) for r in left)
    b = sorted((normalize(r.text), tuple(r.box)) for r in right)
    return bool(a) and len(a) == len(b) and all(
        text_a == text_b and all(abs(x - y) <= 5 for x, y in zip(box_a, box_b))
        for (text_a, box_a), (text_b, box_b) in zip(a, b))


def verify_snapshot(before, after, old_period, period, completed_key=None):
    if old_period != period:
        raise RuntimeError("试炼月份发生变化，请重新运行")
    old, new = {c.key: c for c in before}, {c.key: c for c in after}
    if old.keys() != new.keys():
        raise RuntimeError("试炼副本目标发生变化，停止核查")
    if any(card.completed and not new[key].completed for key, card in old.items()):
        raise RuntimeError("试炼完成状态倒退，停止核查")
    if completed_key is not None and not new[completed_key].completed:
        raise RuntimeError(f"跳过后任务仍未达成：{new[completed_key].name}；不重复消耗票券")


class TrialDungeonNavigator(MonthlyNavigator):
    def page_rows(self, period):
        frame = self.frame()
        if not self.reco("MonthlyTrialsReady", frame):
            raise RuntimeError("读取副本目标时试炼页不可见")
        if parse_period(self.rows("MonthlyReadPeriod", frame)) != period:
            raise RuntimeError("试炼月份发生变化，请重新运行")
        rows = self.rows("MonthlyReadRows", frame)
        if not rows:
            raise RuntimeError("试炼列表 OCR 为空")
        return rows

    def scroll(self, node, period, previous):
        self.action(node)
        current = self.page_rows(period)
        return current, same_rows(previous, current)

    def read_dungeons(self):
        self.open_trials()
        period = parse_period(self.rows("MonthlyReadPeriod", self.frame()))
        rows = self.page_rows(period)
        # 已完成的卡片会排到后面；每次从顶部重新扫描，也支持任意滚动位置启动。
        unchanged = 0
        for _ in range(MAX_SCROLLS):
            rows, stable = self.scroll("MonthlyDungeonScrollUp", period, rows)
            unchanged = unchanged + 1 if stable else 0
            if unchanged == 2:
                break
        else:
            raise RuntimeError("试炼列表超过滚动上限，无法确认顶部")

        found = {}
        unchanged = 0
        for _ in range(MAX_SCROLLS):
            cards = parse_cards(rows)
            if cards:
                time.sleep(0.3)
                second = parse_cards(self.page_rows(period))
                if cards != second:
                    raise RuntimeError("连续两次识别的副本任务或完成状态不一致")
                for card in cards:
                    if card.key in found and found[card.key] != card:
                        raise RuntimeError(f"扫描期间任务状态变化：{card.name}")
                    found[card.key] = card
            if len(found) == EXPECTED_CARDS:
                result = sorted(found.values(), key=lambda c: c.key)
                LOG.warning("MonthlyTrialDungeons 截止 %s，目标 %s", period, result)
                return result, period
            if len(found) > EXPECTED_CARDS:
                raise RuntimeError("副本卡片数量超出预期，停止核查")
            rows, stable = self.scroll("MonthlyDungeonScrollDown", period, rows)
            unchanged = unchanged + 1 if stable else 0
            if unchanged == 2:
                break
        raise RuntimeError(f"未读全本期三个副本任务，只确认 {len(found)} 个；不消耗票券")

    def run_dungeons(self, catalog):
        cards, period = self.read_dungeons()
        ignored = set()
        while True:
            self.check()
            selected = None
            for card in cards:
                if card.completed or card.key in ignored:
                    continue
                target, reason = match_dungeon(card, catalog)
                if target is None:
                    ignored.add(card.key)
                    LOG.warning("MonthlyTrialDungeons 略过 %s：%s", card.name, reason)
                    continue
                selected = card, target
                break
            if selected is None:
                LOG.warning("MonthlyTrialDungeons 完成：已达成 %s 项，略过 %s 项，保留试炼页",
                            sum(c.completed for c in cards), len(ignored))
                return True
            card, target = selected
            LOG.warning("MonthlyTrialDungeons %s → %s / %s，跳过一次",
                        card.name, target["id"], target["difficulty"])
            self.close_progress()
            self.pipeline("DungeonEntrance")
            self.wait("DungeonMenuReady")
            dungeon = DungeonNavigator(self.context)
            dungeon.deadline = self.deadline
            completed_key = card.key
            try:
                if dungeon.skip(target, 1) != 1:
                    raise RuntimeError("副本跳过未确认单次结算")
            except DungeonSkipUnavailable:
                # 仅吞掉已核对目标页但按钮未启用这一种结果；其他识别、资源错误照常失败。
                ignored.add(card.key)
                completed_key = None
                LOG.warning("MonthlyTrialDungeons 略过 %s：当前跳过按钮未启用", card.name)
                self.pipeline("DungeonEntrance")
                self.wait("DungeonMenuReady")
                self.action("MonthlyDungeonCloseMenu")
                self.world()
            current, new_period = self.read_dungeons()
            verify_snapshot(cards, current, period, new_period, completed_key)
            cards = current


class MonthlyTrialDungeons(CustomAction):
    def run(self, context, argv):
        try:
            params = json.loads(argv.custom_action_param)
            if not isinstance(params, dict):
                raise ValueError("月度副本参数必须是对象")
            minutes = params.get("max_minutes", 30)
            if type(minutes) is not int or not 10 <= minutes <= 120:
                raise ValueError("运行上限必须为 10～120 分钟的整数")
            catalog = json.loads((Path(__file__).parent / "data/dungeons.json").read_text(encoding="utf-8"))
            return TrialDungeonNavigator(context, minutes).run_dungeons(catalog)
        except (ValueError, TypeError, RuntimeError) as exc:
            LOG.error("MonthlyTrialDungeons 失败：%s", exc)
            return False
        except Exception:
            LOG.exception("MonthlyTrialDungeons 未预期异常")
            return False


def register(resource):
    return resource.register_custom_action("MonthlyTrialDungeons", MonthlyTrialDungeons())
