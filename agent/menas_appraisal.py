"""谜晶批量鉴定：严格读取白值与完整词条，仅锁定命中玩家规则的武器。"""

import json
import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from maa.custom_action import CustomAction

from navigation import Navigator


LOG = logging.getLogger(__name__)
PREFIX = "MenasAppraisal"
CATALOG_PATH = Path(__file__).with_name("data") / "menas_affixes.json"
WEAPONS = {"staff": "杖", "sword": "剑", "katana": "刀", "axe": "斧",
           "lance": "枪", "bow": "弓", "fists": "拳", "hammer": "锤"}


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def integer(value, name, maximum):
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name}必须为 0～{maximum} 的整数")
    return value


@dataclass(frozen=True)
class Rules:
    batches: int
    auto_lock: bool
    attack_min: int
    magic_min: int
    stat_mode: str
    affix_mode: str
    condition_mode: str
    affixes: tuple[str, ...]
    weapons: tuple[str, ...]
    rule_mode: str = "custom"
    primary_above: int = 210


def parse_rules(params, catalog=None):
    if not isinstance(params, dict):
        raise ValueError("谜晶鉴定参数必须是对象")
    allowed = {"batches", "auto_lock", "attack_min", "magic_min", "stat_mode", "affix_mode",
               "condition_mode", "affixes", "weapons", "extra_affixes", "rule_mode", "primary_above"}
    if set(params) - allowed:
        raise ValueError(f"未知鉴定参数：{sorted(set(params) - allowed)}")
    catalog = catalog or load_catalog()
    names = {a["id"]: normalize(a["name"]) for a in catalog["affixes"]}
    selected = []
    for field, choices in (("affixes", names), ("weapons", WEAPONS)):
        values = params.get(field, {})
        if (not isinstance(values, dict) or set(values) - set(choices)
                or any(type(v) is not bool for v in values.values())):
            raise ValueError(f"{field} 必须使用目录中的键和布尔值")
        selected.append(tuple(choices[k] for k, enabled in values.items() if enabled))
    extra = params.get("extra_affixes", "")
    if not isinstance(extra, str) or len(extra) > 1000:
        raise ValueError("自定义词条必须是长度不超过 1000 的文本")
    affixes = tuple(dict.fromkeys((*selected[0], *(normalize(v) for v in re.split(r"[;；\n]", extra)
                                                  if normalize(v)))))
    modes = [params.get(name, default) for name, default in
             (("stat_mode", "any"), ("affix_mode", "all"), ("condition_mode", "all"))]
    if any(mode not in ("all", "any") for mode in modes):
        raise ValueError("条件组合仅支持 all / any")
    auto_lock = params.get("auto_lock", True)
    if type(auto_lock) is not bool:
        raise ValueError("auto_lock 必须是布尔值")
    # 未指定模式的旧参数仍按原来的自定义规则解析；GUI/Pipeline 显式设置默认预设。
    rule_mode = params.get("rule_mode", "custom")
    if rule_mode not in ("custom", "poison_pain"):
        raise ValueError("rule_mode 必须为 custom / poison_pain")
    rules = Rules(integer(params.get("batches", 1), "鉴定批数", 999), auto_lock,
                  integer(params.get("attack_min", 0), "攻击下限", 9999),
                  integer(params.get("magic_min", 0), "魔力下限", 9999),
                  *modes, affixes, selected[1], rule_mode,
                  integer(params.get("primary_above", 210), "白值严格下限", 9999))
    if rules.auto_lock and rules.rule_mode == "custom" and not (rules.attack_min or rules.magic_min or rules.affixes):
        raise ValueError("请先设置攻击、魔力下限或目标词条；也可关闭自动锁定，仅鉴定并记录")
    return rules


@dataclass(frozen=True)
class Weapon:
    kind: str
    attack: int
    magic: int
    affixes: tuple[str, ...]


def matches(weapon, rules):
    if not rules.auto_lock or (rules.weapons and weapon.kind not in rules.weapons):
        return False
    if rules.rule_mode == "poison_pain":
        primary = weapon.magic if weapon.kind == "杖" else weapon.attack
        if primary <= rules.primary_above:
            return False
        affixes = set(weapon.affixes)
        ailments = len(affixes & {"中毒时强化+30%", "疼痛时强化+30%"})
        bonuses = len(affixes & {"HP最大时伤害+25%", "暴击威力+40%", "全属性攻击力+25%"})
        return ailments == 2 or (ailments >= 1 and bonuses >= 2)
    groups, stats = [], []
    if rules.attack_min:
        stats.append(weapon.attack >= rules.attack_min)
    if rules.magic_min:
        stats.append(weapon.magic >= rules.magic_min)
    if stats:
        groups.append((all if rules.stat_mode == "all" else any)(stats))
    if rules.affixes:
        hits = [value in weapon.affixes for value in rules.affixes]
        groups.append((all if rules.affix_mode == "all" else any)(hits))
    # 空条件不参与 OR，也不能通过 all([]) 意外锁定所有装备。
    return bool(groups) and (all if rules.condition_mode == "all" else any)(groups)


