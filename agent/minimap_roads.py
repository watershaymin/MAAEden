"""只在已识别图例的遮挡框内补齐直角；不跨地图空白猜路。"""

import cv2
import numpy as np


def _runs(line, origin):
    padded = np.pad(line.astype(np.int8), (1, 1))
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1)
    return [origin + (a+b-1)/2 for a, b in zip(starts, ends) if 8 <= b-a <= 28]


def complete_corners(road, boxes, anchor):
    """两个可见轴向路口唯一相交时补角；角色所在遮挡框允许角色作为端点。"""
    visible = cv2.resize(road.raw.astype(np.uint8), (1280, 720), interpolation=cv2.INTER_NEAREST)
    added = np.zeros_like(visible)
    for bx, by, bw, bh in boxes:
        # 合并大面积遮挡会隐藏多个路口，不能推断其拓扑。
        if bw > 90 or bh > 80:
            continue
        # RoadMap 会扩大遮挡并腐蚀路缘；采样线须落在这个安全边缘之外。
        x0, x1 = max(170, bx-16), min(1115, bx+bw+16)
        y0, y1 = max(140, by-16), min(610, by+bh+16)
        if x1 <= x0 or y1 <= y0:
            continue
        horizontal = [(x, y) for x in (x0, x1) for y in _runs(visible[y0:y1+1, x], y0)]
        vertical = [(x, y) for y in (y0, y1) for x in _runs(visible[y, x0:x1+1], x0)]
        ax, ay = anchor
        if bx <= ax <= bx+bw and by <= ay <= by+bh:
            if vertical and not horizontal:
                horizontal = [(ax, ay)]
            elif horizontal and not vertical:
                vertical = [(ax, ay)]
        if not horizontal or not vertical:
            continue
        ys = [p[1] for p in horizontal]
        xs = [p[0] for p in vertical]
        if max(xs)-min(xs) > 8 or max(ys)-min(ys) > 8:
            continue
        corner = (round(float(np.mean(xs))), round(float(np.mean(ys))))
        if not (bx-4 <= corner[0] <= bx+bw+4 and by-4 <= corner[1] <= by+bh+6):
            continue
        for x, y in horizontal:
            cv2.line(added, (round(x), corner[1]), corner, 1, 12)
        for x, y in vertical:
            cv2.line(added, (corner[0], round(y)), corner, 1, 12)
    patch = added.reshape(180, 4, 320, 4).mean(axis=(1, 3)) >= .5
    road.grid |= patch
    road.raw |= patch
    from cat_diary import erode
    road.clearance = road.grid.astype(np.int16)
    for radius in (2, 3):
        road.clearance += erode(road.raw, radius)
    return road
