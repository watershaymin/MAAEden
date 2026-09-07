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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb-path", required=True, type=Path)
    parser.add_argument("--address", required=True, help="例如 127.0.0.1:16384")
    parser.add_argument("--task", choices=list(TASKS), default="StartUp")
    parser.add_argument("--direction", choices=["left", "right", "up", "down"], default="left")
    parser.add_argument("--dungeon", default="snake_damak_vh")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if args.task == "DungeonSkip" and not 1 <= args.count <= 999:
        parser.error("--count 必须为 1～999")
    if not args.adb_path.is_file():
        parser.error("--adb-path 必须指向 adb 可执行文件")

    root = Path(__file__).resolve().parents[1]
    completion_node, time_limit, log_dir, success_message = TASKS[args.task]
    Toolkit.init_option(root / "debug" / log_dir)
    capture = MaaAdbScreencapMethodEnum.Encode
    input_method = MaaAdbInputMethodEnum.AdbShell
    config = {}
    if args.task == "CatDiary":
        # 移动目标需要及时截图。仅复用明确匹配用户所选地址的模拟器配置。
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
            time_limit = 600 + args.count * 90
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
    if args.task == "DungeonSkip":
        override = {"DungeonSkip": {"custom_action_param": {"target": args.dungeon, "count": args.count}}}
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
