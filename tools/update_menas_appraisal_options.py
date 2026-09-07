"""从实测词条目录更新谜晶鉴定 GUI 选项，保留其他任务与稳定选项标识。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "MenasAppraisal"


def override(**params):
    return {PREFIX: {"custom_action_param": params}}


def input_option(label, fields, description=""):
    inputs = [{"name": name, "label": title, "default": default, "pipeline_type": "int",
               "verify": pattern, "pattern_msg": message}
              for name, title, default, pattern, message in fields]
    return {"type": "input", "label": label, "description": description, "inputs": inputs,
            "pipeline_override": override(**{f["name"]: "{" + f["name"] + "}" for f in inputs})}


def combination(label, field, all_label, any_label, default="all"):
    return {"type": "select", "label": label, "default_case": default,
            "cases": [{"name": name, "label": title, "pipeline_override": override(**{field: name})}
                      for name, title in (("all", all_label), ("any", any_label))]}


def generate(catalog):
    options = {}
    options[PREFIX + "Batches"] = input_option("鉴定批数", [
        ("batches", "批数（每批25个；0＝全部完整批次）", "1", r"^(0|[1-9][0-9]{0,2})$", "请输入0～999")
    ], "只处理每批25个。剩余不足25个时停止，保留余数。")
    rule_options = ["Weapons", "Stats", "StatMode", "AffixMode", "ConditionMode", "Affixes", "ExtraAffixes"]
    options[PREFIX + "AutoLock"] = {
        "type": "switch", "label": "自动锁定符合条件的武器", "default_case": "Yes",
        "description": "默认使用毒痛增伤组合规则，也可切换自定义；关闭时仅鉴定并保存统计。已有锁定会保留。",
        "cases": [
            {"name": "Yes", "label": "按条件锁定", "pipeline_override": override(auto_lock=True),
             "option": [PREFIX + "RuleMode"]},
            {"name": "No", "label": "仅鉴定并记录", "pipeline_override": override(auto_lock=False)},
        ],
    }
    options[PREFIX + "RuleMode"] = {
        "type": "select", "label": "锁定规则", "default_case": "poison_pain",
        "description": "默认：杖的魔力／其他武器攻击大于210，且同时具有毒痛增伤，"
                       "或具有毒痛之一并具有满血伤害、暴击威力、全属性攻击力中的至少两种。",
        "cases": [
            {"name": "poison_pain", "label": "毒痛增伤组合（默认）",
             "pipeline_override": override(rule_mode="poison_pain"),
             "option": [PREFIX + "PrimaryStat", PREFIX + "Weapons"]},
            {"name": "custom", "label": "自定义白值与词条",
             "pipeline_override": override(rule_mode="custom"),
             "option": [PREFIX + name for name in rule_options]},
        ],
    }
    options[PREFIX + "PrimaryStat"] = input_option("默认组合的白值要求", [
        ("primary_above", "杖魔力／其他武器攻击须大于", "210", r"^(0|[1-9][0-9]{0,3})$", "请输入0～9999")
    ], "严格大于：默认210不合格，211开始合格。词条必须为双毒痛，或单毒／痛加三种增伤中的至少两种。")
    weapons = {"staff": "杖", "sword": "剑", "katana": "刀", "axe": "斧",
               "lance": "枪", "bow": "弓", "fists": "拳", "hammer": "锤"}
    options[PREFIX + "Weapons"] = {
        "type": "checkbox", "label": "适用武器", "description": "不勾选表示全部武器。选择后仅锁定这些类型。",
        "default_case": [], "cases": [
            {"name": key, "label": value, "pipeline_override": override(weapons={key: True})}
            for key, value in weapons.items()],
    }
    options[PREFIX + "Stats"] = input_option("白值下限（包含等于）", [
        ("attack_min", "攻击下限（0＝不限制）", "0", r"^(0|[1-9][0-9]{0,3})$", "请输入0～9999"),
        ("magic_min", "魔力下限（0＝不限制）", "0", r"^(0|[1-9][0-9]{0,3})$", "请输入0～9999"),
    ], "比较结果页中的实际攻击、魔力数值，0表示该项不参与判断。")
    options[PREFIX + "StatMode"] = combination("攻击与魔力如何组合", "stat_mode",
        "设置的下限全部达标", "设置的下限任意一项达标", "any")
    options[PREFIX + "AffixMode"] = combination("所选词条如何组合", "affix_mode",
        "必须同时具有全部所选词条", "具有任意一个所选词条即可")
    options[PREFIX + "ConditionMode"] = combination("白值与词条如何组合", "condition_mode",
        "白值条件和词条条件同时满足", "满足白值条件或词条条件即可")
    options[PREFIX + "ConditionMode"]["description"] = "未设置的一组不参与判断；武器类型始终需要符合。"
    options[PREFIX + "Affixes"] = {
        "type": "checkbox", "label": "目标词条（可多选）", "default_case": [],
        "description": f"实测{catalog['batches']}批、{catalog['weapons_observed']}把，共{len(catalog['affixes'])}种。"
                       "使用放大镜详情的完整名称；样本不代表完整词条池。不勾选时不限制词条。",
        "cases": [{"name": affix["id"], "label": affix["name"],
                   "pipeline_override": override(affixes={affix["id"]: True})} for affix in catalog["affixes"]],
    }
    options[PREFIX + "ExtraAffixes"] = {
        "type": "input", "label": "其他目标词条（选填）",
        "description": "填游戏放大镜详情中的完整词条名，多个词条用分号分隔；与上面的勾选共同参与词条判断。",
        "inputs": [{"name": "extra_affixes", "label": "完整词条名；完整词条名", "default": "",
                    "verify": r"^[\s\S]{0,1000}$", "pattern_msg": "最多1000个字符"}],
        "pipeline_override": override(extra_affixes="{extra_affixes}"),
    }
    return options


def main():
    path = ROOT / "assets/interface.json"
    interface = json.loads(path.read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "agent/data/menas_affixes.json").read_text(encoding="utf-8"))
    task = {"name": PREFIX, "label": "梅纳斯谜晶鉴定", "entry": PREFIX,
            "description": "从主界面、梅纳斯试炼或鉴定道具页开始，每批鉴定25个谜晶，逐把读取攻击、魔力及完整词条，"
                           "默认锁定杖魔力／其他武器攻击大于210，且双毒痛，或毒痛之一加满血伤害、暴击威力、"
                           "全属性攻击力中至少两种的装备。可切换自定义规则或关闭自动锁定以收集样本。"
                           "不出售装备、不解除已有锁定；完成后停在鉴定道具页，剩余不足25个时停止。",
            "option": [PREFIX + "Batches", PREFIX + "AutoLock"]}
    existing = next((i for i, t in enumerate(interface["task"]) if t["name"] == PREFIX), None)
    if existing is None:
        position = next(i for i, t in enumerate(interface["task"]) if t["name"] == "MenasTrial") + 1
        interface["task"].insert(position, task)
    else:
        interface["task"][existing] = task
    interface["option"].update(generate(catalog))
    path.write_text(json.dumps(interface, ensure_ascii=False, indent=4) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
