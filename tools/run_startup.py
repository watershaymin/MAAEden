"""通过 MaaFramework 在指定 ADB 设备上运行任务，默认启动并登录。"""

import argparse
import sys
import time
from pathlib import Path

from maa.controller import AdbController
from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit


TASKS = {
    "MenasAppraisal": ("MenasAppraisalComplete", 780, "menas-appraisal-run", "谜晶鉴定筛选完成，停留鉴定道具页；详细结果见 debug/menas-appraisal。"),
    "CatDiary": ("CatDiaryComplete", 2760, "cat-diary-run", "本轮猫咪日记已全部完成，停留日记页。"),
    "MonthlyTrialDungeons": ("MonthlyTrialDungeonsComplete", 1860, "monthly-trial-dungeons-run", "本期可跳过的副本任务已处理，停留试炼页；略过原因见日志。"),
    "MonthlyStarTrial": ("MonthlyStarTrialComplete", 10860, "monthly-star-trial-run", "本月星天200胜试炼已完成，停留试炼页。"),
    "DungeonSkip": ("DungeonSkipComplete", 900, "dungeon-skip-run", "已完成指定次数跳过并返回蓝门。"),
    "DungeonEntrance": ("DungeonMenuReady", 180, "dungeon-entrance-run", "已到达平行迷宫选图界面。"),
    "StartUp": ("StartUpWorldReady", 300, "startup-run", "已进入游戏主界面。"),
    "MenasTrial": ("MenasTrialComplete", 900, "menas-trial-run", "梅纳斯试炼已结算并返回主界面。"),
    "CollectMail": ("MailComplete", 600, "mail-run", "邮件已领取完毕并返回主界面。"),
    "NavigationMove": ("NavigationMoveComplete", 240, "navigation-run", "已通过区域地图确认位移。"),
    "NavigationTeleport": ("NavigationTeleportComplete", 180, "navigation-run", "已确认传送到巴尔沃基。"),
    "NavigationBaruokiRoute": ("NavigationRouteComplete", 240, "navigation-run", "已到达巴尔沃基北侧路口。"),
}


