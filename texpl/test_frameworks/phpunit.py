import os
import logging
import re
from xml.etree import ElementTree
from typing import Dict, List, Optional, Union
from tempfile import TemporaryDirectory

from ..test_framework import (TestFramework, register_framework)
from ..test_suite import TestSuite
from ..test_data import (TestData, DiscoveredTest, TestLocation, TEST_SEPARATOR)
from .. import process
from . import common, teamcity

logger = logging.getLogger('TestManager.phpunit')
parser_logger = logging.getLogger('TestManagerParser.phpunit')

class OutputParser(teamcity.OutputParser):
    def __init__(self, test_data: TestData, suite_id: str, executable: str):
        super().__init__(test_data, suite_id, executable)
        self.current_suite = None

    def parse_name(self, line: str):
        return re.search("name='([^']+)'", line).group(1)

    def parse_test_id(self, line: str):
        if self.current_suite is None:
            return self.parse_name(line)
        else:
            return f'{self.current_suite}::{self.parse_name(line)}'

    def feed(self, line: str):
        super().feed(line)

        if line.startswith('##teamcity[testSuiteStarted'):
            self.current_suite = self.parse_name(line)
            parser_logger.error(self.current_suite)


class PHPUnit(TestFramework):
    def __init__(self,
                 suite: TestSuite,
                 phpunit: Union[str, List[str]] = 'phpunit',
                 env: Dict[str, str] = {},
                 cwd: Optional[str] = None,
                 args: List[str] = [],
                 discover_args: List[str] = [],
                 run_args: List[str] = [],
                 parser: str = 'default'):
        super().__init__(suite)
        self.phpunit = phpunit
        self.env = env
        self.cwd = cwd
        self.args = args
        self.discover_args = discover_args
        self.run_args = run_args
        self.parser = parser

    @staticmethod
    def get_default_settings():
        return {
            'phpunit': 'phpunit',
            'env': {},
            'cwd': None,
            'args': [],
            'discover_args': [],
            'run_args': ['--teamcity'],
            'parser': 'default'
        }

    @staticmethod
    def from_json(suite: TestSuite, settings: Dict):
        assert settings['type'] == 'phpunit'
        return PHPUnit(suite=suite,
                       phpunit=settings['phpunit'],
                       env=settings['env'],
                       cwd=settings['cwd'],
                       args=settings['args'],
                       discover_args=settings['discover_args'],
                       run_args=settings['run_args'],
                       parser=settings['parser'])

    def get_phpunit(self):
        if isinstance(self.phpunit, list):
            return self.phpunit

        if not os.path.isabs(self.phpunit) and len(os.path.dirname(self.phpunit)) > 0:
            return [os.path.join(self.project_root_dir, self.phpunit)]

        return [self.phpunit]

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        with TemporaryDirectory() as temp_dir:
            output_file = os.path.join(temp_dir, 'output.xml')
            discover_args = self.get_phpunit() + self.discover_args + self.args + ['--list-tests-xml', output_file]
            process.get_output(discover_args, env=self.env, cwd=cwd)
            return self.parse_discovery(output_file)

    def parse_discovered_test(self, test: ElementTree.Element, class_name: str):
        path = []

        if self.suite.custom_prefix is not None:
            path += self.suite.custom_prefix.split(TEST_SEPARATOR)

        name = test.attrib['name']

        path += [class_name, name]

        run_id = f'{class_name}::{name}'

        # TODO: How to get these?
        file = ''
        line = 0

        return DiscoveredTest(
            full_name=path, suite_id=self.suite.suite_id, run_id=run_id, report_id=run_id,
            location=TestLocation(executable='phpunit', file=file, line=line))

    def parse_discovery(self, output_file: str) -> List[DiscoveredTest]:
        tree = ElementTree.parse(output_file)
        tests = []
        for c in tree.getroot():
            logger.warning(c.tag)
            if c.tag == 'testCaseClass':
                for t in c:
                    if t.tag == 'testCaseMethod':
                        tests.append(self.parse_discovered_test(t, c.attrib['name']))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        assert len(grouped_tests) == 1

        test_ids = [test for tests in grouped_tests.values() for test in tests]

        parser = common.get_generic_parser(parser=self.parser,
                                           test_data=self.test_data,
                                           suite_id=self.suite.suite_id,
                                           executable='phpunit')

        if parser is None:
            parser = OutputParser(self.test_data, self.suite.suite_id, 'phpunit')

        # TODO: This is inefficient; how to run more than one test in the same process?
        for test_id in test_ids:
            run_args = self.get_phpunit() + self.run_args + self.args + ['--filter', test_id]
            process.get_output_streamed(run_args,
                                        parser.feed, self.test_data.stop_tests_event,
                                        queue='phpunit', ignore_errors=True, env=self.env, cwd=cwd)

            parser.close()


register_framework('phpunit', 'PHPUnit (PHP) -- experimental', PHPUnit.from_json, PHPUnit.get_default_settings())
