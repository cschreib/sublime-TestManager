import os
import logging
import xml.etree.ElementTree as ET
import xml.sax
from typing import Dict, List, Optional
from functools import partial

from ..test_framework import (TestFramework, register_framework)
from ..test_data import (DiscoveredTest, DiscoveryError, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

logger = logging.getLogger('TestExplorer.doctest-cpp')

# The content inside these elements is controlled by doctest, don't assume it is standard output.
captured_elements = ['Info', 'Original', 'Expanded', 'Exception']


class OutputParser(common.XmlParser):
    def __init__(self, test_data: TestData, framework: str, executable: str, test_ids: List[str]):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.executable = executable
        self.test_ids = test_ids

        self.current_test: Optional[List[str]] = None
        self.has_output = False
        self.current_expression: Optional[dict] = None
        self.current_sections = []
        self.current_infos = []
        self.current_exception: Optional[dict] = None
        self.last_expression_content = {}

    def startElement(self, name, attrs):
        if name == 'TestCase':
            test_id = attrs['name']
            if not test_id in self.test_ids:
                # doctest always outputs a TestCase element for all tests, even if they are not
                # run; they are marked as "skipped". We don't want that to be interpreted as an
                # actual skipped test, it is just that the test has not run. Sadly there is no
                # distinction in the XML output between the two, so we have to manually filter out
                # results for tests that we did not intend to run...
                return

            self.current_test = self.test_list.find_test_by_report_id(self.framework, self.executable, test_id)
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))

            if 'skipped' in attrs and attrs['skipped'] == 'true':
                self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.SKIPPED))
                self.current_test = None
        elif name == 'OverallResultsAsserts':
            if self.current_test is None:
                return

            if 'test_case_success' in attrs and attrs['test_case_success'] == 'true':
                status = TestStatus.PASSED
            else:
                status = TestStatus.FAILED

            self.test_data.notify_test_finished(FinishedTest(self.current_test, status))
            self.current_test = None
            self.has_output = False
        elif name == 'Expression':
            self.current_expression = attrs
        elif name == 'Exception':
            self.current_exception = attrs
        elif name == 'SubCase':
            self.current_sections.append(attrs)

    def endElement(self, name, content):
        if name == 'Original' or name == 'Expanded':
            self.last_expression_content[name] = content.strip()
        elif name == 'Expression':
            if self.current_test is None or self.current_expression is None:
                return

            sep = '-'*64 + '\n'

            original = self.last_expression_content.get('Original', '')
            expanded = self.last_expression_content.get('Expanded', '')

            file = self.current_expression["filename"]
            line = self.current_expression["line"]
            result = 'FAILED' if self.current_expression["success"] == 'false' else 'PASSED'
            check = self.current_expression["type"]
            subcases = ''.join([f'  in subcase "{s["name"]}"\n' for s in self.current_sections])
            infos = ''.join([f'  with "{i}"\n' for i in self.current_infos])

            self.test_data.notify_test_output(
                TestOutput(self.current_test, sep +
                           f'{result}\n' +
                           f'  at {file}:{line}\n' +
                           f'{subcases}{infos}\n' +
                           f'Expected: {check}({original})\n' +
                           f'Actual:   {expanded}\n' +
                           sep))

            self.has_output = True
            self.current_expression = None
            self.current_infos = []
            self.last_expression_content = {}
        elif name == 'Exception':
            if self.current_test is None or self.current_exception is None:
                return

            sep = '-'*64 + '\n'

            message = content.strip()
            result = 'EXCEPTION' if self.current_exception["crash"] == 'false' else 'CRASH'
            subcases = ''.join([f'  in subcase "{s["name"]}"\n' for s in self.current_sections])
            infos = ''.join([f'  with "{i}"\n' for i in self.current_infos])

            self.test_data.notify_test_output(TestOutput(self.current_test,
                                                         f'{sep}{result}\n{subcases}{infos}{message}\n{sep}'))

            self.has_output = True
            self.current_exception = None
            self.current_infos = []
        elif name == 'SubCase':
            self.current_sections.pop()
        elif name == 'Info':
            self.current_infos.append(content.strip())
        elif name == 'TestCase':
            self.content = {}

    def output(self, content):
        if self.current_test is not None:
            self.test_data.notify_test_output(TestOutput(self.current_test, content))


