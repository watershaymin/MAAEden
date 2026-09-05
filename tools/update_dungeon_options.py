"""将已确认可跳过的副本目录同步到客户端选项。"""
import json
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
    if not cases or len({v['name'] for v in cases}) != len(cases):
        raise ValueError('可用副本为空或标识重复')
    option = interface['option']['DungeonTarget']
    if option['default_case'] not in {v['name'] for v in cases}:
        raise ValueError('默认副本不在可用目录中')
    option['cases'] = cases
    path.write_text(json.dumps(interface, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
    print(f'已同步 {len(cases)} 个可跳过副本选项。')


if __name__ == '__main__':
    main()
