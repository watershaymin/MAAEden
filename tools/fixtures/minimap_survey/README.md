# 15 张新区域的实机标定与结果

详见 [`docs/zh_cn/develop/minimap-survey.md`](../../../docs/zh_cn/develop/minimap-survey.md)。

各 `cat_*.json`、`kms.json`、`fantasy.json`、`iskariot.json` 是给
`tools/probe_minimap_maps.py --case` 使用的参数：

- `entry_id` 与 `teleport_override` 仅用于传送。地图身份以 `map_name` 的实际展开图标题为准。
- `waypoints` 是从 `source_capture` 原始截图人工选取的目标，使用 1280×720 展开图坐标。
- `segments` 若存在，是按同一截图标定的轴向道路中心线；只在测试对象内覆盖道路，未修改默认任务地图数据。
- `access_note` 说明需要先人工进入的区域，不能把城门外或无小地图房间当作导航起点。
- `evidence_root` 与 `source_capture` 组合得到原始截图路径。原始大体积帧与日志保留在本地 debug 目录。

`results.json` 保留所有导航尝试，包括失败和最早一次参数格式错误；
`final` 是每张地图最后一次参数合法的结果，不能把一次成功视为长期稳定性保证。
早期工具尚未记录源码散列或失败步数，缺失字段保持缺失，未事后伪造。

原始帧中需要长期回归的星之塔出口重叠样本另收录于 `../minimap_navigation.npz`，
不依赖本地 debug 目录即可运行定位回归。
