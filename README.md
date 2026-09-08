# MAAEden

<p align="center">
  <img src="assets/logo.png" alt="MAAEden 猫可可图标" width="256" height="256">
</p>

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的猫游（另一个伊甸：超越时空的猫）自动化工具，GUI 使用与 M9A 同生态的 [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)。当前适配 16:9 横屏安卓模拟器。
只适用于国服

## GUI 运行

本地构建后打开 `install/MFAAvalonia.exe`。运行包包含 .NET 与 Python，无需另外安装这两个运行时；请保留整个 `install` 目录，不要单独移动 exe。

1. 在模拟器内完成账号登录。
2. 在 GUI 的设备设置中选择实际运行游戏的模拟器，检查 ADB 路径和地址。存在多个模拟器时，请勿直接使用自动选中的第一台。
3. 勾选要运行的任务，配置对应选项，再开始执行。所有任务默认不勾选。

主要是清日常和月常，可以自己打梅纳斯，设定副本扫荡，去晓之塔的怪物巢穴刷星天的200战斗

GPT6Astra它强的简直可怕(

很多功能没经过仔细的尝试验证，出问题随缘改。因为猫游已经进入末期了，除非有什么新的比较繁琐的日常内容，否则更新频率应该不会太高...也不去搞什么在线更新这类东西了

能用就用一下，用不了说明我大概也删游跑路了_(:з」∠)_


## 开发

开始修改前阅读 [项目规则](rules.md) 和 [开发说明](docs/zh_cn/develop/how_to_develop.md)。资源流程位于 `assets/`，Python 自定义逻辑位于 `agent/`。

感谢 MaaFramework、MaaPracticeBoilerplate、MFAAvalonia 与 M9A 提供的框架和参考。GUI 上游许可证与源码地址随运行包保存在 `licenses/`。
