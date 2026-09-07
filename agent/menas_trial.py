"""读取梅纳斯入场券并按已确认的单场结算推进挑战次数。"""

import json
import logging
import re
import time

from maa.custom_action import CustomAction

from navigation import Navigator


LOG = logging.getLogger(__name__)
ROUND_NODES = (
    "MenasTrialOpenActivities", "MenasTrialOpenTrial", "MenasTrialSelectSS",
    "MenasTrialChallenge", "MenasTrialAttack", "MenasTrialRewards", "MenasTrialCongratulations",
)


def parse_count(params):
    if not isinstance(params, dict):
        raise ValueError("梅纳斯参数必须是对象")
    count = params.get("count", 0)
    if isinstance(count, str) and re.fullmatch(r"0|[1-9][0-9]{0,2}", count):
        count = int(count)
    if type(count) is not int or not 0 <= count <= 999:
        raise ValueError("挑战次数必须为 0～999 的整数，0 表示全部入场券")
    return count


def parse_tickets(rows):
    text = "".join(re.sub(r"\s+", "", row.text) for row in rows if row.score >= 0.85)
    match = re.fullmatch(r"入场券持有量[:：]([0-9]{1,3})/([0-9]{1,3})", text)
    if not match or int(match[2]) == 0:
        raise RuntimeError(f"无法确认梅纳斯入场券持有量：{text}")
    return int(match[1])


class MenasNavigator(Navigator):
    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("用户停止任务")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("梅纳斯试炼超过运行时间上限")

    def pipeline(self, entry, completion):
        self.check()
        result = self.context.run_task(entry)
        if (not result or not result.status.succeeded or not result.nodes
                or result.nodes[-1].name != completion):
            raise RuntimeError(f"梅纳斯流程未完成：{entry} → {completion}")

    def prepare(self):
        # 同一任务内的命中计数会累积；每场重置，保留原有单场保护上限。
        for node in ROUND_NODES:
            self.check()
            if not self.context.clear_hit_count(node):
                raise RuntimeError(f"无法重置单场节点计数：{node}")
        self.pipeline("MenasTrialOpen", "MenasTrialStagesReady")
        quantities = []
        for _ in range(2):
            frame = self.frame()
            if not self.reco("MenasTrialStagesReady", frame):
                raise RuntimeError("读取入场券时梅纳斯选关页不可见")
            result = self.reco("MenasTrialReadTickets", frame)
            quantities.append(parse_tickets(result.all_results if result else []))
        if quantities[0] != quantities[1]:
            raise RuntimeError("连续两次读取的梅纳斯入场券数量不一致")
        return quantities[0]

    def run_trials(self, count):
        self.deadline = time.monotonic() + 180
        tickets = self.prepare()
        planned = tickets if count == 0 else min(count, tickets)
        LOG.warning("MenasTrial 请求 %s，持有 %s 张入场券，计划挑战 %s 次",
                    "全部" if count == 0 else count, tickets, planned)
        if planned == 0:
            self.pipeline("MenasTrialClose", "MenasTrialComplete")
            LOG.warning("MenasTrial 入场券不足，未提交挑战")
            return 0
        self.deadline = time.monotonic() + planned * 900
        completed = 0
        while completed < planned:
            self.check()
            if completed:
                remaining = self.prepare()
                if remaining != tickets - completed:
                    raise RuntimeError(f"入场券变化不符，已完成 {completed} 次；"
                                       f"预期 {tickets - completed}，实际 {remaining}，停止核查")
            self.pipeline("MenasTrialRunOnce", "MenasTrialComplete")
            completed += 1
            LOG.warning("MenasTrial 已完成 %s/%s 次，确认返回主界面", completed, planned)
        if count > completed:
            LOG.warning("MenasTrial 入场券不足，已完成 %s/%s 次，不再提交挑战", completed, count)
        return completed


class MenasTrial(CustomAction):
    def run(self, context, argv):
        try:
            count = parse_count(json.loads(argv.custom_action_param))
            completed = MenasNavigator(context).run_trials(count)
            return count == 0 or completed == count
        except Exception:
            LOG.exception("MenasTrial 失败")
            return False


def register(resource):
    return resource.register_custom_action("MenasTrial", MenasTrial())
