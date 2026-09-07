"""验证运行包的原生 Agent 客户端、Python 子进程、注册和正常退出，不操作游戏。"""

import argparse
import os
from pathlib import Path
import subprocess


def check(package):
    # 与 GUI 入口补丁一致；必须在加载 Maa 原生库前设置。
    temp = package / 'temp'
    temp.mkdir(exist_ok=True)
    os.environ['TMP'] = os.environ['TEMP'] = str(temp)

    from maa.library import Library
    from maa.agent_client import AgentClient
    from maa.resource import Resource
    from maa.toolkit import Toolkit

    Library.open(package / 'runtimes/win-x64/native')
    Toolkit.init_option(str(package / 'debug/agent-smoke'))
    resource = Resource()
    client = AgentClient()
    assert client.set_timeout(10000), '设置通信超时失败'
    assert client.bind(resource), '绑定资源失败'
    log_path = package / 'debug/agent-smoke/server.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            [str(package / 'python/python.exe'), '-X', 'utf8',
             str(package / 'agent/main.py'), client.identifier],
            cwd=package, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            assert client.connect(), f'Agent 握手失败，参见 {log_path}'
            assert client.connected and client.alive, 'Agent 连接状态异常'
            actions = client.custom_action_list
            recognitions = client.custom_recognition_list
            assert {'NavigationMove', 'NavigationBaruokiRoute', 'DungeonSkip',
                    'DungeonDismissDetail', 'MonthlyStarTrial', 'MonthlyTrialDungeons'} <= set(actions), actions
            assert 'DungeonMenuReady' in recognitions, recognitions
            print(f'Agent 握手及注册通过：{actions}, {recognitions}', flush=True)
            assert client.disconnect(), 'Agent 断开失败'
            assert process.wait(timeout=15) == 0, f'Agent 退出异常：{process.returncode}'
            print('Agent 正常断开，子进程退出码 0', flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'install')
    check(parser.parse_args().package.resolve())
