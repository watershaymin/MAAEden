"""将已确认可跳过的副本目录同步到客户端选项。"""
import json
from copy import deepcopy
from collections import Counter
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / 'agent/data/dungeons.json').read_text(encoding='utf-8'))
    path = root / 'assets/interface.json'
    interface = json.loads(path.read_text(encoding='utf-8'))
    cases = []
    available = [v for v in catalog['dungeons'] if v.get('can_enter') and v.get('can_skip')]
    labels = Counter((v['name'], v['difficulty']) for v in available)
    route_options = {}
    for target in available:
        ticket = {'red':'红票', 'green':'绿票'}[target['ticket']]
        name = target['name']
        if labels[(name, target['difficulty'])] > 1:
            name += '（' + ' → '.join(target['path'][:-1]) + '）'
        cases.append({
            'name':target['id'],
            'label':f"{name} / {target['difficulty']} / {ticket} ×{target['ticket_cost']}",
            'pipeline_override':{'DungeonSkip':{'custom_action_param':{'target':target['id']}}},
        })
        if target.get('skip_routes'):
            option_id = 'DungeonRoute_' + target['id']
            cases[-1]['option'] = [option_id]
            route_options[option_id] = {
                'type': 'select', 'label': target['name'] + ' · 扫荡路线',
                'default_case': target['default_route'],
                'cases': [{
                    'name': route['id'], 'label': route['name'],
                    'pipeline_override': {'DungeonSkip': {'custom_action_param': {
                        'routes': {target['id']: route['id']},
                    }}},
                } for route in target['skip_routes']],
            }
    if not cases or len({v['name'] for v in cases}) != len(cases):
        raise ValueError('可用副本为空或标识重复')
    option = interface['option']['DungeonTarget']
    if option['default_case'] not in {v['name'] for v in cases}:
        raise ValueError('默认副本不在可用目录中')
    option['cases'] = cases
    # 保留旧选项标识，已保存的单副本配置继续生成 target/count。
    for ticket, label, default in [('red', '红票', 'snake_damak_vh'),
                                   ('green', '绿票', 'moon_forest_h')]:
        prefix = 'Dungeon' + ticket.title()
        filtered = deepcopy([case for case, target in zip(cases, available) if target['ticket'] == ticket])
        if default not in {case['name'] for case in filtered}:
            raise ValueError(f'{label}默认副本不在可用目录中')
        for case in filtered:
            case['pipeline_override']['DungeonSkip']['custom_action_param'] = {ticket + '_target': case['name']}
        interface['option'][prefix + 'Target'] = {
            'type': 'select', 'label': label + '副本', 'default_case': default, 'cases': filtered,
        }
        interface['option'][prefix + 'Count'] = {
            'type': 'input', 'label': label + '每次运行跳过次数（0 为不执行）',
            'inputs': [{
                'name': 'count', 'label': '跳过场数', 'default': '4', 'pipeline_type': 'int',
                'verify': '^(0|[1-9][0-9]{0,2})$', 'pattern_msg': '请输入 0～999 的整数，0 表示不执行',
            }],
            'pipeline_override': {'DungeonSkip': {'custom_action_param': {ticket + '_count': '{count}'}}},
        }
    interface['option'].update(route_options)
    # Maa 5.12.3 对 custom_action_param 整块覆盖；不同界面项必须有独立的参数载体。
    # attach 是 Pipeline 的自定义数据字段，由 DungeonSkip 在运行时统一读取。
    pipeline_path = root / 'assets/resource/pipeline/dungeons.json'
    pipeline = json.loads(pipeline_path.read_text(encoding='utf-8'))
    pipeline['DungeonSkip']['custom_action_param']['use_interface_options'] = True
    for name, option in interface['option'].items():
        node_name = 'DungeonSkipOption_' + name
        items = [option, *option.get('cases', [])]
        carries_params = False
        for item in items:
            override = item.get('pipeline_override', {})
            if 'DungeonSkip' in override:
                node = override['DungeonSkip']
                if set(node) != {'custom_action_param'}:
                    raise ValueError(f'{name} 包含副本参数之外的覆盖，不能转换')
                override[node_name] = {'attach': node['custom_action_param']}
                del override['DungeonSkip']
            carries_params |= node_name in override
        if carries_params:
            pipeline[node_name] = {'action': 'DoNothing', 'attach': {}}
    pipeline_path.write_text(json.dumps(pipeline, ensure_ascii=False, indent=4) + '\n', encoding='utf-8', newline='\n')
    path.write_text(json.dumps(interface, ensure_ascii=False, indent=4) + '\n', encoding='utf-8', newline='\n')
    print(f'已同步 {len(cases)} 个可跳过副本选项。')


if __name__ == '__main__':
    main()