class DoctestCpp(TestFramework):
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
        assert json_data['type'] == 'doctest-cpp'
        return DoctestCpp(test_data=test_data,
                          project_root_dir=project_root_dir,
                          framework_id=json_data['id'],
                          executable_pattern=json_data.get('executable_pattern', '*'),
                          env=json_data.get('env', {}),
                          cwd=json_data.get('cwd', None),
                          args=json_data.get('args', []),
                          discover_args=json_data.get('discover_args', ['-r=xml', '-ltc', '--no-skip']),
                          run_args=json_data.get('run_args', ['-r=xml']),
                          path_prefix_style=json_data.get('path_prefix_style', 'full'),
                          custom_prefix=json_data.get('custom_prefix', None),
                          parser=json_data.get('parser', 'default'))

    def get_id(self):
        return self.framework_id

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        errors = []
        tests = []

        def run_discovery(executable):
            exe = common.make_executable_path(executable, project_root_dir=self.project_root_dir)
            discover_args = [exe] + self.discover_args + self.args
            output = process.get_output(discover_args, env=self.env, cwd=cwd)
            try:
                return self.parse_discovery(output, executable)
            except DiscoveryError as e:
                errors.append(e.details if e.details else str(e))
                return []

        executables = common.discover_executables(self.executable_pattern, cwd=self.project_root_dir)
        if len(executables) == 0:
            logger.warning(f'no executable found with pattern "{self.executable_pattern}" ' +
                           f'(cwd: {self.project_root_dir})')

        for executable in executables:
            tests += run_discovery(executable)

        if errors:
            raise DiscoveryError('Error when discovering tests. See panel for more information', details=errors)

        return tests

    def parse_discovered_test(self, test: ET.Element, executable: str):
        file = test.attrib.get('filename')
        assert file is not None

        # Doctest reports absolute paths; make it relative to the project directory.
        file = os.path.relpath(file, start=self.project_root_dir)

        line = test.attrib.get('line')
        assert line is not None

        path = []

        if self.custom_prefix is not None:
            path += self.custom_prefix.split(TEST_SEPARATOR)

        path += common.get_file_prefix(executable, path_prefix_style=self.path_prefix_style)

        suite = test.attrib.get('testsuite')
        if suite:
            path.append(suite)

        name = test.attrib.get('name')
        assert name is not None

        path.append(name)

        return DiscoveredTest(
            full_name=path, framework_id=self.framework_id, run_id=name, report_id=name,
            location=TestLocation(executable=executable, file=file, line=int(line)))

    def parse_discovery(self, output: str, executable: str) -> List[DiscoveredTest]:
        tests = []
        for t in ET.fromstring(output):
            if t.tag == 'TestCase':
                tests.append(self.parse_discovered_test(t, executable))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        def run_tests(executable, test_ids):
            logger.debug('starting tests from {}: "{}"'.format(executable, '" "'.join(test_ids)))

            test_filters = ','.join(test.replace(',', '\\,') for test in test_ids)
            exe = common.make_executable_path(executable, project_root_dir=self.project_root_dir)

            parser = common.get_generic_parser(parser=self.parser,
                                               test_data=self.test_data,
                                               framework_id=self.framework_id,
                                               executable=executable)

            if parser is None:
                parser = xml.sax.make_parser()
                parser.setContentHandler(common.XmlStreamHandler(
                    OutputParser(self.test_data, self.framework_id, executable, test_ids),
                    captured_elements))

            def stream_reader(parser, line):
                parser.feed(line)

            run_args = [exe] + self.run_args + self.args + ['-tc=' + test_filters]
            process.get_output_streamed(run_args,
                                        partial(stream_reader, parser), self.test_data.stop_tests_event,
                                        queue='doctest-cpp', ignore_errors=True, env=self.env, cwd=cwd)

        for executable, test_ids in grouped_tests.items():
            run_tests(executable, test_ids)


register_framework('doctest-cpp', DoctestCpp.from_json)
