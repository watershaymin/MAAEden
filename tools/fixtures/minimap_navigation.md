# 小地图导航回放样本

`minimap_navigation.npz` 来自 2026-09-19 MuMu 真机序列，原始分辨率为控制器输出的 1280×720 BGR。
不包含合成角色或人为标注的道路图片。

- `baruoki_base` / `konium_base`：关闭区域图后、未发生移动的场景，裁切 `(165,130,955,490)`。
- `*_map`：同机位展开区域图 10 帧的中值图，使用相同裁切。
- `*_mini`：关闭区域图后序列的最后两帧，裁切 `(1020,20,242,155)`。
- `*_position` / `*_mini_position`：各自序列的圆心，用于检验整图和小地图几何配准的交叉一致性。
  它们来自两组独立图像的检测结果，不是游戏内世界坐标真值。
- `overlap_mini` / `overlap_large`：柯尼姆角色与黄色任务图例重叠的原始连续局部帧，
  `*_roi` 保存原始裁切位置。前者 8 帧，后者 10 帧；实机圆环位置约为 `(1109,95)`、`(579,359)`。
  旧实现会把大图中的任务图标小孔定位到约 `(580,341)`。
- `star_exit_overlap`：扩图测试中星之塔 1 楼出口处的小地图原始 8 帧，裁切同 `MINI_ROI`。
  稳定内孔中心约 `(1166,116)`；旧实现因外圈圆心偏移而否决内孔，返回 `(1168.5,119.5)`，
  在整图坐标中放大为约 8px 偏差。新回归同时保留上面的任务图标反例。

测试将裁切放回原尺寸空白帧，不改变局部颜色或动画。仅恢复必要区域；并不伪装为完整真实截图。

## 扩图问题修复样本

`minimap_sparse.npz` 保留首次失败时的七组展开图中值、场景基底、8 帧小地图和独立展开图圆心。
来源为 `debug/minimap/survey/<case>/run1/sequence-00.npz`、`sequence-01.npz`、`start.png`，
其中 `cat_04` 使用 `run2`。case 包含 `cat_04`、`cat_10`、`cat_38`、`cat_48`、`cat_50`、
`fantasy`、`iskariot`。山道 `cat_48` 的比例明显不同，不能固定按 2 倍还原。

`minimap_repair.npz` 来自修复期间的原始记录：

- `industrial_handoff`：`repair/cat_38/run3/sequence-11..14`，首帧特征定位成功，移动后转为轮廓定位。
- `industrial_mixed`：同次 `sequence-14..17`，相邻两帧分别走特征和轮廓路径，但独立坐标一致。
- `tiny_background`：`repair/fantasy/run2/sequence-00..01` 与 `start.png`，保留开关地图前后人物姿态变化。
  `_before`、`_base` 是两侧背景；取较亮值后能剔除人物残影，避免残影压低小地图轮廓匹配分数。

两个新增文件沿用上述 BGR 和 ROI；`_moved` 是移动后的原始小地图序列，`_measured` 来自其后独立展开图。
样本用于离线回归，不是运行时地图模板。

## 默认任务接入样本

`minimap_targets.npz` 保存三组成对真实截图的必要区域，外部填零，不改变区域内像素：

- `palace`：`debug/cat/2026-09-19/palace-base.png`、`palace-map.png`。
- `castle`：`debug/cat/2026-09-13/castle-2f-base.png`、`castle-2f-map.png`。
- `isiya`：`debug/cat/2026-09-15/isiya-base.png`、`isiya-map.png`。

`*_base` 保留 MAP_ROI 和 MINI_ROI，`*_map` 保留 MAP_ROI。`*_player`、`*_mini_player`
是用于屏蔽角色附近配准特征的截图圆心（宫殿、城堡整图圆心按截图人工标注）。
这组三个静止截图对只验证羽毛识别和地图投影，不作为呼吸环时序或完整寻猫的验证依据。
`tools/test_minimap_targets.py` 用实际 Maa 模板识别两个尺寸的羽毛，检查投影误差和空白负样本。
`xeno_gold` 是 2026-09-19 控制所入口金色出口按钮的真实画面（仅保留按钮识别 ROI），
模板 `CatDiary/XenoDoorGold.png` 裁自其中 `[456,176,61,61]`；已实机点击并核验研究中心落点。

`minimap_titles.npz` 包含 6 组原始标题 ROI `(15,10,640,53)`：
`kms` 来自 `repair/kms/final1/frame-16.png` 的“I旧”误识别；`acid` 来自
`survey/cat_08/run1/frame-00.png` 的白色过滤误识别；`tower` 来自 `repair/cat_10/run1/frame-00.png`。
`ishana_start`、`ishana_east` 来自 2026-09-20 的 `debug/cat/2026-09-20/ishana-map.png`
与 `fixed5/CatDiary-final.png`，验证“巳之国伊刹那”起点彩色 OCR 将“巳”读为“已”时，
以完整预期名称触发现有灰度补充识别，并与东侧正确标题保持一致。
`pador` 来自 2026-09-25 的 `debug/cat/2026-09-25/initial/CatDiary-final.png`，
实际标题为“古代树之村 帕德列”；旧地点配置仅为简称“帕德列”，不能通过显式地图名称的精确校验。
回放同时读取地点配置，检查完整实机标题可接受，而缺少前缀的简称或附加楼层不能接受。
`tools/test_minimap_ocr.py` 用不允许任何输入的离线控制器运行真实 Maa OCR，并确认错误楼层不能通过。

`cat_diary_sami.npz` 来自 2026-09-20 佐见 `debug/cat/2026-09-20/sami-pulse.npz` 的 10 帧序列，
保留角色区域 `[620,369,70,70]` 与移动羽毛区域 `[714,170,82,70]` 的原始 BGR 像素。
不排除羽毛时产生两个脉动候选 `(756.5,205.5)`、`(653.05,402.70)`；排除同帧羽毛识别框后只保留后者。
`tools/test_minimap_navigation.py` 验证该反例，以及排除后零候选或仍有两个候选的停止边界。

`cat_diary_konim_road.npz` 来自 2026-09-22 柯尼姆失败现场的 `konim-base.png`、`konim-map.png`，
原图及遮挡框记录保存在 `debug/cat/2026-09-22/`。仅保留 `[600,320,240,80]` 的原始 BGR 像素，
附实际识别的图例遮挡框及整图呼吸环圆心 `(783.88,360.17)`。
角色环与旁边图例共同遮住路端，新提取道路不能接受该圆心；这张样本不允许扩大补路范围。
`tools/test_navigation_sessions.py` 回放此失败，验证同图且独立坐标符合旧道路时可复用先前道路，
并覆盖首次建模没有旧图、旧道路不覆盖当前位置、地图偏移变化三种仍须停止的情况。
