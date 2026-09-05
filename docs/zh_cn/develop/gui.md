# Windows GUI 构建与验证

GUI 直接采用 MFAAvalonia，沿用其设备连接、任务队列、选项配置、日志和设置界面。通过 Project Interface V2 加载 MAAEden 的现有任务，没有另外维护一套任务定义。

## 固定依赖

| 组件 | 版本 |
| --- | --- |
| MFAAvalonia | v2.16.1，提交 `4f11c8122de4f43eafc818a368c9956e3b06249c` |
| MaaFramework 原生运行时 / Python 包 | 5.12.3 |
| 内嵌 Python | 3.12.10，Windows x64 |
| .NET | 10，自包含发布 |

GUI 源码取自 <https://github.com/MaaXYZ/MFAAvalonia>，构建时应用 `tools/patches/gui-agent-temp.patch`，完成或失败后撤回补丁，保持依赖目录干净。运行包 `licenses/` 附带该补丁，`build-info.json` 记录补丁名称。Python 依赖固定在 `tools/gui-requirements.txt`。嵌入式 Python 压缩包由打包脚本校验 SHA256。

## 一键构建

构建机需要 Git、.NET 10 SDK 和 Python 3.12。先准备 OCR 模型 `assets/resource/model/ocr/det.onnx`、`rec.onnx`、`keys.txt`。

```powershell
./tools/build_gui.ps1 -Python python -Run
```

可以将 `-Python` 指向已有 Python 3.12 虚拟环境；可选 `-Proxy` 只影响本次构建，不修改全局 Git 配置。脚本下载源码和依赖、执行 `dotnet publish`、组合运行包，最后由 `-Run` 启动窗口。

输出 `install/` 包含 GUI、资源、Agent、独立 Python 和原生库。`build-info.json` 记录版本与项目提交；`licenses/` 保留 GUI 的 GPL-3.0 许可证和源码地址。重建保留现有 GUI 配置；配置、日志、运行包和下载的依赖不会提交到仓库。

若只更新项目资源，可在关闭 GUI 后运行以下命令（先完成一次完整构建）：

```powershell
python tools/package_gui.py
```

打包后的 `interface.json` 将 Agent 解释器指向包内 `python/python.exe`；源文件中的开发环境配置不受影响。

## 本机验证记录（2026-09-05）

- Windows x64 Release 自包含编译成功，GUI 已启动，加载全部 8 个任务及对应选项。
- 包内 Python 可导入 MaaFramework、NumPy、移动与副本模块，框架版本为 5.12.3。
- 已修复 `MaaAgentClientCreateV2` / `SEHException`：本机默认 `TMP` / `TEMP` 下，ZeroMQ 4.3.5 内部 IPC 初始化触发 `epoll.cpp:73` / `Bad file descriptor`；将临时目录设为包内 `temp/` 后客户端正常创建。切换外部通信为 TCP 仍会触发该问题，因为内部信号通信仍使用 IPC。相关上游分析：[zeromq/libzmq#4734](https://github.com/zeromq/libzmq/pull/4734)。
- GUI 在加载 Maa 原生库前设置进程级 `TMP` / `TEMP`，Python Agent 自动继承。直接打开 `MFAAvalonia.exe` 即生效，不修改系统或用户环境变量，也不需要关闭代理。运行包目录须可写；尚未验证包含中文或超长路径的安装位置。
- GUI 已连接 MuMu `127.0.0.1:16384`，成功启动 Agent；“启动并登录”从模拟器桌面运行约 44 秒，进入游戏主界面，任务状态 `SUCCEEDED`。截图方式 `EmulatorExtras`，输入方式 `Default`。
- 原生 GUI 客户端与包内 Python Agent 的独立冒烟检查通过：握手、移动/副本动作及识别器注册、主动断开和子进程退出码 0。未测试消耗票券的任务。

构建脚本会自动执行通信冒烟检查；也可单独运行（不连接模拟器、不操作游戏）：

```powershell
./install/python/python.exe -X utf8 tools/check_gui_agent.py
```

该检查使用 GUI 的原生 DLL 与包内 Python 子进程；临时目录设置与 GUI 补丁保持一致。它验证通信本身，不能代替直接打开 GUI 的实机检查。修改启动入口补丁后需要完整重建，仅运行 `package_gui.py` 不会更新 GUI 二进制。

排错时查看 `install/logs/` 和 `install/debug/`（若生成），记录设备与所选任务。首次启动还可能提示更新源错误：开发包尚未配置镜像分发，不代表本地资源不存在。

存在多个模拟器时需手动选择游戏所在设备。本机游戏使用 MuMu 的 ADB 地址 `127.0.0.1:16384`，实际使用时以模拟器配置为准。回归时先使用不消耗票券的任务验证，再测试会消耗资源的流程。
