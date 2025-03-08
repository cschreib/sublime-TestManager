import os
import logging
import glob
import json
from typing import Dict, List, Optional
from tempfile import TemporaryDirectory

from ..test_framework import (TestFramework, register_framework)
from ..test_data import (DiscoveredTest, DiscoveryError, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

logger = logging.getLogger('TestExplorer.gtest')
parser_logger = logging.getLogger('TestExplorerParser.gtest')


class OutputParser:
    def __init__(self, test_data: TestData, framework: str, executable: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.executable = executable
        self.current_test: Optional[List[str]] = None

    def parse_test_id(self, line: str):
        return line[12:].strip().split(' ')[0]

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())

        if line.startswith('[ RUN      ] '):
            self.current_test = self.test_list.find_test_by_report_id(
                self.framework, self.executable, self.parse_test_id(line))
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))

        if self.current_test:
            self.test_data.notify_test_output(TestOutput(self.current_test, line))

        if line.startswith('[       OK ] '):
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.PASSED))
            self.current_test = None
        elif line.startswith('[  FAILED  ] '):
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.FAILED))
            self.current_test = None
        elif line.startswith('[  SKIPPED ] '):
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.SKIPPED))
            self.current_test = None


class GoogleTest(TestFramework):
    def __init__(self, test_data: TestData,
                 project_root_dir: str,
                 framework_id: str = '',
                 executable_pattern: str = '*',
                 env: Dict[str, str] = {},
                 cwd: Optional[str] = None,
                 args: List[str] = [],
                 discover_args: List[str] = [],
                 run_args: List[str] = [],
                 path_prefix_style: str = 'full',
                 custom_prefix: Optional[str] = None,
                 parser: str = 'default'):
        super().__init__(test_data, project_root_dir)
        self.test_data = test_data
        self.framework_id = framework_id
        self.executable_pattern = executable_pattern
        self.env = env
        self.cwd = cwd
        self.args = args
        self.discover_args = discover_args
        self.run_args = run_args
        self.path_prefix_style = path_prefix_style
        self.custom_prefix = custom_prefix
        self.parser = parser

    @staticmethod
    def from_json(test_data: TestData, project_root_dir: str, json_data: Dict):
        assert json_data['type'] == 'catch2'
        return GoogleTest(test_data=test_data,
                          project_root_dir=project_root_dir,
                          framework_id=json_data['id'],
                          executable_pattern=json_data.get('executable_pattern', '*'),
                          env=json_data.get('env', {}),
                          cwd=json_data.get('cwd', None),
                          args=json_data.get('args', []),
                          discover_args=json_data.get('discover_args', []),
                          run_args=json_data.get('run_args', []),
                          path_prefix_style=json_data.get('path_prefix_style', 'full'),
                          custom_prefix=json_data.get('custom_prefix', None),
                          parser=json_data.get('parser', 'default'))

    def get_id(self):
        return self.framework_id

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        errors = []
        tests = []

        with TemporaryDirectory() as temp_dir:
            def run_discovery(executable):
                output_file = os.path.join(temp_dir, 'output.json')
                exe = common.make_executable_path(executable, project_root_dir=self.project_root_dir)
                discover_args = [exe, f'--gtest_output=json:{output_file}', '--gtest_list_tests']
                process.get_output(discover_args + self.args + self.discover_args, env=self.env, cwd=cwd)
                try:
                    return self.parse_discovery(output_file, executable)
                except DiscoveryError as e:
                    errors.append(e.details if e.details else str(e))
                    return []

            if '*' in self.executable_pattern:
                old_cwd = os.getcwd()
                os.chdir(self.project_root_dir)
                executables = [e for e in glob.glob(self.executable_pattern)]
                os.chdir(old_cwd)
                if len(executables) == 0:
                    logger.warning(f'no executable found with pattern "{self.executable_pattern}" ' +
                                   f'(cwd: {self.project_root_dir})')

                for executable in executables:
                    tests += run_discovery(executable)

            else:
                tests += run_discovery(self.executable_pattern)

        if errors:
            raise DiscoveryError('Error when discovering tests. See panel for more information', details=errors)

        return tests

    def parse_discovered_test(self, test: dict, suite: str, executable: str):
        # Make file path relative to project directory.
        file = os.path.relpath(test['file'], start=self.project_root_dir)
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

        pretty_suite = suite
        if 'type_param' in test:
            pretty_suite = '/'.join(pretty_suite.split('/')[:-1]) + f'<{test["type_param"]}>'

        name = test['name']

        pretty_name = name
        if 'value_param' in test:
            pretty_name = '/'.join(pretty_name.split('/')[:-1]) + f'[{test["value_param"]}]'

        path += pretty_suite.split('/') + [pretty_name]

        run_id = f'{suite}.{name}'

        return DiscoveredTest(
            full_name=path, framework_id=self.framework_id, run_id=run_id, report_id=run_id,
            location=TestLocation(executable=executable, file=file, line=line))

    def parse_discovery(self, output_file: str, executable: str) -> List[DiscoveredTest]:
        with open(output_file, 'r') as f:
            data = json.load(f)

        tests = []
        for suite in data['testsuites']:
            for test in suite['testsuite']:
                tests.append(self.parse_discovered_test(test, suite['name'], executable))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        def run_tests(executable, test_ids):
            logger.debug('starting tests from {}: "{}"'.format(executable, '" "'.join(test_ids)))

            test_filters = ':'.join(test_ids)
            exe = common.make_executable_path(executable, project_root_dir=self.project_root_dir)
            run_args = [exe, '--gtest_filter=' + test_filters]

            parser = common.get_generic_parser(parser=self.parser,
                                               test_data=self.test_data,
                                               framework_id=self.framework_id,
                                               executable=executable)

            if parser is None:
                parser = OutputParser(self.test_data, self.framework_id, executable)

            process.get_output_streamed(run_args + self.args + self.run_args,
                                        parser.feed, self.test_data.stop_tests_event,
                                        queue='gtest', ignore_errors=True, env=self.env, cwd=cwd)

        for executable, test_ids in grouped_tests.items():
            run_tests(executable, test_ids)


register_framework('gtest', GoogleTest.from_json)
