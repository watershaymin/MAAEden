# 入场队伍栏位样本

2026-09-25，MuMu 安卓设备，MaaFramework 5.12.3，控制器缩放输出 1280×720。
使用正式 `team_selection.select_team` 在月影森林非常困难（红票）、困难（绿票）和梅纳斯 SS
入场确认页分别切换队伍 1～10，并逐帧验证当前栏位。未点击跳过、移动或进行挑战。

`team_selection.npz` 包含 33 张 PNG 编码裁片，每张是原图 `[490, 544, 300, 38]`：

- `red_1`～`red_10`、`green_1`～`green_10`、`menas_1`～`menas_10`：三种页面各 10 个实机栏位。
- `no_marker`：实机主界面同一区域，无选中标记。
- `double_marker`：在真实梅纳斯队伍 1 样本上另复制一个选中圆点到栏位 3，验证拒绝歧义。
- `wrong_position`：将真实圆点放在十个栏位以外的横坐标，验证拒绝错位。

模板 `assets/resource/image/TeamSelection/Selected.png` 裁自最初梅纳斯队伍 1 的
`[496, 548, 25, 25]`，验证样本来自后续实际切队，非仅模板自匹配。
原始整图和探测脚本保存在本地忽略目录 `debug/team-selection/`。
