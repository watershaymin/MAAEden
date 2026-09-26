"""共享小地图定位：整图建模、静态特征配准、呼吸环时序定位。
位置来自图像观测，运动指令只用于排除不合理跳变，不用于推算位置。
"""

from dataclasses import dataclass
import logging
import math
import time

import cv2
import numpy as np

LOG = logging.getLogger(__name__)
MINI_ROI = (1020, 20, 242, 155)
MAP_ROI = (165, 130, 955, 490)


class LocalizationLost(RuntimeError):
    """证据不足，停止移动并请求整图校准。"""


class NavigationInterrupted(RuntimeError):
    """采集期间进入战斗，由原任务恢复并重新建模。"""


@dataclass(frozen=True)
class Observation:
    position: tuple
    inliers: int
    residual: float | None
    source: str = "minimap"
    score: float | None = None
    margin: float | None = None
    transform: tuple | None = None  # 小地图 ROI 内坐标 -> 初次建模的整图屏幕坐标


def map_offset(runner, frame, road_key):
    from navigation import marker_position
    config = runner.map_anchors.get(road_key)
    if not config:
        return (0., 0.)
    anchor = runner.reco(config['node'], frame)
    if not anchor:
        raise LocalizationLost('未识别地图定位锚点')
    offset = tuple(a-b for a, b in zip(marker_position(anchor), config['point']))
    if abs(offset[0]) > 8 or abs(offset[1]) > 45:
        raise LocalizationLost(f'地图锚点偏移超出已验证范围：{offset}')
    return offset


def project_point(observation, point, offset=(0, 0)):
    if observation is None or observation.transform is None:
        raise LocalizationLost('没有可投影的小地图变换')
    matrix = np.asarray(observation.transform)
    return tuple(map(float, matrix[:, :2] @ np.asarray(point) + matrix[:, 2] - offset))


def feather_points(runner, frame, miniature=False):
    """复用实机羽毛图例；小图放大到原模板比例，返回图例脚下的道路点。"""
    image = cv2.resize(crop(frame, MINI_ROI), None, fx=2, fy=2) if miniature else frame
    override = {'CatDiaryMarker': {'roi': [0, 0, image.shape[1], image.shape[0]]}} if miniature else None
    marker = runner.reco('CatDiaryMarker', image, override)
    points = []
    for match in marker.filtered_results if marker else []:
        x, y, w, h = match.box
        point = ((x+w/2)/(2 if miniature else 1), (y+h/2+18)/(2 if miniature else 1))
        if not any(math.dist(point, other) < (6 if miniature else 12) for other in points):
            points.append(point)
    return points


def crop(frame, roi):
    x, y, w, h = roi
    return frame[y:y + h, x:x + w]


def read_map_name(runner, frame, expected):
    from cat_diary import compact
    name = compact(runner.text('NavigationMapName', frame, single_line=True))
    if not expected or name == compact(expected):
        return name
    # 旧 KMS 的彩色背景会把“旧”的竖画识别成多余 I。灰度保留笔画强度，
    # 不删字、不模糊匹配，也不依赖具体地图名做替换。
    gray = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    alternate = compact(runner.text('NavigationMapName', gray, single_line=True))
    return alternate if alternate == compact(expected) else name


def circle_support(energy, cx, cy, radius, factor):
    support = []
    for angle in np.linspace(0, 2 * math.pi, 16, endpoint=False):
        points = [(round(cx + (radius + d) * math.cos(angle)),
                   round(cy + (radius + d) * math.sin(angle)))
                  for d in (-1.5 * factor, 0, 1.5 * factor)]
        samples = [energy[y, x] for x, y in points
                   if 0 <= x < energy.shape[1] and 0 <= y < energy.shape[0]]
        support.append(max(samples, default=0))
    return np.count_nonzero(np.asarray(support) > 5)


