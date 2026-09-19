"""在线展开图的轮廓配准；用于道路清楚但纹理/特征点稀少的地图。"""

import cv2
import numpy as np
import math


def background_stable(previous, current):
    """区分全屏淡入与局部雾气/人物动画；输入为缩小后的场景数组。"""
    difference = current.astype(np.float32) - previous.astype(np.float32)
    shift = float(np.median(difference))
    residual = float(np.median(np.abs(difference - shift)))
    return abs(shift) < 1 and residual < 4


def static_map_mask(image, factor=1):
    """排除巢穴粉色移动怪物图例；其刷新/位移不能成为道路配准证据。"""
    b, g, r = image.astype(np.int16).transpose(2, 0, 1)
    pink = ((r > 140) & (b > 115) & (np.minimum(r, b)-g > 45)).astype(np.uint8)
    valid = np.ones(image.shape[:2], np.uint8)
    count, _, stats, centers = cv2.connectedComponentsWithStats(pink, 8)
    for (_, _, w, h, area), (x, y) in zip(stats[1:], centers[1:]):
        if 4*factor <= w <= 32*factor and 4*factor <= h <= 32*factor and area >= 8*factor:
            cv2.circle(valid, (round(x), round(y)), math.ceil(max(w, h)/2+4*factor), 0, -1)
    return valid


class ContourAtlas:
    """白色半透明地图的前景轮廓，不依赖逐地图预设模板。

    全图用展开前后差分剔除场景，小图的道路叠在暗色面板上，三个颜色
    通道均高于 120。保留背景颜色混合，不要求道路是中性灰。
    比较共同可见前景的 Dice 相似度，同时要求全局次优解明显更差。
    """

    def __init__(self, base, overlay, position, excluded=()):
        delta = overlay.astype(np.float32) - base.astype(np.float32) * .5
        valid = np.zeros(overlay.shape[:2], np.uint8)
        valid[130:620, 165:1120] = 1
        valid *= static_map_mask(overlay, 2)
        cv2.circle(valid, tuple(map(round, position)), 36, 0, -1)
        for x, y in excluded:
            cv2.circle(valid, (round(x), round(y-18)), 28, 0, -1)
        foreground = (delta.min(axis=2) > 20).astype(np.uint8) * valid
        self.foreground = cv2.resize(foreground.astype(np.float32), (640, 360), interpolation=cv2.INTER_AREA)
        self.valid = cv2.resize(valid.astype(np.float32), (640, 360), interpolation=cv2.INTER_AREA)
        self.anchor = position
        self.scale = None
        self.excluded = []

    def register(self, mini, player):
        # 大型区域的展开图会缩放。首次用同机位的整图角色位置校准比例；
        # 每个候选本身仍须有唯一的全局轮廓峰，不能仅靠锚点选重复道路。
        if self.scale is not None:
            return self._at_scale(mini, player, self.scale)
        try:
            result = self._at_scale(mini, player, 1.)
            if math.dist(result[0], self.anchor) <= 7:
                self.scale = 1.
                return result
        except ValueError:
            pass
        options = []
        def consider(scale):
            try:
                result = self._at_scale(mini, player, scale)
                if math.dist(result[0], self.anchor) <= 7:
                    options.append((result[2], scale, result))
            except ValueError:
                pass
        for scale in np.arange(.55, 1.251, .05):
            consider(float(scale))
        if not options:
            raise ValueError('轮廓比例校准失败：无唯一匹配与整图位置一致')
        coarse = max(options, key=lambda o: o[0])[1]
        for scale in np.arange(coarse-.03, coarse+.031, .005):
            consider(float(scale))
        _, self.scale, result = max(options, key=lambda o: o[0])
        return result

    def _at_scale(self, mini, player, scale):
        """返回整图坐标、前景像素数、峰值与次峰差；不使用历史位置选峰。"""
        if scale != 1.:
            mini = cv2.resize(mini, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        player = np.asarray(player) * scale
        valid = np.ones(mini.shape[:2], np.float32)
        valid *= static_map_mask(mini, scale)
        valid[:3] = valid[-3:] = 0
        valid[:, :3] = valid[:, -3:] = 0
        cv2.circle(valid, tuple(map(round, player)), round(18*scale), 0, -1)
        for x, y in self.excluded:
            cv2.circle(valid, (round(x*scale), round((y-9)*scale)), round(14*scale), 0, -1)
        foreground = (mini.min(axis=2) > 120).astype(np.float32) * valid
        count = int(foreground.sum())
        if count < 60:
            raise ValueError('轮廓前景不足')
        cross = cv2.matchTemplate(self.foreground, foreground, cv2.TM_CCORR)
        atlas_count = cv2.matchTemplate(self.foreground, valid, cv2.TM_CCORR)
        mini_count = cv2.matchTemplate(self.valid, foreground, cv2.TM_CCORR)
        scores = 2 * cross / np.maximum(1, atlas_count + mini_count)
        scores[mini_count < count * .8] = 0
        _, best, _, (x, y) = cv2.minMaxLoc(scores)
        # 比较不同的局部峰，而不是同一宽峰的斜坡。道路较宽时，离峰心六
        # 像素仍可能在同一峰上，不代表另一条可解释的道路；重复路段的峰保留。
        peaks = scores >= cv2.dilate(scores, np.ones((11, 11), np.uint8))
        alternatives = np.where(peaks, scores, 0)
        alternatives[max(0, y-5):y+6, max(0, x-5):x+6] = 0
        second = float(alternatives.max())
        margin = best - second
        if best < .68 or margin < .08:
            raise ValueError(f'轮廓匹配不唯一或不足：score={best:.3f} margin={margin:.3f}')
        # 对峰顶做局部插值，减少整图二倍放大带来的整数格点抖动。
        offset = []
        for axis, coordinate in enumerate((x, y)):
            line = scores[y, :] if axis == 0 else scores[:, x]
            delta = 0.
            if 0 < coordinate < len(line)-1:
                left, center, right = map(float, line[coordinate-1:coordinate+2])
                denominator = left - 2*center + right
                if denominator < -1e-6:
                    delta = float(np.clip(.5*(left-right)/denominator, -.5, .5))
            offset.append(coordinate + delta)
        position = (np.asarray(player) + offset) * 2
        return tuple(map(float, position)), count, best, margin
