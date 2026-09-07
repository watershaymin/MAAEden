"""检查发布包的完整性、版本约束与个人配置排除。"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from create_release import REQUIRED_FILES, create_archive


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.package = self.root / 'package'
        self.output = self.root / 'artifacts'
        for name in REQUIRED_FILES:
            self.write(name, 'fixture')
        self.write('interface.json', json.dumps({
            'version': '1.0.0', 'agent': {'child_exec': '{PROJECT_DIR}/python/python.exe'},
        }))
        self.manifest = {'project_version': '1.0.0', 'project_commit': 'a' * 40,
                         'platform': 'win-x64', 'self_contained_dotnet': True}
        self.write('build-info.json', json.dumps(self.manifest))

    def write(self, name, value):
        path = self.package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def archive(self, version='v1.0.0'):
        return create_archive(self.package, self.output, version, 'a' * 40)

    def test_complete_archive_excludes_personal_files_and_has_valid_checksum(self):
        for name in ('config/user.json', 'debug/capture.png', 'logs/run.txt', 'temp/agent.tmp',
                     'backup/config.json', 'agent/__pycache__/main.pyc', 'nested/run.log'):
            self.write(name, 'personal')
        archive, checksum = self.archive()
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(len(bundle.namelist()), len(REQUIRED_FILES))
            self.assertIsNone(bundle.testzip())
        self.assertEqual(checksum.read_text().split()[0], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_missing_runtime_rejected(self):
        (self.package / 'coreclr.dll').unlink()
        with self.assertRaisesRegex(ValueError, '缺少必要文件'):
            self.archive()

    def test_tag_must_match_package(self):
        with self.assertRaisesRegex(ValueError, '版本不一致'):
            self.archive('v1.0.1')

    def test_stale_build_rejected(self):
        self.manifest['project_commit'] = 'b' * 40
        self.write('build-info.json', json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, '当前发布提交'):
            self.archive()

    def test_cannot_archive_inside_package(self):
        self.output = self.package / 'artifacts'
        with self.assertRaisesRegex(ValueError, '不能放在运行包内'):
            self.archive()


if __name__ == '__main__':
    unittest.main()