def dungeon_params(args):
    split = {"red_target": args.red_dungeon, "red_count": args.red_count,
             "green_target": args.green_dungeon, "green_count": args.green_count}
    split_routes = {"red": getattr(args, "red_route", None), "green": getattr(args, "green_route", None)}
    legacy_route = getattr(args, "dungeon_route", None)
    if args.dungeon is not None or args.count is not None or legacy_route is not None:
        if any(value is not None for value in [*split.values(), *split_routes.values()]):
            raise ValueError("旧 --dungeon/--count 不能与红绿票独立参数混用")
        params = {"target": args.dungeon or "snake_damak_vh",
                  "count": args.count if args.count is not None else 1}
        if legacy_route is not None:
            params["routes"] = {params["target"]: legacy_route}
    else:
        params = {key: value for key, value in split.items() if value is not None}
        defaults = {"red": "snake_damak_vh", "green": "moon_forest_h"}
        routes = {params.get(ticket + "_target", defaults[ticket]): route
                  for ticket, route in split_routes.items() if route is not None}
        if routes:
            params["routes"] = routes
    params.update(refill_red=args.refill_red, refill_green=args.refill_green, refill_cat=args.refill_cat)
    return params


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb-path", required=True, type=Path)
    parser.add_argument("--address", required=True, help="例如 127.0.0.1:16384")
    parser.add_argument("--task", choices=list(TASKS), default="StartUp")
    parser.add_argument("--direction", choices=["left", "right", "up", "down"], default="left")
    parser.add_argument("--dungeon", help="兼容旧单副本模式，默认蛇肝达玛克非常困难")
    parser.add_argument("--count", type=int, help="梅纳斯默认 0（全部入场券）；副本旧单副本模式默认 1")
    parser.add_argument("--red-dungeon", help="红票副本 ID，默认 snake_damak_vh")
    parser.add_argument("--green-dungeon", help="绿票副本 ID，默认 moon_forest_h")
    parser.add_argument("--red-count", type=int, help="红票每次运行跳过场数，默认 4，0 为不执行")
    parser.add_argument("--green-count", type=int, help="绿票每次运行跳过场数，默认 4，0 为不执行")
    parser.add_argument("--red-route", help="红票副本扫荡路线 ID，见副本目录 skip_routes")
    parser.add_argument("--green-route", help="绿票副本扫荡路线 ID，见副本目录 skip_routes")
    parser.add_argument("--dungeon-route", help="旧单副本模式的扫荡路线 ID")
    parser.add_argument("--refill-red", action="store_true", help="红票不足时使用星天之证的导证之力补充")
    parser.add_argument("--refill-green", action="store_true", help="绿票不足时使用星天之证的导证之力补充")
    parser.add_argument("--refill-cat", action="store_true", help="猫掌券不足时使用星天之证的导证之力补充")
    parser.add_argument("--appraisal-config", type=Path, help="谜晶鉴定规则 JSON，字段与 Custom 参数一致")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    skip_params = None
    if args.task == "DungeonSkip":
        import json
        sys.path.insert(0, str(root / "agent"))
        from dungeons import parse_skip_plan
        try:
            skip_params = dungeon_params(args)
            catalog = json.loads((root / "agent/data/dungeons.json").read_text(encoding="utf-8"))
            skip_plan = parse_skip_plan(skip_params, catalog)
        except ValueError as exc:
            parser.error(str(exc))
    if args.count is None:
        args.count = 0 if args.task == "MenasTrial" else 1
    if args.task == "MenasTrial" and not 0 <= args.count <= 999:
        parser.error("梅纳斯 --count 必须为 0～999，0 表示全部入场券")
    if not args.adb_path.is_file():
        parser.error("--adb-path 必须指向 adb 可执行文件")

    appraisal_params = None
    if args.task == "MenasAppraisal":
        import json
        sys.path.insert(0, str(root / "agent"))
        from menas_appraisal import parse_rules
        if args.appraisal_config is None:
            parser.error("谜晶鉴定需要 --appraisal-config 指定筛选规则")
        try:
            appraisal_params = json.loads(args.appraisal_config.read_text(encoding="utf-8"))
            # 旧 CLI 规则显式使用自定义模式，避免继承 Pipeline 新增的默认组合。
            if isinstance(appraisal_params, dict):
                appraisal_params.setdefault("rule_mode", "custom")
            appraisal_rules = parse_rules(appraisal_params)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    completion_node, time_limit, log_dir, success_message = TASKS[args.task]
    Toolkit.init_option(root / "debug" / log_dir)
    capture = MaaAdbScreencapMethodEnum.Encode
    input_method = MaaAdbInputMethodEnum.AdbShell
    config = {}
    if args.task in ("CatDiary", "MenasAppraisal"):
        # 移动目标和逐把鉴定需要及时截图。只复用明确匹配用户所选地址的模拟器配置。
        devices = [device for device in Toolkit.find_adb_devices() if device.address == args.address
                   and device.adb_path.resolve() == args.adb_path.resolve()]
        capture = MaaAdbScreencapMethodEnum.Encode | MaaAdbScreencapMethodEnum.RawWithGzip
        input_method = MaaAdbInputMethodEnum.Default
        if len(devices) == 1:
            capture = devices[0].screencap_methods
            input_method = devices[0].input_methods
            config = devices[0].config
    controller = AdbController(
        args.adb_path,
        args.address,
        screencap_methods=capture,
        input_methods=input_method,
        config=config,
    )
    if not controller.post_connection().wait().succeeded:
        print("ADB 连接失败，请检查模拟器地址。", file=sys.stderr)
        return 1
    controller.set_screenshot_target_short_side(720)
    frame = controller.post_screencap().wait().get()
    if frame is None or frame.shape[:2] != (720, 1280):
        print("当前仅支持 16:9 横屏设备（缩放后 1280×720）。", file=sys.stderr)
        return 1

    resource = Resource()
    if args.task == "MenasAppraisal":
        from menas_appraisal import register
        if not register(resource):
            print("谜晶鉴定动作注册失败。", file=sys.stderr)
            return 1
        time_limit = 180 + (appraisal_rules.batches or 999) * 600
    if args.task == "MenasTrial":
        sys.path.insert(0, str(root / "agent"))
        from menas_trial import register
        if not register(resource):
            print("梅纳斯动作注册失败。", file=sys.stderr)
            return 1
        time_limit = 180 + (args.count or 999) * 900
    if args.task == "CatDiary":
        sys.path.insert(0, str(root / "agent"))
        from cat_diary import register
        if not register(resource):
            print("猫咪日记动作注册失败。", file=sys.stderr)
            return 1
    if args.task == "MonthlyTrialDungeons":
        sys.path.insert(0, str(root / "agent"))
        from monthly_dungeons import register
        if not register(resource):
            print("月度副本动作注册失败。", file=sys.stderr)
            return 1
    if args.task == "MonthlyStarTrial":
        sys.path.insert(0, str(root / "agent"))
        from monthly_trial import register
        if not register(resource):
            print("月度试炼动作注册失败。", file=sys.stderr)
            return 1
    if args.task.startswith("Dungeon") or args.task == "MonthlyTrialDungeons":
        sys.path.insert(0, str(root / "agent"))
        from dungeons import register
        if not register(resource):
            print("副本动作注册失败。", file=sys.stderr)
            return 1
        if args.task == "DungeonSkip":
            time_limit = 60 + sum(600 + count * 90 for _, count in skip_plan)
    if args.task.startswith("Navigation"):
        sys.path.insert(0, str(root / "agent"))
        from navigation import register
        if not register(resource):
            print("移动动作注册失败。", file=sys.stderr)
            return 1
    if not resource.post_bundle(root / "assets" / "resource").wait().succeeded:
        print(f"资源加载失败，请检查 debug/{log_dir} 下的日志。", file=sys.stderr)
        return 1
    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        print("MaaFramework 初始化失败。", file=sys.stderr)
        return 1

    override = {}
    if args.task == "MenasAppraisal":
        override = {"MenasAppraisal": {"custom_action_param": appraisal_params}}
    if args.task == "MenasTrial":
        override = {"MenasTrial": {"custom_action_param": {"count": args.count}}}
    if args.task == "DungeonSkip":
        override = {"DungeonSkip": {"custom_action_param": skip_params}}
    if args.task == "NavigationMove":
        override = {"NavigationMove": {"custom_action_param": {"direction": args.direction, "duration": 600}}}
    job = tasker.post_task(args.task, override)
    deadline = time.monotonic() + time_limit
    try:
        while not job.done:
            if time.monotonic() >= deadline:
                print(f"任务超过 {time_limit // 60} 分钟，停止任务。请检查当前画面。", file=sys.stderr)
                tasker.post_stop().wait()
                return 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        tasker.post_stop().wait()
        print("任务已停止。", file=sys.stderr)
        return 130

    detail = job.get()
    if detail:
        print(" → ".join(node.name for node in detail.nodes))
    if not job.succeeded or not detail or not detail.nodes or detail.nodes[-1].name != completion_node:
        print("任务失败，请检查当前画面与日志。", file=sys.stderr)
        return 1
    print(success_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
