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

构建机需要 Git、.NET 10 SDK 和 Python 3.12。先运行 `git submodule update --init assets/MaaCommonAssets`；构建脚本会从该固定子模块配置 OCR 模型。

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

## 发布 Windows Release

正式发布使用全新目录，避免混入本机配置、日志和旧资源。`-Output` 指定的目录必须为空；不指定时仍使用 `install/` 并保留本机配置。

```powershell
./tools/build_gui.ps1 -Python python -Output build/package
python -X utf8 tools/create_release.py --package build/package --output build/artifacts --version v1.0.0
```

打包器核对标签、接口版本和构建提交，检查 GUI、.NET、Python、OCR 与许可证文件，并生成 ZIP 和 `.zip.sha256`。压缩包中排除配置、备份、截图日志、临时目录和 Python 缓存。应先提交源代码，再构建待发布的包，使 `build-info.json` 的提交号对应实际发布代码。

`.github/workflows/install.yml` 使用同一套脚本：先校验资源、Schema 和单元测试，再编译、执行原生 Agent 通信检查、封装产物。普通分支及 PR 只上传 Actions artifact；推送 `v*` 标签后自动发布 GitHub Release。标签必须匹配 `assets/interface.json` 的版本，并存在 `docs/zh_cn/releases/<标签>.md` 发布说明。当前正式分发目标为 Windows x64。

## 项目图标

MAAEden 使用猫可可的 Q 版图标，定稿保存在 [`assets/logo.png`](../../../assets/logo.png)，保持白色背景；Windows 图标为 [`assets/logo.ico`](../../../assets/logo.ico)，包含 16、24、32、48、64、128、256 像素版本。

- `assets/interface.json` 的 `icon` 指向同目录的 `logo.png`，供 GUI 界面、窗口和托盘使用。
- `build_gui.ps1` 通过 `ApplicationIcon` 将 `assets/logo.ico` 嵌入 Windows 程序文件；更换此文件后需要完整重建。
- `package_gui.py` 将两种图标放到运行包根目录，并保留 `assets/logo.png` 供随包 README 展示。
- 本地与 CI 都从固定 GUI 源码执行 Windows x64 Release 编译，将图标写入程序文件。

更新图标时先替换 PNG，再生成对应的多尺寸 ICO。仅更新运行时 PNG 可重新打包并重启 GUI；Windows 程序文件图标需要完整构建，资源管理器的图标缓存也可能延迟刷新。

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
