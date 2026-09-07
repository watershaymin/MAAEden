"""将独立 Windows 运行包封装为 Release ZIP 和 SHA256 校验文件。"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    'MFAAvalonia.exe', 'MFAAvalonia.dll', 'MFAAvalonia.runtimeconfig.json',
    'coreclr.dll', 'hostfxr.dll', 'python/python.exe', 'python/python312._pth',
    'python/Lib/site-packages/maa/__init__.py', 'agent/main.py',
    'resource/model/ocr/det.onnx', 'resource/model/ocr/rec.onnx', 'resource/model/ocr/keys.txt',
    'runtimes/win-x64/native/MaaFramework.dll', 'runtimes/win-x64/native/MaaAgentClient.dll',
    'interface.json', 'build-info.json', 'LICENSE', 'licenses/MFAAvalonia-GPL-3.0.txt',
    'licenses/gui-agent-temp.patch', 'licenses/SOURCES.txt', 'python/LICENSE.txt',
)
PRIVATE_DIRECTORIES = {'config', 'debug', 'logs', 'log', 'temp', 'backup', '.git'}


def include_file(relative):
    return (relative.parts[0].lower() not in PRIVATE_DIRECTORIES
            and '__pycache__' not in relative.parts
            and relative.suffix.lower() not in {'.pyc', '.log', '.pdb'})


def create_archive(package, output, version, expected_commit):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('版本号须为 vX.Y.Z，可带预发布后缀')
    missing = [name for name in REQUIRED_FILES if not (package / name).is_file()]
    if missing:
        raise ValueError(f'运行包缺少必要文件：{missing}')
    interface = json.loads((package / 'interface.json').read_text(encoding='utf-8'))
    manifest = json.loads((package / 'build-info.json').read_text(encoding='utf-8'))
    for actual in (interface['version'], manifest['project_version']):
        if f'v{actual.removeprefix("v")}' != version:
            raise ValueError('标签与运行包版本不一致')
    if manifest['project_commit'] != expected_commit:
        raise ValueError('运行包不是从当前发布提交构建的')
    if manifest['platform'] != 'win-x64' or not manifest['self_contained_dotnet']:
        raise ValueError('只支持自包含的 Windows x64 运行包')
    if interface['agent']['child_exec'] != '{PROJECT_DIR}/python/python.exe':
        raise ValueError('Agent 必须使用包内 Python')
    if output == package or output.is_relative_to(package):
        raise ValueError('压缩包输出目录不能放在运行包内')
    output.mkdir(parents=True, exist_ok=True)
    name = f'MAAEden-{version}-win-x64'
    archive = output / f'{name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(package.rglob('*')):
            relative = path.relative_to(package)
            if path.is_file() and include_file(relative):
                if path.is_symlink() or not path.resolve().is_relative_to(package):
                    raise ValueError(f'运行包不应包含外部链接：{relative}')
                bundle.write(path, f'{name}/{relative.as_posix()}')
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError('ZIP 完整性检查失败')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksum = archive.with_suffix('.zip.sha256')
    checksum.write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'{archive}\nSHA256: {digest}', flush=True)
    return archive, checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/artifacts')
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    create_archive(args.package.resolve(), args.output.resolve(), args.version, commit)
