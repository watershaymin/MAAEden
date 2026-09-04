# MAAEden 项目规则

本文将 M9A 的可复用经验转化为 MAAEden 的开发约定。考察日期：2026-09-05；参考快照为 M9A `main` 的提交 [`b7bbc0c`](https://github.com/MAA1999/M9A/tree/b7bbc0c162036dee20e8d048b56e1226c0c312c9)。本文件记录架构和开发方法，不表示已实现对应功能。

## 1. 当前基础与适用范围

MAAEden 当前是 MaaPracticeBoilerplate 模板项目，使用 MaaFramework 执行图像识别与模拟操作，并非 MaaFramework 核心源码仓库。

| 当前路径 | 职责 |
| --- | --- |
| `assets/interface.json` | Project Interface V2：控制器、资源包、任务、用户选项和 Agent 配置 |
| `assets/resource/pipeline/` | JSON 任务流程 |
| `assets/resource/image/` | 识别模板图片 |
| `assets/resource/model/` | 运行时模型资源，遵守现有忽略规则 |
| `assets/MaaCommonAssets/` | 公共资源子模块 |
| `agent/` | Python 自定义动作与识别，入口为 `main.py` |
| `deps/tools/` | 本地协议 Schema |
| `tools/`、`.github/workflows/` | 校验、配置与打包流程 |

沿用当前结构增量开发。M9A 的 `tasks/`、`i18n/`、`resource/base/` 等目录是参考设计；需要引入时，同步调整接口路径、工具配置和打包脚本。

使用新字段、Pipeline v2 写法或 `[JumpBack]` 前，核对实际 MaaFramework 运行版本、本地 Schema 与对应官方协议。`interface_version: 2` 不等于已经验证所有 Pipeline v2 能力。M9A 的运行时版本和 beta 通道不直接成为本项目要求。

## 2. JSON 流程优先，Python 处理复杂逻辑

- 页面导航、按钮点击、常规 OCR、模板匹配和简单分支优先用 Pipeline 表达。
- 数字解析、组合识别、资源规划、复杂状态计算等超出 Pipeline 表达能力时，再增加 Python Custom Action / Custom Recognition。
- 按功能拆分 Pipeline 和图片目录；节点使用有业务含义的名称，如 `DailyRewardEnter`、`DailyRewardClaim`，共享节点单独组织。
- 同一资源层内保持节点名唯一；跨资源层复用同名节点时，明确其覆盖用途。
- Python 模块增多后，可按 `agent/custom/action/`、`agent/custom/reco/`、`agent/utils/` 分工，避免继续堆积在模板的 `my_action.py`、`my_reco.py` 中。
- 新 Custom 模块必须被 Agent 启动链实际导入，注册名与 Pipeline 引用一致。启用前还要配置 `assets/interface.json` 中的 Agent；当前模板的 Agent 配置处于注释状态。
- 将纯计算、参数解析与截图/控制器操作分开，便于对关键边界行为做独立验证。

参考：[Custom 文档](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/docs/zh_cn/develop/custom.md)、[模块注册](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/agent/custom/action/__init__.py)、[数字比较识别](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/agent/custom/reco/compare_numbers.py)。

## 3. 以画面状态驱动流程

- 编写可运行的识别节点前，先取得真实截图、目标区域及页面跳转信息。缺少素材时可先完成接口、流程设计与明确标注的骨架，不编造可用的坐标、OCR 文本或模板图片。
- 坐标和模板应基于控制器实际输出的缩放截图。当前模板设置短边 720；横屏且比例为 16:9 时基准为 1280×720，其他比例需要独立核对。
- 每个任务明确入口条件、关键中间状态和完成条件；点击后的跳转由后续识别确认，不能仅凭“点击调用成功”判定业务完成。
- `next` 的候选顺序体现优先级：若弹窗与背景同时可识别，弹窗处理通常应先于背景节点。覆盖正常出口、合理的过渡画面和已知异常弹窗。
- 页面切换或动画造成不稳定时，优先补充中间识别，或使用合适区域的 `pre_wait_freezes` / `post_wait_freezes`。固定延时仅用于确有依据的场景，并说明原因，避免把增加等待时间作为通用修复。
- 通用返回、关闭弹窗、奖励确认可提取为公共节点；需要处理后返回原流程时，在确认协议支持后使用 `[JumpBack]`。
- 谨慎使用 `DirectHit` 和 `inverse`，避免无条件节点抢占后续候选或在未知画面误操作。
- 循环和重试必须有可观察的状态变化、退出条件及次数或时间上限；错误要定位原因，不叠加无依据的重试。
- 图片按功能归档，资源引用使用 `/`。调整阈值、ROI 或模板时，尽量用成功和失败样本检查误识别情况。

参考：[Pipeline 文档](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/docs/zh_cn/develop/pipeline.md)、[奖励领取流程](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/resource/base/pipeline/awards.json)。以上上限与验证要求是面向 MAAEden 的约定，不代表 M9A 每个节点均已满足。

## 4. 任务选项与流程保持一致

- 用户可调的次数、目标、开关等放在 Project Interface，通过 `pipeline_override` 或 Custom 参数传入，避免散落在 Python 或节点里。
- 增加任务时，一起检查任务入口、选项引用、覆盖节点、图片路径以及默认值；选项必须确实改变对应运行行为。
- 将任务 `name`、选项键、case 名称视为稳定标识。修改显示文本优先使用 `label`，重命名标识时同步处理引用及已有配置兼容。
- 新任务先保证可单独运行；有多个稳定任务后，再用预设组合日常流程，避免所有功能相互依赖。
- 当前任务量少时继续使用 `assets/interface.json`。需要拆分时，可在确认客户端和协议支持后采用 `import` 引入 `assets/tasks/`，并验证发布包包含导入文件。

参考：[M9A 接口](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/interface.json)、[奖励选项](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/tasks/Awards.json)、[日常预设](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/tasks/preset/Daily.json)。

## 5. 有需求后再引入的能力

| M9A 的做法 | MAAEden 的引入时机与约定 |
| --- | --- |
| 基础资源包 + 渠道/语言差异包 | 出现第二个实际客户端差异时再拆分。通用逻辑放基础层，差异层只覆盖必要节点或图片，明确加载顺序；不要复制整套流程。 |
| 界面国际化 | 需要多语言界面时引入 `assets/i18n/`，用稳定 ID 与显示文本分离。声明的语言表须覆盖所引用的键；游戏内 OCR 文本属于资源适配，不随助手界面语言直接替换。 |
| ADB、Win32 等多控制器 | 先验证实际使用的设备与控制方式。分别记录截图、点击和窗口匹配配置，不能把模板里的示例控制器当作已支持平台。 |
| 分辨率事件检查 | 出现多分辨率适配需求时，可在任务开始时检查屏幕比例和尺寸，提前报告不兼容配置。 |
| 游戏数据与执行逻辑分离 | 出现掉落表、物品表、活动时间或规划算法时，将数据集中管理并记录来源与更新方式。 |
| 资源更新与打包冒烟检查 | 发布需求明确后再引入；优先确保包内资源路径、OCR 模型、Agent 导入和运行时版本一致。热更新、遥测、第三方分发需要独立设计，不作为初始默认配置。 |

参考：[资源与控制器配置](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/interface.json)、[国际化约定](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/docs/zh_cn/develop/i18n.md)、[分辨率检查](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/agent/custom/sink/aspect_ratio.py)、[打包冒烟检查](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/.github/workflows/package-smoke.yml)。

## 6. 排错与验证

- 排错时记录框架/资源版本、控制器、资源包、任务选项和复现步骤，结合日志与截图定位最后一个正确节点和首个异常节点。
- 区分资源加载失败、连接失败、识别失败与流程分支缺失；先定位这一层，再修改对应实现。
- Custom 日志保留任务/节点、关键输入、识别结果与失败原因。错误不得被吞掉后伪装成成功。
- 代码检查无法替代实机验证。功能变更按影响范围验证正常路径、相关异常分支和停止行为，并明确哪些场景尚未验证。
- 参数解析、数值计算、状态重置与模块注册等复杂或易回归逻辑值得增加针对性测试；纯文档和低影响改动不机械添加测试。
- 遵循本仓库 `.editorconfig` 与 `.prettierrc`；新增 Markdown、JSON、Python 使用 UTF-8 无 BOM，避免无关格式化。

当前可复用的检查命令来自本仓库 `.github/workflows/check.yml`，在仓库根目录、依赖已安装的环境下执行：

```sh
npm ci
npx @nekosu/maa-tools check
python tools/validate_schema.py --schema-dir deps/tools --resource-dirs assets/resource --exclude-dirs assets/resource/announcement --interface-files assets/interface.json
```

Schema 校验还需要 `jsonschema` 与 `referencing`，依赖版本以现有 CI 为准。新增资源层或拆分接口后，同步更新校验范围。环境缺失或检查失败时，报告实际原因，不宣称验证通过。

M9A 有 `pnpm check`、`pnpm check:py`、Ruff、Pyright 和 pytest；MAAEden 当前尚未配置这些脚本，不能直接要求运行。未来引入时一起配置依赖、命令与 CI，并按改动范围执行。本次仅文档修改时检查差异、路径和规则一致性即可。

参考：[M9A 排错流程](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/docs/zh_cn/develop/fix.md)、[检查脚本](https://github.com/MAA1999/M9A/blob/b7bbc0c162036dee20e8d048b56e1226c0c312c9/package.json)。

## 7. 后续实现的推荐顺序

先确认目标游戏、平台、截图缩放方式和第一个小任务；打通“识别入口 → 操作 → 确认完成”的最小流程。随后提取返回、关闭弹窗等公共节点，增加任务选项与必要的 Custom 扩展。形成可重复验证的基础功能后，再按实际需求增加任务预设、差异资源包、国际化和发布增强。

这些阶段是开发建议，不代表当前已完成；每次交付应说明修改文件、实际验证结果及下一项需要补齐的素材或环境。