def row_text(rows, label, pattern, confidence=.95):
    ordered = sorted(rows, key=lambda row: row.box[0])
    text = "".join(normalize(row.text) for row in ordered)
    if not ordered or any(row.score < confidence for row in ordered) or not re.fullmatch(pattern, text):
        raise RuntimeError(f"无法可靠读取{label}：{text}")
    return text


def parse_main(rows):
    def band(left, top, bottom):
        return [row for row in rows if row.box[0] >= left and top <= row.box[1] + row.box[3] / 2 < bottom]
    name = row_text(band(60, 60, 105), "武器名", r"谜晶之[杖剑刀斧枪弓拳锤]")
    attack = int(row_text(band(405, 154, 196), "攻击", r"[1-9][0-9]{0,3}"))
    magic = int(row_text(band(405, 196, 238), "魔力", r"[1-9][0-9]{0,3}"))
    return name[-1], attack, magic


def parse_affixes(rows):
    """详情固定四行；按纵坐标重组被 OCR 横向拆开的同一词条。"""
    groups = [[] for _ in range(4)]
    for row in rows:
        text = normalize(row.text)
        if row.box[0] >= 925 or text in ("-", "—"):
            continue
        if not text:
            raise RuntimeError("检测到未读出的词条文字")
        center = row.box[1] + row.box[3] / 2
        index = round((center - 331) / 33)
        if not 0 <= index < 4 or abs(center - (331 + index * 33)) > 13:
            raise RuntimeError(f"词条位置不符：{text}")
        groups[index].append(row)
    count = sum(bool(group) for group in groups)
    if not count or any(not group for group in groups[:count]):
        raise RuntimeError("词条读取为空或存在缺行")
    return tuple(row_text(group, "词条", r".+", .93) for group in groups[:count])


def parse_stock(rows):
    return int(row_text(rows, "谜晶持有数", r"持有数[0-9]{1,6}")[3:])


def parse_quantity(rows):
    return int(row_text(rows, "本次鉴定数量", r"[xX×][0-9]{1,2}", .85)[1:])


