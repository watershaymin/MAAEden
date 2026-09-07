# MAAEden

<p align="center">
  <img src="assets/logo.png" alt="MAAEden 猫可可图标" width="256" height="256">
</p>

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的《另一个伊甸》自动化工具，GUI 使用与 M9A 同生态的 [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)。当前适配 16:9 横屏安卓模拟器。

## GUI 运行

本地构建后打开 `install/MFAAvalonia.exe`。运行包包含 .NET 与 Python，无需另外安装这两个运行时；请保留整个 `install` 目录，不要单独移动 exe。

1. 在模拟器内完成账号登录。
2. 在 GUI 的设备设置中选择实际运行游戏的模拟器，检查 ADB 路径和地址。存在多个模拟器时，请勿直接使用自动选中的第一台。
3. 勾选要运行的任务，配置对应选项，再开始执行。所有任务默认不勾选。

当前包含启动登录、梅纳斯试炼、邮件领取、副本跳过等任务。梅纳斯可指定次数，默认 0 表示用完当前入场券。
副本跳过自动前往蓝门，红票、绿票和猫掌券不足时是否使用星天之证补充可分别设置，默认不补充，票不足即停止。
基础移动、巴尔沃基传送和寻路、前往副本蓝门默认隐藏，保留命令行调试入口。

新增[星天试炼·每月200胜](docs/zh_cn/develop/monthly_trial.md)：读取本月已有胜场，前往晓之塔魔物巢穴补足剩余进度，完成后停留试炼页。需要预先配置能够持续通关的队伍。

[星天试炼·指定副本](docs/zh_cn/develop/monthly_dungeons.md)：OCR 读取本期三个副本任务，与现有跳过目录匹配；未达成且可跳过的各执行一次，回到试炼页核对完成状态，其余略过。副本每月变化无需修改配置。

[猫咪日记](docs/zh_cn/develop/cat_diary.md)：读取三只猫的地点线索，传送并追踪移动中的羽毛图例；每次找到后重新读取新线索，直到三只猫均完成。地点库含 76 条，部分地图与跨楼层路线仍待适配，详见功能说明。

**当前 GUI 验证状态：** 已修复 Agent 通信初始化的 ZeroMQ 错误；Windows x64 构建、Agent 握手与模块注册、正常退出均通过验证。GUI 已连接 MuMu，成功执行“启动并登录”并进入游戏主界面；消耗票券的任务尚未通过 GUI 验证。详见 [GUI 构建与排错](docs/zh_cn/develop/gui.md)。

## 构建

准备 Git、.NET 10 SDK、Python 3.12，以及 `assets/resource/model/ocr/` 下的 OCR 模型，然后在仓库根目录执行：

```powershell
./tools/build_gui.ps1 -Python python -Run
```

需要代理时通过 `-Proxy http://127.0.0.1:端口` 指定。重新构建前关闭当前运行包的 GUI。具体依赖版本、输出结构和验证方法见 [构建说明](docs/zh_cn/develop/gui.md)。

## 开发

开始修改前阅读 [项目规则](rules.md) 和 [开发说明](docs/zh_cn/develop/how_to_develop.md)。资源流程位于 `assets/`，Python 自定义逻辑位于 `agent/`。

感谢 MaaFramework、MaaPracticeBoilerplate、MFAAvalonia 与 M9A 提供的框架和参考。GUI 上游许可证与源码地址随运行包保存在 `licenses/`。
