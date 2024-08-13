import os
import logging
import glob
import json
from typing import Dict, List, Optional
from tempfile import TemporaryDirectory

from ..list import TEST_SEPARATOR
from ..test_framework import TestFramework, register_framework
from ..test_data import DiscoveredTest, DiscoveryError, TestLocation
from ..cmd import Cmd

logger = logging.getLogger('TestExplorer.gtest')

class GoogleTest(TestFramework, Cmd):
    def __init__(self, executable_pattern: str = '*',
                       env: Dict[str,str] = {},
                       cwd: Optional[str] = None,
                       args: List[str] = [],
                       path_prefix_style: str = 'full',
                       custom_prefix: Optional[str] = None):
        self.executable_pattern = executable_pattern
        self.env = env
        self.cwd = cwd
        self.args = args
        self.path_prefix_style = path_prefix_style
        self.custom_prefix = custom_prefix

    @staticmethod
    def from_json(json_data: Dict):
        assert json_data['type'] == 'catch2'
        return GoogleTest(executable_pattern=json_data.get('executable_pattern', '*'),
                      env=json_data.get('env', {}),
                      cwd=json_data.get('cwd', None),
                      args=json_data.get('args', []),
                      path_prefix_style=json_data.get('path_prefix_style', 'full'),
                      custom_prefix=json_data.get('custom_prefix', None))

    def get_current_working_directory(self, project_root_dir: str):
        # Set up current working directory. Default to the project root dir.
        if self.cwd is not None:
            cwd = self.cwd
            if not os.path.isabs(cwd):
                cwd = os.path.join(project_root_dir, cwd)
        else:
            cwd = project_root_dir

        return cwd

    def discover(self, project_root_dir: str) -> List[DiscoveredTest]:
        cwd = self.get_current_working_directory(project_root_dir)

        errors = []
        tests = []

        with TemporaryDirectory() as temp_dir:
            def run_discovery(executable):
                output_file = os.path.join(temp_dir, 'output.json')
                discover_args = [executable, f'--gtest_output=json:{output_file}', '--gtest_list_tests']
                self.cmd_string(discover_args + self.args, env=self.env, cwd=cwd)
                try:
                    return self.parse_discovery(output_file, executable, project_root_dir)
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

    def parse_discovered_test(self, test: dict, suite: str, executable: str, project_directory: str):
        # Make file path relative to project directory.
        file = os.path.relpath(test['file'], start=project_directory)
        line = test['line']

        path = []

        if self.custom_prefix is not None:
            path += self.custom_prefix.split(TEST_SEPARATOR)

        if self.path_prefix_style == 'full':
            path += os.path.normpath(executable).split(os.sep)
        elif self.path_prefix_style == 'basename':
            path.append(os.path.basename(executable))
        elif self.path_prefix_style == 'none':
            pass

        if 'type_param' in test:
            suite = '/'.join(suite.split('/')[:-1]) + f'<{test["type_param"]}>'

        name = test['name']

        if 'value_param' in test:
            name = '/'.join(name.split('/')[:-1]) + f'[{test["value_param"]}]'

        path += [suite, name]

        return DiscoveredTest(full_name=path, location=TestLocation(file=file, line=line))

    def parse_discovery(self, output_file: str, executable: str, project_directory: str) -> List[DiscoveredTest]:
        with open(output_file, 'r') as f:
            data = json.load(f)

        tests = []
        for suite in data['testsuites']:
            for test in suite['testsuite']:
                tests.append(self.parse_discovered_test(test, suite['name'], executable, project_directory))

        return tests

register_framework('gtest', GoogleTest.from_json)
