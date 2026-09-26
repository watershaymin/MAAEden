# 猫咪日记对话与海报回放样本

`cat_diary_poster.npz` 保留 1280×720 控制器截图中的必要识别区域；回放将裁剪放回空白画面，不补画场景。

| 键 | 来源 |
| --- | --- |
| `page1` | 2026-09-25 体育场失败后采集的 `debug/cat/2026-09-25/poster-before.png` |
| `page2` | 点击一次后的 `poster-page2.png`；再点击一次已实测回到场景 |
| `world` | 两页说明关闭后的 `poster-closed.png` |
| `ordinary` | 2026-09-16 佐见稻草人对话，`debug/cat/2026-09-16/initial/agent-final-frame.npy` |
| `map` | 2026-09-25 帕德列区域图，`initial/CatDiary-final.png` |
| `diary` | 2026-09-24 三红爪完成日记，`fixed1/CatDiary-final.png` |

未写全路径的当日图片均在 `debug/cat/2026-09-25/`。
每个键保存六个原始 BGR 裁剪，坐标记录在 `rois`：
`[140,10,85,86]`、`[460,26,370,44]`、`[1130,15,140,45]`、`[0,515,135,28]`、
`[25,625,120,78]`、`[235,630,85,73]`，依次为海报边框、首行文字、普通对话记录、下框、主界面菜单和地图按钮。

模板 `CatDiary/StadiumPosterBorder.png` 裁自 `page1` 原图的 `[152,22,57,60]`。
`tools/test_cat_diary_dialogue.py` 验证两页海报和旧普通对话、三个实际负场景，以及移除边框、移除文字和半亮度负样本。
在没有设备连接的控制器中，还回放从海报两页返回主界面、关闭海报不算猫交互成功、
以及 `world` 与 `interact` 两条路径遇到不变页面时均最多点击 20 次的原有上限。
