# 猫咪日记印章样本

`cat_diary_stamps.npz` 来自 2026-09-09 MuMu 实机，MaaFramework 5.12.3，缩放至 1280×720。
仅保存日记印章区域 `frame[514:566,358:898]` 的 BGR 像素；`bands` 按下表顺序排列，`expected` 为实际印章数。

| 样本 | 印章数 | 采集时点 |
| --- | --- | --- |
| 0 | 5 | 当日三只猫均未完成 |
| 1 | 7 | 那古萨无交互后，礼物位置出现第七枚红爪印 |
| 2 | 1 | 猫神神社交互后，新卡第一枚红爪印 |

`tools/test_cat_diary.py` 将区域放回相同坐标，调用正式印章识别函数，验证第七枚和换卡边界。
完整原图留在本机忽略目录 `debug/cat/`，分别为 `today_initial_diary.png`、`nagsham_result.png`、`shrine_today_result.png`。
