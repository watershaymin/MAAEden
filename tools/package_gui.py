"""将已编译的 MFAAvalonia 与资源、独立 Python Agent 组成 Windows 运行包。"""
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
GUI_COMMIT = '4f11c8122de4f43eafc818a368c9956e3b06249c'


def package(output):
    if not (output / 'MFAAvalonia.exe').is_file():
        raise RuntimeError('请先使用 build_gui.ps1 编译 MFAAvalonia')
    archive = ROOT / 'deps/python-3.12.10-embed-amd64.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise RuntimeError('Python 压缩包 SHA256 不匹配')
    for filename in ('det.onnx', 'rec.onnx', 'keys.txt'):
        if not (ROOT / 'assets/resource/model/ocr' / filename).is_file():
            raise RuntimeError(f'缺少 OCR 文件：{filename}')
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.log')
    for directory in ('agent', 'assets/resource'):
        shutil.copytree(ROOT / directory, output / Path(directory).name, dirs_exist_ok=True, ignore=ignore)
    runtime = output / 'python'
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(runtime)
    shutil.copytree(ROOT / 'deps/gui-python-packages', runtime / 'Lib/site-packages', dirs_exist_ok=True, ignore=ignore)
    (runtime / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../agent\nimport site\n', encoding='utf-8')
    interface = json.loads((ROOT / 'assets/interface.json').read_text(encoding='utf-8'))
    interface['agent']['child_exec'] = '{PROJECT_DIR}/python/python.exe'
    interface['agent']['child_args'] = ['-X', 'utf8', '{PROJECT_DIR}/agent/main.py']
    (output / 'interface.json').write_text(json.dumps(interface, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
    for name in ('README.md', 'LICENSE', 'rules.md'):
        shutil.copy2(ROOT / name, output / name)
    shutil.copytree(ROOT / 'docs/zh_cn/develop', output / 'docs/zh_cn/develop', dirs_exist_ok=True, ignore=ignore)
    notices = output / 'licenses'
    notices.mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'deps/MFAAvalonia/LICENSE', notices / 'MFAAvalonia-GPL-3.0.txt')
    shutil.copy2(ROOT / 'tools/patches/gui-agent-temp.patch', notices / 'gui-agent-temp.patch')
    (notices / 'SOURCES.txt').write_text(
        f'MFAAvalonia v2.16.1 + local Agent temp fix, GPL-3.0\nhttps://github.com/MaaXYZ/MFAAvalonia/tree/{GUI_COMMIT}\n'
        'Local changes: gui-agent-temp.patch (apply with git apply before building)\n'
        'Python 3.12.10, PSF license: ../python/LICENSE.txt\n'
        'Python package licenses: ../python/Lib/site-packages/*dist-info/\n', encoding='utf-8')
    manifest = {'gui':'MFAAvalonia v2.16.1', 'gui_commit':GUI_COMMIT, 'framework':'5.12.3',
                'python':'3.12.10', 'platform':'win-x64', 'self_contained_dotnet':True,
                'gui_patches':['gui-agent-temp.patch'],
                'project_commit':subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()}
    (output / 'build-info.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'运行包已生成：{output / "MFAAvalonia.exe"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'install')
    package(parser.parse_args().output.resolve())
