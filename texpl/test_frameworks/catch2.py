import os
import json
import logging
import glob
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..test_framework import TestFramework, register_framework
from ..test_data import DiscoveredTest, DiscoveryError, TestLocation
from ..cmd import Cmd

logger = logging.getLogger('TestExplorer.catch2')

class Catch2(TestFramework, Cmd):
    def __init__(self, executable_pattern: str = '*', env: Dict[str,str] = {}, cwd: Optional[str] = None, args: List[str] = []):
        self.executable_pattern = executable_pattern
        self.env = env
        self.cwd = cwd
        self.args = args

    @staticmethod
    def from_json(json_data: Dict):
        assert json_data['type'] == 'catch2'
        return Catch2(executable_pattern=json_data.get('executable_pattern', '*'),
                      env=json_data.get('env', {}),
                      cwd=json_data.get('cwd', None),
                      args=json_data.get('args', []))

    def discover(self, project_root_dir: str) -> List[DiscoveredTest]:
        # Set up current working directory. Default to the project root dir.
        if self.cwd is not None:
            cwd = self.cwd
            if not os.path.isabs(cwd):
                cwd = os.path.join(project_root_dir, cwd)
        else:
            cwd = project_root_dir

        errors = []
        tests = []

        def run_discovery(executable):
            discover_args = [executable, '-r', 'xml', '--list-tests']
            output = self.cmd_string(discover_args + self.args, env=self.env, cwd=cwd)
            try:
                return self.parse_discovery(output, executable, cwd, project_root_dir)
            except DiscoveryError as e:
                errors.append(e.details if e.details else str(e))
                return []

        if '*' in self.executable_pattern:
            for executable in glob.glob(self.executable_pattern):
                tests += run_discovery(executable)
        else:
            tests += run_discovery(self.executable_pattern)

        if errors:
            raise DiscoveryError('Error when discovering tests. See panel for more information', details=errors)

        return tests

    def parse_discovered_test(self, test: ET.Element, executable: str, working_directory: str, project_directory: str):
        # Make file path relative to project directory.
        location = test.find('SourceInfo')
        assert location is not None

        file = location.find('File')
        assert file is not None
        file = file.text
        assert file is not None

        file = os.path.relpath(file, start=project_directory)

        line = location.find('Line')
        assert line is not None
        line = line.text
        assert line is not None

        path = os.path.normpath(executable).split(os.sep)
        fixture = test.find('ClassName')
        if fixture and fixture.text:
            path.append(fixture.text)

        name = test.find('Name')
        assert name is not None
        name = name.text
        assert name is not None

        path.append(name)

        return DiscoveredTest(full_name=path, location=TestLocation(file=file, line=int(line)))

    def parse_discovery(self, output: str, executable: str, working_directory: str, project_directory: str) -> List[DiscoveredTest]:
        tests = []
        for t in ET.fromstring(output):
            if t.tag == 'TestCase':
                tests.append(self.parse_discovered_test(t, executable, working_directory, project_directory))

        return tests

register_framework('catch2', Catch2.from_json)
