import os
import logging
import xml.etree.ElementTree as ET
import xml.sax
from xml.sax.xmlreader import IncrementalParser
from typing import Dict, List, Optional

from ..test_framework import (TestFramework, register_framework)
from ..test_suite import TestSuite
from ..test_data import (DiscoveredTest, DiscoveryError, TestLocation, TestData,
                         StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus, TestOutput)
from .. import process
from . import common

logger = logging.getLogger('TestManager.catch2')

# The content inside these elements is controlled by Catch2, don't assume it is standard output.
captured_elements = ['Info', 'Original', 'Expanded',
                     'StdOut', 'StdErr', 'Skip', 'Exception', 'FatalErrorCondition']


class OutputParser(common.XmlParser):
    def __init__(self, test_data: TestData, suite_id: str, executable: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.suite_id = suite_id
        self.executable = executable

        self.current_test: Optional[List[str]] = None
        self.last_status: Optional[TestStatus] = None
        self.has_output = False
        self.current_expression: Optional[dict] = None
        self.current_sections = []
        self.current_infos = []
        self.last_results_content = {}
        self.last_expression_content = {}

        xml_parser = xml.sax.make_parser()
        assert isinstance(xml_parser, IncrementalParser)
        self.xml_parser = xml_parser
        self.xml_parser.setContentHandler(common.XmlStreamHandler(self, captured_elements))

    def feed(self, line):
        self.xml_parser.feed(line)

    def close(self):
        self.finish_current_test()
        self.xml_parser.close()

    def finish_current_test(self):
        if self.current_test is None:
            return

        if self.last_status is None:
            self.last_status = TestStatus.CRASHED

        prev = '\n\n' if self.has_output else ''

        content = self.last_results_content.get('Skip', '')
        if len(content) > 0:
            self.test_data.notify_test_output(
                TestOutput(self.current_test, f'{prev}{common.make_header("SKIPPED")}\n{content.strip()}'))
            prev = '\n\n'

        content = self.last_results_content.get('StdErr', '')
        if len(content) > 0:
            self.test_data.notify_test_output(
                TestOutput(self.current_test, f'{prev}{common.make_header("STDERR")}\n{content}'))
            prev = '\n\n'

        content = self.last_results_content.get('StdOut', '')
        if len(content) > 0:
            self.test_data.notify_test_output(
                TestOutput(self.current_test, f'{prev}{common.make_header("STDOUT")}\n{content}'))

        self.test_data.notify_test_finished(FinishedTest(self.current_test, self.last_status))

        self.last_results_content = {}
        self.current_test = None
        self.has_output = False

    def startElement(self, name, attrs):
        if name == 'TestCase':
            self.finish_current_test()
            self.current_test = self.test_list.find_test_by_report_id(
                self.suite_id, self.executable, attrs['name'])
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))
        elif name == 'OverallResult':
            if 'success' in attrs and attrs['success'] == 'true':
                self.last_status = TestStatus.PASSED
            else:
                self.last_status = TestStatus.FAILED

            if 'skips' in attrs and attrs['skips'] != '0':
                self.last_status = TestStatus.SKIPPED
        elif name == 'Expression':
            self.current_expression = attrs
        elif name == 'Exception' or name == 'FatalErrorCondition':
            self.current_exception = attrs
        elif name == 'Section':
            self.current_sections.append(attrs)

    def endElement(self, name, content):
        if name == 'Skip' or name == 'StdErr' or name == 'StdOut':
            self.last_results_content[name] = content
        elif name == 'OverallResult':
            self.finish_current_test()
        elif name == 'Original' or name == 'Expanded':
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
            sections = ''.join([f'  in section "{s["name"]}"\n' for s in self.current_sections])
            infos = ''.join([f'  with "{i}"\n' for i in self.current_infos])

            self.test_data.notify_test_output(
                TestOutput(self.current_test, sep +
                           f'{result}\n' +
                           f'  at {file}:{line}\n' +
                           f'{sections}{infos}\n' +
                           f'Expected: {check}({original})\n' +
                           f'Actual:   {expanded}\n' +
                           sep))

            self.has_output = True
            self.last_expression_content = {}
            self.current_expression = None
            self.current_infos = []
        elif name == 'Exception' or name == 'FatalErrorCondition':
            if self.current_test is None or self.current_exception is None:
                return

            sep = '-'*64 + '\n'

            message = content.strip()
            result = 'EXCEPTION' if name == 'Exception' else 'CRASH'
            sections = ''.join([f'  in section "{s["name"]}"\n' for s in self.current_sections])
            infos = ''.join([f'  with "{i}"\n' for i in self.current_infos])

            self.test_data.notify_test_output(TestOutput(self.current_test,
                                                         f'{sep}{result}\n{sections}{infos}{message}\n{sep}'))

            self.has_output = True
            self.current_exception = None
            self.current_infos = []
        elif name == 'Section':
            self.current_sections.pop()
        elif name == 'Info':
            self.current_infos.append(content.strip())
        elif name == 'TestCase':
            self.content = {}

    def output(self, content):
        if self.current_test is not None:
            self.test_data.notify_test_output(TestOutput(self.current_test, content))