class AppraisalRunner(Navigator):
    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("用户停止任务")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("谜晶鉴定超过运行时间上限")

    def rows(self, node, frame):
        self.check()
        result = self.reco(PREFIX + node, frame)
        return result.all_results if result else []

    def ready(self, node, seconds=10):
        return self.wait(PREFIX + node, seconds)

    def act(self, node, target=None):
        name = PREFIX + node
        self.action(name, {name: {"target": target}} if target else None)

    def ensure(self, node, frame=None):
        self.check()
        if not self.reco(PREFIX + node, self.frame() if frame is None else frame):
            raise RuntimeError(f"当前画面不是 {node}，停止操作")

    def open(self):
        frame = self.frame()
        if self.reco(PREFIX + "Home", frame):
            return
        if self.reco(PREFIX + "Results", frame):
            raise RuntimeError("当前仍在上一批结果页，请先手动完成该批或点继续鉴定，再运行任务")
        if not self.reco("MenasTrialStagesReady", frame):
            for node in ("MenasTrialOpenActivities", "MenasTrialOpenTrial"):
                if not self.context.clear_hit_count(node):
                    raise RuntimeError(f"无法重置导航节点：{node}")
            result = self.context.run_task("MenasTrialOpen")
            if (not result or not result.status.succeeded or not result.nodes
                    or result.nodes[-1].name != "MenasTrialStagesReady"):
                raise RuntimeError("未能进入梅纳斯试炼选关页")
        self.check()
        if not self.reco("MenasTrialStagesReady", self.frame()):
            raise RuntimeError("梅纳斯试炼选关页不可见")
        self.act("Enter")
        self.ready("Home")

    def stock(self):
        values = []
        for _ in range(2):
            frame = self.ready("Home")
            values.append(parse_stock(self.rows("ReadStock", frame)))
        if values[0] != values[1]:
            raise RuntimeError("连续两次读取的谜晶持有量不一致")
        return values[0]

    def submit(self):
        self.ensure("Home")
        self.act("Auto")
        frame = self.ready("Confirm")
        if parse_quantity(self.rows("ReadQuantity", frame)) != 25:
            raise RuntimeError("本次自动鉴定不是 25 个，保留确认页并停止")
        self.ensure("Confirm")
        # 每批只提交一次；若网络或动画超时，停止并保留现场。
        self.report["unconfirmed_consumption"] = True
        self.save()
        self.act("Submit")
        self.ready("Results", 45)

    def main(self):
        frame = self.ready("Results")
        return parse_main(self.rows("ReadMain", frame))

    def lock_state(self, frame=None):
        frame = self.frame() if frame is None else frame
        self.ensure("Results", frame)
        locked = bool(self.reco(PREFIX + "Locked", frame))
        unlocked = bool(self.reco(PREFIX + "Unlocked", frame))
        if locked == unlocked:
            raise RuntimeError("锁图标不明确，停止以避免误解锁")
        return locked

    def read_weapon(self, index):
        if not 0 <= index < 25:
            raise ValueError("武器序号越界")
        self.ensure("Results")
        self.act("Select", [652 + index % 5 * 128, 128 + index // 5 * 128])
        first = self.main()
        if self.main() != first:
            raise RuntimeError(f"第 {index + 1} 把白值尚未稳定")
        self.act("Inspect")
        first_affixes = parse_affixes(self.rows("ReadAffixes", self.ready("Detail")))
        second_affixes = parse_affixes(self.rows("ReadAffixes", self.ready("Detail")))
        if first_affixes != second_affixes:
            raise RuntimeError(f"第 {index + 1} 把词条尚未稳定")
        self.act("CloseDetail")
        if self.main() != first:
            raise RuntimeError(f"第 {index + 1} 把武器在读取词条后发生变化")
        return Weapon(*first, first_affixes), self.lock_state()

    def lock(self, weapon):
        if self.main() != (weapon.kind, weapon.attack, weapon.magic):
            raise RuntimeError("锁定前武器白值变化")
        if self.lock_state():
            return  # 幂等：永远不切换已有的锁定状态。
        self.act("Lock")
        self.ready("LockNotice")
        self.act("AcknowledgeLock")
        self.ready("Results")
        if not self.lock_state():
            raise RuntimeError("锁定后图标未确认，不重复点击")

    def save(self):
        self.report_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def scan_batch(self, rules, batch):
        for index in range(25):
            self.check()
            weapon, was_locked = self.read_weapon(index)
            matched = matches(weapon, rules)
            record = {"batch": batch, "index": index + 1, **asdict(weapon),
                      "matched": matched, "locked_before": was_locked, "locked_after": was_locked,
                      "status": "read"}
            self.report["weapons"].append(record)
            self.save()
            if matched and not was_locked:
                self.lock(weapon)
                record["locked_after"] = True
            record["status"] = "done"
            self.save()
            LOG.warning("MenasAppraisal 第 %s 批 %s/25：%s 攻击%s 魔力%s；%s；%s",
                        batch, index + 1, weapon.kind, weapon.attack, weapon.magic,
                        "、".join(weapon.affixes), "已锁定" if record["locked_after"] else "未锁定")

    def run(self, rules):
        self.deadline = time.monotonic() + 180
        directory = Path("debug/menas-appraisal")
        directory.mkdir(parents=True, exist_ok=True)
        self.report_path = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
        self.report = {"rules": asdict(rules), "status": "running", "consumed": 0,
                       "unconfirmed_consumption": False,
                       "completed_batches": 0, "weapons": []}
        self.save()
        try:
            self.open()
            initial = self.stock()
            planned = initial // 25 if rules.batches == 0 else min(rules.batches, initial // 25)
            self.deadline = time.monotonic() + max(180, planned * 600)
            self.report.update(initial_stock=initial, planned_batches=planned)
            self.save()
            LOG.warning("MenasAppraisal 持有 %s 个，计划 %s 批；报告 %s", initial, planned, self.report_path)
            for batch in range(1, planned + 1):
                self.check()
                if self.stock() != initial - (batch - 1) * 25:
                    raise RuntimeError("鉴定前谜晶数量变化不符，停止核查")
                self.submit()
                self.report["consumed"] += 25
                self.report["unconfirmed_consumption"] = False
                self.save()
                self.scan_batch(rules, batch)
                self.ensure("Results")
                self.act("Continue")
                self.ready("Home")
                if self.stock() != initial - batch * 25:
                    raise RuntimeError("鉴定后谜晶数量变化不符，停止核查")
                self.report["completed_batches"] = batch
                self.save()
            if rules.batches and planned != rules.batches:
                raise RuntimeError(f"谜晶不足 25 个一批，实际完成 {planned}/{rules.batches} 批")
            self.report["status"] = "succeeded"
            LOG.warning("MenasAppraisal 完成 %s 批，已锁定 %s 把，停留鉴定道具页", planned,
                        sum(w["locked_after"] and not w["locked_before"] for w in self.report["weapons"]))
            return True
        except Exception as exc:
            self.report.update(status="failed", error=str(exc))
            raise
        finally:
            self.save()


class MenasAppraisal(CustomAction):
    def run(self, context, argv):
        try:
            rules = parse_rules(json.loads(argv.custom_action_param))
            return AppraisalRunner(context).run(rules)
        except Exception:
            LOG.exception("MenasAppraisal 失败")
            return False


def register(resource):
    return resource.register_custom_action(PREFIX, MenasAppraisal())
