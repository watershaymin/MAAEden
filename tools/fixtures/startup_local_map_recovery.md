# 启动后区域地图恢复回放（2026-09-30）

环境：MuMu `127.0.0.1:16384`，MaaFramework 5.12.3，1280×720 控制器截图。
当日自动数据下载、读取存档、关闭公告后，游戏恢复到展开的埃尔吉昂伽玛区地图。
原启动流程只等待主场景、公告或梅纳斯选关页，最终超时，猫咪日记尚未开始。

新增 `StartUpCloseLocalMap` 同帧要求区域图标题装饰和置信度至少 0.8 的非空标题。
装饰复用 `NavigationLocalMap` 的原阈值 0.85；文字使用 `[15,10,640,53]`，不改动通用导航 OCR。
去除标题的反例仍可能读出低分 `YBAR`（0.509），因此不能直接复用默认低阈值的任意非空文字判据。
识别成功后只点击地图切换位置 `(1150,140)` 一次，再等待主场景；画面不变时失败，不能再次切换把地图展开。

`startup_local_map_recovery.npz` 保存 7 张真实截图的局部区域，另复用既有选关页样本作为反例。

| 样本 | 原图路径（仓库根目录下） |
| --- | --- |
| `local_map` | `debug/cat/2026-09-30/startup-local-map.png` |
| `long_map` | `debug/cat/2026-09-26/museum-library-map.png` |
| `world` | `debug/cat/2026-09-29/initial/StartUp-final.png` |
| `diary` | `debug/cat/2026-09-29/fixed2/CatDiary-final.png` |
| `world_map` | `debug/cat/2026-09-26/initial/CatDiary-final.png` |
| `download` | `debug/cat/2026-09-30/startup-download.png` |
| `desktop` | `debug/cat/2026-09-30/initial/start.png` |

每组只保存标题区域 `[0,0,800,110]`、主场景菜单 `[25,625,120,78]`、地图按钮 `[235,630,85,73]`。
`rois` 保存上述坐标；`<name>_i` 是相应裁剪，测试时拼回黑底完整截图。

`tools/test_startup_local_map_recovery.py` 使用原生框架确认：

- 两张区域图正例和六种其他画面反例。
- 移除标题、移除装饰、合成半亮度区域图都不触发。
- 区域图 → 一次收起 → 主场景成功。
- 区域图不变时只点击一次，随后失败，不到达完成节点。

回放控制器只在内存中切换画面，不连接模拟器；真实恢复结果见 `debug/cat/2026-09-30/fixed1/StartUp-result.json`。
