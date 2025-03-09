import os
import logging
import json
from typing import Dict, List, Optional, Union

from ..test_framework import (TestFramework, register_framework)
from ..test_data import (DiscoveredTest, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

logger = logging.getLogger('TestExplorer.cargo')
parser_logger = logging.getLogger('TestExplorerParser.cargo')


class OutputParser:
    def __init__(self, test_data: TestData, framework: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.current_test: Optional[List[str]] = None

    def parse_test_id(self, line: str):
        return line[12:].strip().split(' ')[0]

    def get_json(self, line: str):
        if not line.startswith('{'):
            return None

        try:
            json_line = json.loads(line)
        except:
            return None

        if 'type' not in json_line or 'event' not in json_line:
            return None

        return json_line

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())

        json_line = self.get_json(line)
        if json_line is None:
            if self.current_test:
                self.test_data.notify_test_output(TestOutput(self.current_test, line))
            return

        if json_line['type'] != 'test':
            return

        if json_line['event'] == 'started':
            self.current_test = self.test_list.find_test_by_report_id(
                self.framework, 'cargo', json_line['name'])
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))

        if json_line['event'] == 'ok':
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.PASSED))
            self.current_test = None
        elif json_line['event'] == 'failed':
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.FAILED))
            self.current_test = None
        elif json_line['event'] == 'ignored':
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.SKIPPED))
            self.current_test = None


class Cargo(TestFramework):
    def __init__(self, test_data: TestData,
                 project_root_dir: str,
                 framework_id: str = '',
                 cargo: Union[str, List[str]] = 'cargo',
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
        self.cargo = cargo
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
        assert json_data['type'] == 'cargo'
        return Cargo(test_data=test_data,
                     project_root_dir=project_root_dir,
                     framework_id=json_data['id'],
                     cargo=json_data.get('cargo', 'cargo'),
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

    def get_cargo(self):
        if isinstance(self.cargo, list):
            return self.cargo

        if not os.path.isabs(self.cargo) and len(os.path.dirname(self.cargo)) > 0:
            return [os.path.join(self.project_root_dir, self.cargo)]

        return [self.cargo]

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)
        discover_args = self.get_cargo() + ['test', '--', '--list', '--test-threads=1',
                                            '--nocapture', '--format=json', '-Z', 'unstable-options']
        output = process.get_output(discover_args + self.args + self.discover_args, env=self.env, cwd=cwd)
        return self.parse_discovery(output, cwd)

    def parse_discovered_test(self, json_data: dict, working_directory: str):
        # Make file path relative to project directory.
        path = []

        if self.custom_prefix is not None:
            path += self.custom_prefix.split(TEST_SEPARATOR)

        discovery_file = json_data['source_path']
        discovery_file = os.path.normpath(os.path.relpath(os.path.join(
            working_directory, discovery_file), start=self.project_root_dir))

        if self.path_prefix_style == 'full':
            path += os.path.normpath(discovery_file).split(os.sep)
        elif self.path_prefix_style == 'basename':
            path.append(os.path.basename(discovery_file))
        elif self.path_prefix_style == 'none':
            pass

        path += json_data['name'].split('::')

        run_id = json_data['name']

        return DiscoveredTest(
            full_name=path, framework_id=self.framework_id, run_id=run_id, report_id=run_id,
            location=TestLocation(executable='cargo', file=json_data['source_path'], line=json_data['start_line']))

    def parse_discovery(self, output: str, working_directory: str) -> List[DiscoveredTest]:
        tests = []
        for line in output.split('\n'):
            if not line.startswith('{'):
                continue

            try:
                json_line = json.loads(line)
            except:
                continue

            if 'type' not in json_line or 'event' not in json_line:
                continue

            if json_line['type'] != 'test' or json_line['event'] != 'discovered':
                continue

            tests.append(self.parse_discovered_test(json_line, working_directory))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        assert len(grouped_tests) == 1

        test_ids = [test for tests in grouped_tests.values() for test in tests]
        run_args = self.get_cargo() + ['test', '--', '--test-threads=1',
                                       '--nocapture', '--format=json', '-Z', 'unstable-options'] + test_ids

        parser = common.get_generic_parser(parser=self.parser,
                                           test_data=self.test_data,
                                           framework_id=self.framework_id,
                                           executable='cargo')

        if parser is None:
            parser = OutputParser(self.test_data, self.framework_id)

        process.get_output_streamed(run_args + self.args + self.run_args,
                                    parser.feed, self.test_data.stop_tests_event,
                                    queue='cargo', ignore_errors=True, env=self.env, cwd=cwd)


register_framework('cargo', Cargo.from_json)