class Catch2(TestFramework):
    def __init__(self,
                 suite: TestSuite,
                 executable_pattern: str = '*',
                 env: Dict[str, str] = {},
                 cwd: Optional[str] = None,
                 args: List[str] = [],
                 discover_args: List[str] = [],
                 run_args: List[str] = [],
                 parser: str = 'default'):
        super().__init__(suite)
        self.executable_pattern = executable_pattern
        self.env = env
        self.cwd = cwd
        self.args = args
        self.discover_args = discover_args
        self.run_args = run_args
        self.parser = parser

    @staticmethod
    def get_default_settings():
        return {
            'executable_pattern': '*',
            'env': {},
            'cwd': None,
            'args': [],
            'discover_args': ['-r', 'xml', '--list-tests'],
            'run_args': ['-r', 'xml'],
            'parser': 'default'
        }

    @staticmethod
    def from_json(suite: TestSuite, settings: Dict):
        assert settings['type'] == 'catch2'
        return Catch2(suite=suite,
                      executable_pattern=settings['executable_pattern'],
                      env=settings['env'],
                      cwd=settings['cwd'],
                      args=settings['args'],
                      discover_args=settings['discover_args'],
                      run_args=settings['run_args'],
                      parser=settings['parser'])

    def discover(self) -> List[DiscoveredTest]:
        cwd = common.get_working_directory(user_cwd=self.cwd, project_root_dir=self.project_root_dir)

        errors = []
        tests = []

        def run_discovery(executable):
            exe = common.make_executable_path(executable, project_root_dir=self.project_root_dir)
            discover_args = [exe] + self.discover_args + self.args
            output = process.get_output(discover_args,
                                        queue='catch2', env=self.env, cwd=cwd)
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
        location = test.find('SourceInfo')
        assert location is not None

        file = location.find('File')
        assert file is not None
        file = file.text
        assert file is not None

        # Catch2 reports absolute paths; make it relative to the project directory.
        file = os.path.relpath(file, start=self.project_root_dir)

        line = location.find('Line')
        assert line is not None
        line = line.text
        assert line is not None

        path = []

        if self.suite.custom_prefix is not None:
            path += self.suite.custom_prefix.split(TEST_SEPARATOR)

        path += common.get_file_prefix(executable, path_prefix_style=self.suite.path_prefix_style)

        fixture = test.find('ClassName')
        if fixture is not None and fixture.text is not None:
            assert len(fixture.text) > 0
            path.append(fixture.text)

        name = test.find('Name')
        assert name is not None
        name = name.text
        assert name is not None

        path.append(name)

        return DiscoveredTest(
            full_name=path, suite_id=self.suite.suite_id, run_id=name, report_id=name,
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
                                               suite_id=self.suite.suite_id,
                                               executable=executable)

            if parser is None:
                parser = OutputParser(self.test_data, self.suite.suite_id, executable)

            run_args = [exe] + self.run_args + self.args + [test_filters]
            process.get_output_streamed(run_args,
                                        parser.feed, self.test_data.stop_tests_event,
                                        queue='catch2', ignore_errors=True, env=self.env, cwd=cwd)

            parser.close()

        for executable, test_ids in grouped_tests.items():
            run_tests(executable, test_ids)


register_framework('catch2', Catch2.from_json, Catch2.get_default_settings())
