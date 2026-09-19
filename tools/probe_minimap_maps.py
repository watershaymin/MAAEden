"""实机小地图扩图验证。capture 仅采集，run 使用已标定目标，结果逐次写入独立目录。"""

import argparse
import hashlib
from importlib.metadata import version
import json
import logging
import math
from pathlib import Path
import sys
import time
import traceback

import cv2
import numpy as np
from maa.controller import AdbController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from cat_diary import CatDiaryRunner, RoadMap, compact
from minimap_navigation import MAP_ROI, MiniMapNavigator, parse_route, pulse_position


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['capture', 'run'])
    parser.add_argument('--case', required=True, help='含 entry_id/map_name/waypoints 的 JSON 文件')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--address', default='127.0.0.1:16384')
    travel = parser.add_mutually_exclusive_group()
    travel.add_argument('--teleport', action='store_true', help='run 前重新传送；capture 默认传送')
    travel.add_argument('--current', action='store_true', help='采集当前已经进入的地图，不传送')
    args = parser.parse_args()
    case = json.loads(Path(args.case).read_text(encoding='utf-8-sig'))
    if args.phase == 'run':
        parse_route(case)
    if (args.output / 'result.json').exists():
        parser.error('输出目录已有测试记录，请选择新的目录')
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)
    Toolkit.init_option(args.output / 'maa')
    devices = [d for d in Toolkit.find_adb_devices() if d.address == args.address]
    if len(devices) != 1:
        raise RuntimeError('ADB 设备不唯一或未找到')
    device = devices[0]
    controller = AdbController(device.adb_path, device.address, screencap_methods=device.screencap_methods,
                               input_methods=device.input_methods, config=device.config)
    assert controller.post_connection().wait().succeeded
    controller.set_screenshot_target_short_side(720)
    resource = Resource()

    class Probe(CustomAction):
        def run(self, context, argv):
            nav = CatDiaryRunner(context, max_minutes=6)
            began = time.monotonic()
            report = dict(case, phase=args.phase, status='running')
            report['environment'] = {
                'maafw': version('maafw'), 'opencv': cv2.__version__,
                'device': args.address, 'scaled_resolution': [1280, 720],
                'navigation_sha256': hashlib.sha256((ROOT / 'agent/minimap_navigation.py').read_bytes()).hexdigest(),
                'module_sha256': {name: hashlib.sha256((ROOT / 'agent' / name).read_bytes()).hexdigest()
                                  for name in ('minimap_navigation.py', 'minimap_geometry.py',
                                               'minimap_roads.py', 'minimap_transitions.py', 'cat_diary.py')},
                'transitions_sha256': hashlib.sha256((ROOT / 'agent/data/minimap_transitions.json').read_bytes()).hexdigest(),
            }
            counter = 0
            session = None
            movement_count = 0
            original_action = nav.action
            def action(name, *arguments, **keywords):
                nonlocal movement_count
                result = original_action(name, *arguments, **keywords)
                if name == 'CatDiarySwipe':
                    movement_count += 1
                return result
            nav.action = action
            def save_report():
                (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            def burst(count=8):
                nonlocal counter
                frames = []
                for _ in range(count):
                    frames.append(nav.frame())
                    time.sleep(.075)
                # 原始无损局部序列用于失败重放；完整首尾图用于人工核验。
                seq = np.asarray(frames)
                np.savez_compressed(args.output / f'sequence-{counter:02d}.npz',
                                    mini=seq[:, 20:175, 1020:1262],
                                    large=seq[:, 130:620, 165:1120] if count == 10 else np.empty(0, np.uint8))
                cv2.imwrite(str(args.output / f'frame-{counter:02d}.png'), frames[-1])
                counter += 1
                return frames
            save_report()
            try:
                frame = nav.frame()
                if nav.reco('NavigationLocalMap', frame):
                    nav.action('NavigationToggleLocalMap')
                elif nav.reco('CatDiaryWorldMap', frame):
                    nav.action('CatDiaryClose')
                if not args.current and (args.phase == 'capture' or args.teleport):
                    entry = next(e for e in nav.catalog if e['id'] == case['entry_id'])
                    entry = dict(entry, **case.get('teleport_override', {}))
                    nav.teleport(entry)
                base = nav.world()
                cv2.imwrite(str(args.output / 'start.png'), base)
                if args.phase == 'capture':
                    nav.action('NavigationToggleLocalMap')
                    nav.wait('NavigationLocalMap')
                    frames = burst(10)
                    name = compact(nav.text('NavigationMapName', frames[-1], single_line=True))
                    for _ in range(2):
                        if name:
                            break
                        frames = burst(10)
                        name = compact(nav.text('NavigationMapName', frames[-1], single_line=True))
                    report['map_name'] = name
                    cv2.imwrite(str(args.output / 'map.png'), frames[-1])
                    report['start_position'] = pulse_position(frames, MAP_ROI)
                    icons = nav.reco('CatDiaryMapIcons', frames[-1])
                    boxes = [r.box for r in icons.filtered_results] if icons else []
                    px, py = report['start_position']
                    boxes.append([round(px - 40), round(py - 32), 80, 64])
                    road = RoadMap(base, frames[-1], boxes, (px, py))
                    preview = frames[-1].copy()
                    ys, xs = np.where(road.grid)
                    preview[ys * 4 + 2, xs * 4 + 2] = [40, 240, 60]
                    cv2.circle(preview, (round(px), round(py)), 10, (0, 0, 255), 2)
                    cv2.imwrite(str(args.output / 'roads.png'), preview)
                    # 只报告候选供标定，不自动将最远像素视作可达目标。
                    candidates = []
                    for x, y in zip(xs[::12] * 4 + 2, ys[::12] * 4 + 2):
                        if 100 <= math.dist((x, y), (px, py)) <= 280:
                            try:
                                path = road.path((px, py), (int(x), int(y)))
                                if 26 <= len(path) <= 110:
                                    candidates.append((len(path), int(x), int(y)))
                            except RuntimeError:
                                pass
                    report['candidate_targets'] = sorted(candidates, reverse=True)[::max(1, len(candidates) // 8)][:8]
                    nav.action('NavigationToggleLocalMap')
                    nav.world()
                else:
                    session = MiniMapNavigator(nav, case['map_name'])
                    session.burst = burst
                    if case.get('segments'):
                        nav.maps[compact(case['map_name'])] = case['segments']
                    metrics = session.follow(case['waypoints'], case.get('max_steps', 40))
                    report.update(metrics)
                    report['final_position'] = session.last_map_position
                    report['target_error'] = math.dist(session.last_map_position, case['waypoints'][-1])
                report['status'] = 'passed'
                return True
            except Exception as exc:
                report.update(status='failed', error=str(exc))
                traceback.print_exc()
                return False
            finally:
                if session is not None:
                    report.update(steps=movement_count, map_opens=session.map_opens,
                                  mini_updates=session.mini_updates,
                                  recalibrations=session.recalibrations,
                                  interactions=session.interactions,
                                  last_position=session.position,
                                  last_map_position=session.last_map_position,
                                  audit_error=session.last_audit_error)
                report['elapsed_seconds'] = round(time.monotonic() - began, 2)
                save_report()
                cv2.imwrite(str(args.output / 'final.png'), controller.post_screencap().wait().get())
                print(json.dumps(report, ensure_ascii=False), flush=True)

    resource.register_custom_action('MiniMapSurvey', Probe())
    assert resource.post_bundle(ROOT / 'assets/resource').wait().succeeded
    tasker = Tasker()
    assert tasker.bind(resource, controller)
    job = tasker.post_task('MiniMapSurvey', {'MiniMapSurvey': {'action': 'Custom', 'custom_action': 'MiniMapSurvey'}})
    try:
        job.wait()
    except KeyboardInterrupt:
        tasker.post_stop().wait()
        return 130
    return 0 if job.succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
