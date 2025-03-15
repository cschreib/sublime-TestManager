import os
import logging
import json
from typing import Dict, List, Optional, Union

from ..test_framework import (TestFramework, register_framework)
from ..test_suite import TestSuite
from ..test_data import (DiscoveredTest, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

logger = logging.getLogger('TestExplorer.cargo')
parser_logger = logging.getLogger('TestExplorerParser.cargo')


def get_json(line: str):
    if not line.startswith('{'):
        return None

    try:
        json_line = json.loads(line)
    except:
        return None

    if 'type' not in json_line or 'event' not in json_line:
        return None

    return json_line


class OutputParser:
    def __init__(self, test_data: TestData, suite_id: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.suite_id = suite_id
        self.current_test: Optional[List[str]] = None

    def finish_current_test(self):
        if self.current_test is not None:
            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.CRASHED))
            self.current_test = None

    def close(self):
        self.finish_current_test()

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())

        json_line = get_json(line)
        if json_line is None:
            if self.current_test:
                self.test_data.notify_test_output(TestOutput(self.current_test, line))
            return

        if json_line['type'] != 'test':
            return

        if json_line['event'] == 'started':
            self.finish_current_test()
            self.current_test = self.test_list.find_test_by_report_id(
                self.suite_id, 'cargo', json_line['name'])
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
    def __init__(self,
                 suite: TestSuite,
                 cargo: Union[str, List[str]] = 'cargo',
                 env: Dict[str, str] = {},
                 cwd: Optional[str] = None,
                 args: List[str] = [],
                 discover_args: List[str] = [],
                 run_args: List[str] = [],
                 parser: str = 'default'):
        super().__init__(suite)
        self.cargo = cargo
        self.env = env
        self.cwd = cwd
        self.args = args
        self.discover_args = discover_args
        self.run_args = run_args
        self.parser = parser

    @staticmethod
    def get_default_settings():
        return {
            'cargo': 'cargo',
            'env': {},
            'cwd': None,
            'args': [],
            'discover_args': ['test', '--', '--list', '--test-threads=1',
                              '--nocapture', '--format=json', '-Z', 'unstable-options'],
            'run_args': ['test', '--', '--test-threads=1', '--nocapture',
                         '--exact', '--format=json', '-Z', 'unstable-options'],
            'parser': 'default'
        }

    @staticmethod
    def from_json(suite: TestSuite, settings: Dict):
        assert settings['type'] == 'cargo'
        return Cargo(suite=suite,
                     cargo=settings['cargo'],
                     env=settings['env'],
                     cwd=settings['cwd'],
                     args=settings['args'],
                     discover_args=settings['discover_args'],
                     run_args=settings['run_args'],
                     parser=settings['parser'])

    def get_cargo(self):
        if isinstance(self.cargo, list):
            return self.cargo

        if not os.path.isabs(self.cargo) and len(os.path.dirname(self.cargo)) > 0:
            return [os.path.join(self.project_root_dir, self.cargo)]

        return [self.cargo]

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)
        discover_args = self.get_cargo() + self.discover_args + self.args
        output = process.get_output(discover_args, env=self.env, cwd=cwd)
        return self.parse_discovery(output, cwd)

    def parse_discovered_test(self, json_data: dict, working_directory: str):
        discovery_file = common.change_parent_dir(json_data['source_path'],
                                                  old_cwd=working_directory,
                                                  new_cwd=self.project_root_dir)

        path = []

        if self.suite.custom_prefix is not None:
            path += self.suite.custom_prefix.split(TEST_SEPARATOR)

        path += common.get_file_prefix(discovery_file, path_prefix_style=self.suite.path_prefix_style)
        path += json_data['name'].split('::')

        run_id = json_data['name']

        return DiscoveredTest(
            full_name=path, suite_id=self.suite.suite_id, run_id=run_id, report_id=run_id,
            location=TestLocation(executable='cargo', file=json_data['source_path'], line=json_data['start_line']))

    def parse_discovery(self, output: str, working_directory: str) -> List[DiscoveredTest]:
        tests = []
        for line in output.split('\n'):
            json_line = get_json(line)
            if json_line is None:
                continue

            if json_line['type'] != 'test' or json_line['event'] != 'discovered':
                continue

            tests.append(self.parse_discovered_test(json_line, working_directory))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        assert len(grouped_tests) == 1

        test_ids = [test for tests in grouped_tests.values() for test in tests]

        parser = common.get_generic_parser(parser=self.parser,
                                           test_data=self.test_data,
                                           suite_id=self.suite.suite_id,
                                           executable='cargo')

        if parser is None:
            parser = OutputParser(self.test_data, self.suite.suite_id)

        run_args = self.get_cargo() + self.run_args + self.args + test_ids
        process.get_output_streamed(run_args,
                                    parser.feed, self.test_data.stop_tests_event,
                                    queue='cargo', ignore_errors=True, env=self.env, cwd=cwd)

        parser.close()


register_framework('cargo', Cargo.from_json, Cargo.get_default_settings())
