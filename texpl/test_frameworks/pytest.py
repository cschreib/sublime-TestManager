import os
import json
import logging
from typing import Dict, List, Optional

from ..test_framework import (TestFramework, register_framework)
from ..test_suite import TestSuite
from ..test_data import (DiscoveredTest, DiscoveryError, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

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
parser_logger = logging.getLogger('TestExplorerParser.pytest')


class OutputParser:
    def __init__(self, test_data: TestData, suite_id: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.suite_id = suite_id
        self.current_test: Optional[List[str]] = None
        self.current_status: Optional[TestStatus] = None

    def finish_current_test(self):
        if self.current_test is None:
            return
        if self.current_status is None:
            self.current_status = TestStatus.CRASHED
        self.test_data.notify_test_finished(FinishedTest(self.current_test, self.current_status))
        self.current_test = None
        self.current_status = None

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())
        if not line.startswith(PYTEST_STATUS_HEADER):
            return

        line = line.replace(PYTEST_STATUS_HEADER, '')
        data = json.loads(line)

        if data['status'] == 'started':
            self.finish_current_test()
            self.current_test = self.test_list.find_test_by_report_id(self.suite_id, 'pytest', data['test'])
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))
        elif data['status'] == 'finished':
            self.finish_current_test()
        elif data['status'] == 'output':
            if self.current_test is None:
                return
            self.test_data.notify_test_output(TestOutput(self.current_test, data['content']))
        else:
            if self.current_status is None:
                self.current_status = TestStatus.NOT_RUN
            self.current_status = TestStatus(max(self.current_status.value, PYTEST_STATUS_MAP[data['status']].value))

    def close(self):
        self.finish_current_test()


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


class PyTest(TestFramework):
    def __init__(self,
                 suite: TestSuite,
                 python: str = 'python',
                 env: Dict[str, str] = {},
                 cwd: Optional[str] = None,
                 args: List[str] = [],
                 discover_args: List[str] = [],
                 run_args: List[str] = [],
                 parser: str = 'default'):
        super().__init__(suite)
        self.python = python
        self.env = env
        self.cwd = cwd
        self.args = args
        self.discover_args = discover_args
        self.run_args = run_args
        self.parser = parser

    @staticmethod
    def from_json(suite: TestSuite, settings: Dict):
        assert settings['type'] == 'pytest'
        return PyTest(suite=suite,
                      python=settings.get('python', 'python'),
                      env=settings.get('env', {}),
                      cwd=settings.get('cwd', None),
                      args=settings.get('args', []),
                      discover_args=settings.get('discover_args', ['--collect-only']),
                      run_args=settings.get('run_args', []),
                      parser=settings.get('parser', 'default'))

    def get_pytest(self):
        if not os.path.isabs(self.python) and len(os.path.dirname(self.python)) > 0:
            python = os.path.join(self.project_root_dir, self.python)
        else:
            python = self.python

        return [python, '-m', 'pytest']

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
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        discover_args = self.get_pytest() + self.discover_args + self.args
        output = process.get_output(discover_args, env=env, cwd=cwd, success_codes=PYTEST_SUCCESS_CODES)
        return self.parse_discovery(output, cwd)

    def parse_discovered_test(self, test: Dict, working_directory: str):
        # This is where the test is defined.
        file = common.change_parent_dir(test['file'],
                                        old_cwd=working_directory,
                                        new_cwd=self.project_root_dir)

        # This is where the test was discovered.
        # This is usually the same as 'file', except when tests are imported.
        test_path = test['name'].split('::')
        discovery_file = common.change_parent_dir(test_path[0],
                                                  old_cwd=working_directory,
                                                  new_cwd=self.project_root_dir)
        test_path = test_path[1:]

        path = []

        if self.suite.custom_prefix is not None:
            path += self.suite.custom_prefix.split(TEST_SEPARATOR)

        path += common.get_file_prefix(discovery_file, path_prefix_style=self.suite.path_prefix_style)
        path += test_path

        run_id = test['name']
        report_id = run_id
        if self.parser == 'teamcity':
            components = test['name'].split('::')
            report_file, _ = os.path.splitext(components[0])
            report_id = '.'.join([report_file.replace('/', '.').replace('\\', '.')] + components[1:])
            report_id = report_id.replace('[', '(').replace(']', ')')

        return DiscoveredTest(
            full_name=path, suite_id=self.suite.suite_id, run_id=run_id, report_id=report_id,
            location=TestLocation(executable='pytest', file=file, line=test['line']))

    def parse_discovery(self, output: str, working_directory: str) -> List[DiscoveredTest]:
        for line in output.split('\n'):
            parser_logger.debug(line.rstrip())
            if PYTEST_DISCOVERY_HEADER in line:
                line = line.replace(PYTEST_DISCOVERY_HEADER, '')

                data = json.loads(line)
                if data['errors']:
                    raise DiscoveryError(
                        'Error when discovering tests. See panel for more information.', details=data['errors'])

                return [self.parse_discovered_test(t, working_directory) for t in data['tests']]

        raise DiscoveryError('Could not find test discovery data; pytest plugin compatibility issue?')

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        env = self.get_env()
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        assert len(grouped_tests) == 1
        test_ids = [test for tests in grouped_tests.values() for test in tests]

        parser = common.get_generic_parser(parser=self.parser,
                                           test_data=self.test_data,
                                           suite_id=self.suite.suite_id,
                                           executable='pytest')

        if parser is None:
            parser = OutputParser(self.test_data, self.suite.suite_id)

        run_args = self.get_pytest() + self.run_args + self.args + test_ids
        process.get_output_streamed(run_args,
                                    parser.feed, self.test_data.stop_tests_event,
                                    queue='pytest', ignore_errors=True, env=env, cwd=cwd)

        parser.close()


register_framework('pytest', PyTest.from_json)