def temporal_circles(energy, factor):
    """在时序能量上拟合圆周，静态任务图标不提供有效圆周证据。"""
    image = cv2.GaussianBlur(np.minimum(energy * 8, 255).astype(np.uint8), (3, 3), .6)
    circles = cv2.HoughCircles(image, cv2.HOUGH_GRADIENT, dp=1, minDist=8 * factor,
                               param1=60, param2=9 * factor, minRadius=3 * factor,
                               maxRadius=12 * factor)
    accepted = []
    if circles is None:
        return accepted
    for cx, cy, radius in circles[0]:
        # 16 个方向至少 13 个存在脉动弧线；箭头尖端不能代替圆环。
        if circle_support(energy, cx, cy, radius, factor) >= 13:
            accepted.append((float(cx), float(cy), float(radius)))
    return accepted


def pulse_candidates(frames, roi=MINI_ROI, previous=None, max_distance=150):
    """在静止机位的短序列中找有时序变化的金色圆环，不匹配预设图片。

    圆环内孔中心不受外圈大小与方向箭头影响。重叠遮掉内孔或出现多个
    合理候选时拒绝定位，而不是将黄色任务菱形或历史位置当成角色。
    """
    if len(frames) < 4:
        raise LocalizationLost("角色呼吸环需要至少四帧")
    values = np.asarray([crop(f, roi) for f in frames], dtype=np.float32)
    b, g, r = values[..., 0], values[..., 1], values[..., 2]
    gold = (r > 135) & (r - g > 5) & (g - b > 22)
    energy = values.std(axis=0).mean(axis=2)
    dynamic = ((energy > 3) & gold.any(axis=0)).astype(np.uint8)
    dynamic = cv2.morphologyEx(dynamic, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dynamic, 8)
    factor = 2 if roi == MAP_ROI else 1
    circles = temporal_circles(energy * gold.any(axis=0), factor)
    candidates = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if not (7 * factor <= w <= 42 * factor and 7 * factor <= h <= 32 * factor
                and area >= 18 * factor * factor):
            continue
        arcs = [c for c in circles if x <= c[0] <= x + w and y <= c[1] <= y + h]
        centers = []
        for mask in gold:
            contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP,
                                                   cv2.CHAIN_APPROX_SIMPLE)
            options = []
            if hierarchy is None:
                continue
            for contour, relation in zip(contours, hierarchy[0]):
                if relation[3] < 0:
                    continue
                size = cv2.contourArea(contour)
                perimeter = cv2.arcLength(contour, True)
                if not (4 * factor ** 2 <= size <= 100 * factor ** 2) or perimeter == 0:
                    continue
                bx, by, bw, bh = cv2.boundingRect(contour)
                if not (.72 <= bw / bh <= 1.38 and 4 * math.pi * size / perimeter ** 2 > .78):
                    continue
                boundary = contour.reshape(-1, 2)
                if np.mean(energy[boundary[:, 1], boundary[:, 0]] > 3) < .6:
                    continue
                moments = cv2.moments(contour)
                cx, cy = moments['m10'] / size, moments['m01'] / size
                if x <= cx <= x + w and y <= cy <= y + h:
                    options.append((size, cx, cy))
            if options:
                # 同帧若出现互相分开的圆孔，不能靠面积挑一个。
                largest = max(item[0] for item in options)
                significant = [item for item in options if item[0] >= largest * .8]
                if any(math.dist(a[1:], b[1:]) > 4 * factor for a in significant for b in significant):
                    continue
                _, cx, cy = max(options)
                centers.append((cx, cy))
        center = None
        # 呼吸最暗时内孔会破碎成小洞；采用多数帧的稳定圆心，不接受少数帧跳点。
        if len(centers) >= 3:
            median = np.median(centers, axis=0)
            stable = np.asarray(centers)[np.linalg.norm(np.asarray(centers) - median, axis=1) <= 2.5 * factor]
            if len(stable) >= max(3, math.ceil(len(centers) * .6)):
                refined = np.median(stable, axis=0)
                score = max(circle_support(energy * gold.any(axis=0), *refined, radius, factor)
                            for radius in range(4 * factor, 12 * factor + 1))
                # 内孔应位于检测到的脉动圆内部。出口箭头重叠时，Hough 圆心
                # 会偏移数像素；固定圆心距离会否决稳定内孔并选中偏移外圈。
                # 仍要求圆周时序支持，且拒绝圆外另一图例的小孔。
                if score >= 13 and (not arcs or any(math.dist(refined, arc[:2]) <= arc[2] for arc in arcs)):
                    center = refined
        if center is None and len(arcs) == 1:
            center = np.asarray(arcs[0][:2])
        if center is None:
            continue
        point = (float(center[0] + roi[0]), float(center[1] + roi[1]))
        if previous is None or math.dist(point, previous) <= max_distance:
            candidates.append(point)
    return candidates


