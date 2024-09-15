import os
import json
import logging
from typing import Dict, List, Optional

from ..test_framework import TestFramework, register_framework
from ..test_data import DiscoveredTest, DiscoveryError, TestLocation, TestData, StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, status_merge
from ..cmd import Cmd

PYTEST_PLUGIN_PATH = 'pytest_plugins'
PYTEST_PLUGIN = 'sublime_test_runner'
PYTEST_DISCOVERY_HEADER = 'SUBLIME_DISCOVERY: '
PYTEST_STATUS_HEADER = 'SUBLIME_STATUS: '

# Pytest returns 5 if no test was found.
PYTEST_SUCCESS_CODES = [0, 5]

PYTEST_STATUS_MAP = {
    'passed': TestStatus.PASSED,
    'failed': TestStatus.FAILED,
    'skipped': TestStatus.SKIPPED
}

logger = logging.getLogger('TestExplorer.pytest')
parser_logger = logging.getLogger('TestExplorerParser.gtest')


class OutputParser:
    def __init__(self, test_data: TestData, framework: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.current_test: Optional[List[str]] = None
        self.current_status: Optional[TestStatus] = None

    def feed(self, line: str):
        parser_logger.debug(line.strip())
        if not line.startswith(PYTEST_STATUS_HEADER):
            return

        line = line.replace(PYTEST_STATUS_HEADER, '')
        data = json.loads(line)

        if data['status'] == 'started':
            self.current_test = self.test_list.find_test_by_run_id(self.framework, data['test'])
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))
        elif data['status'] == 'finished':
            if self.current_test is None:
                return
            if self.current_status is None:
                self.current_status = TestStatus.SKIPPED
            self.test_data.notify_test_finished(FinishedTest(self.current_test, self.current_status))
            self.current_test = None
            self.current_status = None
        else:
            self.current_status = status_merge(self.current_status, PYTEST_STATUS_MAP[data['status']])


def get_os_python_path():
    python_path = os.environ.get('PYTHONPATH')
    if not python_path:
        return []

    return python_path.split(os.pathsep)


def get_os_pytest_plugins():
    plugins = os.environ.get('PYTEST_PLUGINS')
    if not plugins:
        return []

    return plugins.split(',')


class PyTest(TestFramework, Cmd):
    def __init__(self, test_data: TestData,
                       project_root_dir: str,
                       framework_id: str = '',
                       python: str = 'python',
                       env: Dict[str,str] = {},
                       cwd: Optional[str] = None,
                       args: List[str] = [],
                       path_prefix_style: str = 'full',
                       custom_prefix: Optional[str] = None):
        super().__init__(test_data, project_root_dir)
        self.test_data = test_data
        self.framework_id = framework_id
        self.python = python
        self.env = env
        self.cwd = cwd
        self.args = args
        self.path_prefix_style = path_prefix_style
        self.custom_prefix = custom_prefix

    @staticmethod
    def from_json(test_data: TestData, project_root_dir: str, json_data: Dict):
        assert json_data['type'] == 'pytest'
        return PyTest(test_data=test_data,
                      project_root_dir=project_root_dir,
                      framework_id=json_data['id'],
                      python=json_data.get('python', 'python'),
                      env=json_data.get('env', {}),
                      cwd=json_data.get('cwd', None),
                      args=json_data.get('args', []),
                      path_prefix_style=json_data.get('path_prefix_style', 'full'),
                      custom_prefix=json_data.get('custom_prefix', None))

    def get_id(self):
        return self.framework_id

    def get_working_directory(self):
        # Set up current working directory. Default to the project root dir.
        if self.cwd is not None:
            cwd = self.cwd
            if not os.path.isabs(cwd):
                cwd = os.path.join(self.project_root_dir, cwd)
        else:
            cwd = self.project_root_dir

        return cwd

    def get_env(self):
        # Default discovery output of pytest does not contain file & line numbers.
        # We can import our own pytest plugin to fill the gap.
        env = self.env.copy()
        env['PYTEST_PLUGINS'] = ','.join(get_os_pytest_plugins() + [PYTEST_PLUGIN])
        here_path = os.path.dirname(os.path.abspath(__file__))
        plugin_path = os.path.join(here_path, PYTEST_PLUGIN_PATH)
        env['PYTHONPATH'] = os.pathsep.join(get_os_python_path() + [plugin_path])
        return env

    def discover(self) -> List[DiscoveredTest]:
        env = self.get_env()
        cwd = self.get_working_directory()

        discover_args = [self.python, '-m', 'pytest', '--collect-only', '-q']
        lines = self.cmd_lines(discover_args + self.args, env=env, cwd=cwd, success_codes=PYTEST_SUCCESS_CODES)
        return self.parse_discovery(lines, cwd)

    def parse_discovered_test(self, test: Dict, working_directory: str):
        # Make file path relative to project directory.
        file = os.path.relpath(os.path.join(working_directory, test['file']), start=self.project_root_dir)

        # Make full name relative to project directory.
        # NB: the 'discovery_file' here points to the file where the test was discovered.
        # The 'file' variable above points to the file where the test is defined.
        # They are usually the same, except when tests are imported.
        path = test['name'].split('::')
        discovery_file = path[0]
        discovery_file = os.path.normpath(os.path.relpath(os.path.join(working_directory, discovery_file), start=self.project_root_dir))

        path = path[1:]

        if self.path_prefix_style == 'full':
            path = discovery_file.split(os.sep) + path
        elif self.path_prefix_style == 'basename':
            path = [os.path.basename(discovery_file)] + path
        elif self.path_prefix_style == 'none':
            pass

        if self.custom_prefix is not None:
            path = self.custom_prefix.split(TEST_SEPARATOR) + path

        return DiscoveredTest(
            full_name=path, framework_id=self.framework_id, run_id=test['name'],
            location=TestLocation(executable=discovery_file, file=file, line=test['line']))

    def parse_discovery(self, lines: List[str], working_directory: str) -> List[DiscoveredTest]:
        for line in lines:
            if PYTEST_DISCOVERY_HEADER in line:
                line = line.replace(PYTEST_DISCOVERY_HEADER, '')

                data = json.loads(line)
                if data['errors']:
                    raise DiscoveryError('Error when discovering tests. See panel for more information.', details=data['errors'])

                return [self.parse_discovered_test(t, working_directory) for t in data['tests']]

        raise DiscoveryError('Could not find test discovery data; pytest plugin compatibility issue?')

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        env = self.get_env()
        cwd = self.get_working_directory()

        run_args = [self.python, '-m', 'pytest'] + [test for tests in grouped_tests.values() for test in tests]

        parser = OutputParser(self.test_data, self.framework_id)

        self.cmd_streamed(run_args + self.args, parser.feed,
            queue='pytest', ignore_errors=True, env=env, cwd=cwd)


register_framework('pytest', PyTest.from_json)