def pulse_position(frames, roi=MINI_ROI, previous=None, max_distance=150, *, excluded=()):
    candidates = pulse_candidates(frames, roi, previous, max_distance)
    # 移动的金色羽毛也可能形成脉动圆，排除同帧已经识别的羽毛框。
    # 所有候选被排除或仍有多个候选时继续拒绝定位。
    candidates = [point for point in candidates if not any(
        x <= point[0] <= x+w and y <= point[1] <= y+h for x, y, w, h in excluded)]
    if len(candidates) != 1:
        raise LocalizationLost(f"呼吸环候选不唯一：{len(candidates)}")
    return candidates[0]


class MapAtlas:
    """一次整图采集的静态特征模型；每帧独立配准，误差不累计。"""

    def __init__(self, base, frames, name, position, excluded=()):
        from minimap_geometry import ContourAtlas, static_map_mask
        self.name = name
        self.image = np.median(frames, axis=0).astype(np.uint8)
        self.contours = ContourAtlas(base, self.image, position, excluded)
        self.excluded = []
        self.feature_scale = None
        self.detector = cv2.SIFT_create(nfeatures=1800, contrastThreshold=.02, edgeThreshold=12)
        # 道路/固定图例由同机位展开前后差分给出，排除场景纹理与角色环。
        delta = self.image.astype(np.float32) - base.astype(np.float32) * .5
        mask = (delta.min(axis=2) > 20).astype(np.uint8) * 255
        mask[:130] = mask[620:] = 0
        mask[:, :165] = mask[:, 1120:] = 0
        mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))
        mask *= static_map_mask(self.image, 2)
        cv2.circle(mask, tuple(map(round, position)), 46, 0, -1)
        for x, y in excluded:
            cv2.circle(mask, (round(x), round(y-18)), 28, 0, -1)
        image = cv2.resize(self.image, (640, 360), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (640, 360), interpolation=cv2.INTER_NEAREST)
        self.keypoints, self.descriptors = self.detector.detectAndCompute(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), mask)

    def register(self, frame, player):
        self.contours.excluded = self.excluded
        try:
            result = self.register_features(frame, player)
            # 特征路径已验证标准比例。后续运动才转入轮廓路径时，不能再要求
            # 新位置等于最初锚点，否则会把正常位移误判成比例校准失败。
            if self.contours.scale is None:
                self.contours.scale = self.feature_scale or 1.
            return result
        except LocalizationLost as feature_error:
            try:
                position, count, score, margin = self.contours.register(
                    crop(frame, MINI_ROI), np.asarray(player) - MINI_ROI[:2])
            except ValueError as exc:
                raise LocalizationLost(f'{feature_error}；{exc}') from exc
            scale = self.contours.scale * 2
            translation = np.asarray(position) - (np.asarray(player)-MINI_ROI[:2]) * scale
            transform = ((scale, 0., float(translation[0])), (0., scale, float(translation[1])))
            return Observation(position, count, None, 'contour', score, margin, transform)

    def register_features(self, frame, player):
        if self.descriptors is None or len(self.keypoints) < 12:
            raise LocalizationLost("整图静态特征不足")
        mini = crop(frame, MINI_ROI)
        from minimap_geometry import static_map_mask
        mask = static_map_mask(mini) * 255
        local = (round(player[0] - MINI_ROI[0]), round(player[1] - MINI_ROI[1]))
        cv2.circle(mask, local, 24, 0, -1)
        for x, y in self.excluded:
            cv2.circle(mask, (round(x), round(y-9)), 14, 0, -1)
        keypoints, descriptors = self.detector.detectAndCompute(
            cv2.cvtColor(mini, cv2.COLOR_BGR2GRAY), mask)
        if descriptors is None or len(descriptors) < 8:
            raise LocalizationLost("小地图静态特征不足")
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(descriptors, self.descriptors, k=2)
        matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < pair[1].distance * .72]
        # SIFT 可在同一点生成多个方向，不能将重复匹配计作独立证据。
        distinct = {}
        for match in sorted(matches, key=lambda item: item.distance):
            source = keypoints[match.queryIdx].pt
            target = self.keypoints[match.trainIdx].pt
            key = tuple(round(v / 3) for v in (*source, *target))
            distinct.setdefault(key, match)
        matches = list(distinct.values())
        if len(matches) < 8:
            raise LocalizationLost(f"小地图匹配不足：{len(matches)}")
        source = np.float32([keypoints[m.queryIdx].pt for m in matches])
        target = np.float32([self.keypoints[m.trainIdx].pt for m in matches])
        matrix, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                                     ransacReprojThreshold=1.8, maxIters=2000)
        if matrix is None or inliers is None:
            raise LocalizationLost("小地图几何匹配失败")
        keep = inliers.ravel().astype(bool)
        support = source[keep]
        scale = math.hypot(matrix[0, 0], matrix[1, 0])
        angle = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
        valid_scale = (.55 <= scale <= 1.25 if self.feature_scale is None else abs(scale-self.feature_scale) <= .02)
        if keep.sum() < 8 or keep.mean() < .35 or not valid_scale or angle > 1.2:
            raise LocalizationLost(f"小地图几何约束不符：inliers={keep.sum()}/{len(keep)} scale={scale:.3f} angle={angle:.2f}")
        cells = {(int(x // 45), int(y // 40)) for x, y in support}
        if len(cells) < 4 or np.ptp(support[:, 0]) < 65 or np.ptp(support[:, 1]) < 25:
            raise LocalizationLost("匹配集中在单一图例或直路，定位有歧义")
        predicted = source @ matrix[:, :2].T + matrix[:, 2]
        residual = float(np.sqrt(np.mean(np.sum((predicted[keep] - target[keep]) ** 2, axis=1))) * 2)
        point = (np.asarray(player) - MINI_ROI[:2]) @ matrix[:, :2].T + matrix[:, 2]
        if self.feature_scale is None:
            if math.dist(point*2, self.contours.anchor) > 7:
                raise LocalizationLost('特征比例校准与整图锚点不符')
            self.feature_scale = scale
        return Observation(tuple(map(float, point * 2)), int(keep.sum()), residual,
                           transform=tuple(tuple(map(float, row)) for row in matrix * 2))

    def observe(self, frames, previous=None, movement=None):
        accepted = []
        reason = '没有可确认的呼吸环'
        for player in pulse_candidates(frames):
            try:
                observations = [self.register(frame, player) for frame in frames[-2:]]
                if math.dist(observations[0].position, observations[1].position) > 3:
                    raise LocalizationLost("相邻帧的地图变换不一致")
                position = tuple(map(float, np.mean([o.position for o in observations], axis=0)))
                if previous is not None:
                    dx, dy = position[0] - previous[0], position[1] - previous[1]
                    x_limit = 70 if movement in ('left', 'right') else 12 if movement else 7
                    y_limit = 135 if movement in ('up', 'down') else 35 if movement else 7
                    if abs(dx) > x_limit or abs(dy) > y_limit:
                        raise LocalizationLost("小地图位置跳变超出单步范围")
                accepted.append(Observation(position, min(o.inliers for o in observations),
                                            max((o.residual for o in observations if o.residual is not None), default=None),
                                            observations[0].source if observations[0].source == observations[1].source else 'hybrid',
                                            min((o.score for o in observations if o.score is not None), default=None),
                                            min((o.margin for o in observations if o.margin is not None), default=None),
                                            tuple(map(tuple, np.mean([o.transform for o in observations], axis=0)))
                                            if all(o.transform is not None for o in observations) else None))
            except LocalizationLost as exc:
                reason = str(exc)
        if len(accepted) != 1:
            raise LocalizationLost(f"小地图定位候选 {len(accepted)}：{reason}")
        return accepted[0]


def parse_route(params):
    if not isinstance(params, dict) or not isinstance(params.get('map_name'), str) or not params['map_name'].strip():
        raise ValueError("需要 map_name 地图全名")
    points = params.get('waypoints')
    if not isinstance(points, list) or not 1 <= len(points) <= 16:
        raise ValueError("waypoints 需要 1～16 个已确认地图路点")
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or any(type(n) not in (int, float) for n in point):
            raise ValueError("路点必须是两个数值")
        if not (165 <= point[0] <= 1120 and 130 <= point[1] <= 620):
            raise ValueError("路点超出区域图范围")
    steps = params.get('max_steps', 60)
    if type(steps) is not int or not 1 <= steps <= 120:
        raise ValueError("max_steps 必须为 1～120")
    return params['map_name'].strip(), points, steps


class MiniMapNavigator:
    """复用现有控制器/道路规划的观察-移动闭环；低置信度时有界校准。"""

    def __init__(self, runner, map_name, *, aliases=None, road_key=None, exact=True, allow_full_map=False):
        from minimap_transitions import load_transitions
        self.runner = runner
        self.map_name = map_name
        self.aliases = tuple(aliases if aliases is not None else [map_name])
        self.exact = exact
        self.road_key = road_key
        self.allow_full_map = allow_full_map
        self.offset = (0., 0.)
        self.observation = None
        self.frames = []
        self.map_frames = []
        self.full_map_fallbacks = 0
        self.mini_calibration_failures = 0
        self.full_map_mode = False
        self.target_positions = []
        self.target_time = 0
        self.target_source = None
        self.atlas = None
        self.road = None
        self.position = None
        self.map_opens = 0
        self.mini_updates = 0
        self.recalibrations = 0
        self.consecutive_losses = 0
        self.last_calibration = 0
        self.last_audit_error = None
        self.last_map_position = None
        self.transitions = load_transitions(map_name) if map_name else []
        self.interactions = 0

    def burst(self, count=8):
        frames = []
        for _ in range(count):
            frame = self.runner.frame()
            if self.runner.navigation_interrupted(frame):
                raise NavigationInterrupted('地图采集被战斗打断')
            frames.append(frame)
            time.sleep(.075)
        return frames

    def accepts_name(self, name):
        from cat_diary import compact
        if not name:
            return False
        # 首次允许调用方已声明的后缀别名；建模之后严格锁定全名与楼层。
        if self.atlas is not None:
            return name == self.map_name
        return not self.aliases or any(name == compact(alias) if self.exact else
                                       (name.startswith(compact(alias)) or name.endswith(compact(alias)))
                                       for alias in self.aliases)

    def wait_map(self):
        until = min(self.runner.deadline, time.monotonic() + 10)
        while time.monotonic() < until:
            frame = self.runner.frame()
            if self.runner.navigation_interrupted(frame):
                raise NavigationInterrupted('展开地图被战斗打断')
            if self.runner.reco('NavigationLocalMap', frame):
                return
            time.sleep(.1)
        raise LocalizationLost('等待区域地图超时')

    def calibrate(self, audit=False):
        from cat_diary import RoadMap, compact
        nav = self.runner
        before = nav.world()
        if nav.navigation_interrupted(before):
            raise NavigationInterrupted('展开地图前场景已改变')
        epoch = nav.navigation_epoch
        nav.action('NavigationToggleLocalMap')
        self.map_opens += 1
        self.wait_map()
        frames = self.burst(10)
        if not nav.reco('NavigationLocalMap', frames[-1]):
            raise NavigationInterrupted('采集期间区域地图消失，先恢复主界面')
        name = read_map_name(nav, frames[-1], self.map_name)
        # 保留抗锯齿笔画，不对白色文字做硬二值化。错读或淡入时有界重采样，
        # 始终精确核对全名与楼层，不用模糊名称跨过地图身份检查。
        for _ in range(2):
            if self.accepts_name(name):
                break
            frames = self.burst(10)
            if not nav.reco('NavigationLocalMap', frames[-1]):
                raise NavigationInterrupted('重采样期间区域地图消失，先恢复主界面')
            name = read_map_name(nav, frames[-1], self.map_name)
        if not self.accepts_name(name):
            raise LocalizationLost(f"地图不符：预期 {self.map_name}，实际 {name}；保留现场")
        road_keys = [key for key in nav.maps if name == key or name.endswith(key)]
        road_key = self.road_key or (road_keys[0] if len(road_keys) == 1 else name)
        offset = map_offset(nav, frames[-1], road_key)
        marker = nav.reco('CatDiaryMarker', frames[-1])
        excluded = [match.box for match in marker.filtered_results] if marker else []
        screen_position = pulse_position(frames, MAP_ROI, excluded=excluded)
        position = tuple(a-b for a, b in zip(screen_position, offset))
        self.last_map_position = position
        if audit and self.position is not None:
            self.last_audit_error = math.dist(position, self.position)
            LOG.warning('MiniMap audit %s error=%.2f predicted=%s measured=%s', name,
                        self.last_audit_error, self.position, position)
            if self.last_audit_error > 8:
                raise LocalizationLost(f"终点整图核验误差过大：{self.last_audit_error:.1f}px；保留现场")
            # 到达复核只需独立整图坐标，尤其驻怪点不能为重建已知道路长留。
            nav.action('NavigationToggleLocalMap')
            nav.world()
            self.position = position
            self.observation = None
            return position
        nav.action('NavigationToggleLocalMap')
        # 传送后的主界面识别可能早于淡入结束。用展开图采集完成后的场景作
        # 差分基底，避免把较暗的传送帧与已经恢复亮度的地图相减而制造假路。
        base = nav.world()
        previous = cv2.resize(base[180:560], (160, 48)).astype(np.float32)
        stable = 0
        from minimap_geometry import background_stable
        for _ in range(12):
            time.sleep(.15)
            candidate = nav.world()
            current = cv2.resize(candidate[180:560], (160, 48)).astype(np.float32)
            stable = stable + 1 if background_stable(previous, current) else 0
            base, previous = candidate, current
            if stable >= 3:
                break
        else:
            raise LocalizationLost("场景亮度或机位仍在变化，停止建图")
        if nav.navigation_epoch != epoch:
            raise NavigationInterrupted('建模前后发生战斗，重新采集同一机位的整图与底图')
        # 开关地图时人物会改变姿态。两侧背景取较亮值，只有同时区别于两次
        # 场景的前景才作道路，剔除人物残影，也不受传送前帧偏暗影响。
        base = np.maximum(before, base)
        if road_key in nav.maps:
            road = RoadMap.from_segments(nav.maps[road_key], nav.horizontal_slopes.get(road_key, []))
        else:
            icons = nav.reco('CatDiaryMapIcons', frames[-1])
            boxes = [r.box for r in icons.filtered_results] if icons else []
            marker = nav.reco('CatDiaryMarker', frames[-1])
            boxes += [r.box for r in marker.filtered_results] if marker else []
            boxes.append([round(screen_position[0] - 40), round(screen_position[1] - 32), 80, 64])
            road = RoadMap(base, frames[-1], boxes, position)
            from minimap_roads import complete_corners
            road = complete_corners(road, boxes, position)
        if self.transitions:
            from minimap_transitions import add_landings
            road = add_landings(road, self.transitions)
        try:
            road.nearest(position)
        except RuntimeError:
            # 路端的角色环和邻近图例可能遮断本次差分道路。全名、机位偏移
            # 和本次独立整图坐标均须符合旧模型，才可复用此前确认的道路。
            # 传送/跨层会清空会话；首次建模没有旧道路时仍保留失败现场。
            if self.atlas is None or self.road is None or name != self.map_name or offset != self.offset:
                raise
            self.road.nearest(position)
            road = self.road
            LOG.warning('MiniMap reused confirmed road %s position=%s after occlusion', name, position)
        atlas = MapAtlas(base, frames, name, screen_position, feather_points(nav, frames[-1]))
        # 整图与小地图必须在同一机位交叉核验，避免接受另一组相似图例。
        self.frames = self.burst()
        atlas.excluded = feather_points(nav, self.frames[-1], True)
        try:
            initial = atlas.observe(self.frames, screen_position)
            if math.dist(initial.position, screen_position) > 7:
                raise LocalizationLost("整图与小地图初始位置不一致")
        except LocalizationLost as exc:
            if not self.allow_full_map:
                raise
            initial = None
            self.full_map_fallbacks += 1
            self.mini_calibration_failures += 1
            LOG.warning('MiniMap full-map observation used: %s', exc)
        if initial is not None:
            self.mini_calibration_failures = 0
        self.full_map_mode = self.mini_calibration_failures >= 3
        self.atlas, self.road = atlas, road
        self.offset, self.map_name, self.map_frames = offset, name, frames
        self.observation = initial
        if initial is not None and self.allow_full_map:
            self.consecutive_losses = 0
        self.position = tuple(a-b for a, b in zip(initial.position, offset)) if initial else position
        from minimap_transitions import load_transitions
        self.transitions = load_transitions(name)
        self.last_calibration = time.monotonic()
        LOG.warning('MiniMap calibrated %s position=%s inliers=%s', name, self.position, initial.inliers if initial else 0)
        return self.position

    def locate(self, movement=None):
        self.runner.world()
        # 极稀疏地图暂时按整图观测推进；仍由任务的步数、实际位移和时间
        # 上限约束。每次校准都会再尝试小图，恢复证据后自动退出此模式。
        if self.full_map_mode:
            return self.calibrate()
        # 校准失败保留整图现场，不再把身份错误当成一次小图失配来重复开关。
        if time.monotonic() - self.last_calibration > 45:
            return self.calibrate()
        try:
            return self.observe_only(movement)
        except LocalizationLost as exc:
            self.recalibrations += 1
            self.consecutive_losses += 1
            if not self.allow_full_map and self.recalibrations > 3:
                raise LocalizationLost(f"超过 3 次整图重定位：{exc}") from exc
            LOG.warning('MiniMap recalibrate: %s', exc)
            return self.calibrate()

    def observe_only(self, movement=None):
        """跨区域路段可先尝试小图；由调用方确认新的地图或无图连接路。"""
        self.frames = self.burst()
        self.atlas.excluded = feather_points(self.runner, self.frames[-1], True)
        screen_previous = tuple(a+b for a, b in zip(self.position, self.offset))
        result = self.atlas.observe(self.frames, screen_previous, movement)
        position = tuple(a-b for a, b in zip(result.position, self.offset))
        try:
            self.road.nearest(position, 16)
        except RuntimeError as exc:
            raise LocalizationLost(str(exc)) from exc
        self.position = position
        self.observation = result
        self.mini_updates += 1
        self.consecutive_losses = 0
        LOG.warning('MiniMap observed %s source=%s support=%s residual=%s score=%s margin=%s',
                    self.position, result.source, result.inliers, result.residual, result.score, result.margin)
        return self.position

    def cat_targets(self):
        """近处逐帧更新羽毛；视野外坐标仅作有时限的搜索路点。"""
        now = time.monotonic()
        if self.observation is not None:
            first, second = [feather_points(self.runner, frame, True) for frame in self.frames[-2:]]
            points = [project_point(self.observation, point, self.offset) for point in second
                      if any(math.dist(point, other) <= 4 for other in first)]
            if points:
                self.target_positions, self.target_time, self.target_source = points, now, 'minimap'
                return points
        # 刚展开的整图包含本轮最新目标；不能反复将旧地图帧当成新观测。
        if self.target_time < self.last_calibration:
            self.target_positions = [tuple(a-b for a, b in zip(point, self.offset))
                                     for point in feather_points(self.runner, self.map_frames[-1])]
            self.target_time, self.target_source = now, 'map'
            return self.target_positions
        # 视野外的目标可引导走向搜索区域；进入 45px 邻域、曾可见却丢失，
        # 或 20 秒仍未进入视野时，先刷新整图，不能用过期羽毛宣布到达。
        refresh = (self.target_source == 'minimap' or now-self.target_time > 20 or
                   any(math.dist(self.position, target) < 45 for target in self.target_positions))
        if refresh:
            self.calibrate()
            self.target_positions = [tuple(a-b for a, b in zip(point, self.offset))
                                     for point in feather_points(self.runner, self.map_frames[-1])]
            self.target_time, self.target_source = time.monotonic(), 'map'
        return self.target_positions

    def follow(self, waypoints, max_steps=60):
        from navigation import DIRECTIONS
        self.calibrate()
        steps = 0
        stalled = 0
        used_transitions = set()
        for target in waypoints:
            while math.dist(self.position, target) > 8:
                self.runner.check()
                if steps + self.interactions >= max_steps:
                    raise RuntimeError('小地图导航超过移动步数上限')
                try:
                    step = self.road.step(self.position, target)
                except RuntimeError:
                    from minimap_transitions import choose_transition, interact
                    transition = choose_transition(self.transitions, used_transitions, self.road, self.position, target)
                    if transition is None:
                        raise
                    index, edge = transition
                    if math.dist(self.position, edge['from']) > 10:
                        step = self.road.step(self.position, edge['from'])
                        if step is None:
                            raise RuntimeError('无法走到机关起点')
                    else:
                        interact(self.runner, edge)
                        used_transitions.add(index)
                        self.interactions += 1
                        # 机关可改变机位或地图，强制核对全名和实际落点再继续。
                        self.calibrate()
                        if math.dist(self.position, edge['to']) > 10:
                            raise RuntimeError('机关实际落点与已验证连接不符')
                        continue
                if step is None:
                    # RoadMap 到达容差是 10px，与实验入口一致，不再盲目微调。
                    if math.dist(self.position, target) > 10:
                        raise RuntimeError('道路投影无法到达指定路点')
                    break
                direction, duration = step
                previous = self.position
                dx, dy = DIRECTIONS[direction]
                self.runner.action('CatDiarySwipe', {'CatDiarySwipe': {
                    'begin': [200, 450], 'end': [200 + dx * 180, 450 + dy * 180],
                    'duration': duration, 'post_delay': 1500 if dy else 200,
                }})
                steps += 1
                self.locate(direction)
                if dy and abs(self.position[0] - target[0]) <= 10:
                    crossed = (previous[1] - target[1]) * (self.position[1] - target[1]) < 0
                    if crossed and abs(self.position[1] - target[1]) > 10:
                        raise RuntimeError('目标位于不可停留的换道连接路，请选择平台路点')
                displacement = (self.position[0] - previous[0]) * dx + (self.position[1] - previous[1]) * dy
                stalled = stalled + 1 if displacement < 3 else 0
                if stalled >= 3:
                    raise RuntimeError('连续三步未确认预期位移，停止小地图导航')
        # 到达仍由独立整图观测复核；不将路径投影或指令时长视作成功。
        self.calibrate(audit=True)
        if math.dist(self.last_map_position, waypoints[-1]) > 10:
            raise RuntimeError('终点整图复核未到达')
        LOG.warning('MiniMap complete steps=%s map_opens=%s mini_updates=%s recalibrations=%s',
                    steps, self.map_opens, self.mini_updates, self.recalibrations)
        return {'steps': steps, 'map_opens': self.map_opens, 'mini_updates': self.mini_updates,
                'recalibrations': self.recalibrations, 'interactions': self.interactions,
                'audit_error': self.last_audit_error}
