import os
import logging
import glob
import xml.etree.ElementTree as ET
import xml.sax
from typing import Dict, List, Optional
from functools import partial

from ..test_framework import TestFramework, register_framework
from ..test_data import DiscoveredTest, DiscoveryError, TestLocation, TestData, StartedTest, FinishedTest, TEST_SEPARATOR, TestStatus
from ..cmd import Cmd

logger = logging.getLogger('TestExplorer.catch2')
parser_logger = logging.getLogger('TestExplorerParser.catch2')

class ResultsStreamHandler(xml.sax.handler.ContentHandler):
    def __init__(self, test_data: TestData, framework: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.current_test: Optional[List[str]] = None

    def startElement(self, name, attrs):
        attrs_str = ', '.join(['"{}": "{}"'.format(k, v) for k, v in attrs.items()])
        parser_logger.debug('startElement(' + name + ', ' + attrs_str + ')')

        if name == 'TestCase':
            self.current_test = self.test_list.find_test_by_run_id(self.framework, attrs['name'])
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))

        if name == 'OverallResult':
            if self.current_test is None:
                return

            if 'success' in attrs and attrs['success'] == 'true':
                status = TestStatus.PASSED
            else:
                status = TestStatus.FAILED

            if 'skips' in attrs and attrs['skips'] != '0':
                status = TestStatus.SKIPPED

            self.test_data.notify_test_finished(FinishedTest(self.current_test, status))
            self.current_test = None

    def endElement(self, name):
        parser_logger.debug('endElement(' + name + ')')

    def characters(self, content):
        parser_logger.debug('characters(' + content + ')')


class Catch2(TestFramework, Cmd):
    def __init__(self, test_data: TestData,
                       project_root_dir: str,
                       framework_id: str = '',
                       executable_pattern: str = '*',
                       env: Dict[str,str] = {},
                       cwd: Optional[str] = None,
                       args: List[str] = [],
                       path_prefix_style: str = 'full',
                       custom_prefix: Optional[str] = None):
        super().__init__(test_data, project_root_dir)
        self.test_data = test_data
        self.framework_id = framework_id
        self.executable_pattern = executable_pattern
        self.env = env
        self.cwd = cwd
        self.args = args
        self.path_prefix_style = path_prefix_style
        self.custom_prefix = custom_prefix

    @staticmethod
    def from_json(test_data: TestData, project_root_dir: str, json_data: Dict):
        assert json_data['type'] == 'catch2'
        return Catch2(test_data=test_data,
                      project_root_dir=project_root_dir,
                      framework_id=json_data['id'],
                      executable_pattern=json_data.get('executable_pattern', '*'),
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

    def make_executable_path(self, executable):
        return os.path.join(self.project_root_dir, executable) if not os.path.isabs(executable) else executable

    def discover(self) -> List[DiscoveredTest]:
        cwd = self.get_working_directory()

        errors = []
        tests = []

        def run_discovery(executable):
            discover_args = [self.make_executable_path(executable), '-r', 'xml', '--list-tests']
            output = self.cmd_string(discover_args + self.args, queue='catch2', env=self.env, cwd=cwd)
            try:
                return self.parse_discovery(output, executable)
            except DiscoveryError as e:
                errors.append(e.details if e.details else str(e))
                return []

        if '*' in self.executable_pattern:
            for executable in glob.glob(self.executable_pattern):
                logger.debug(f'Discovering from {executable}')
                tests += run_discovery(executable)
        else:
            tests += run_discovery(self.executable_pattern)

        if errors:
            raise DiscoveryError('Error when discovering tests. See panel for more information', details=errors)

        return tests

    def parse_discovered_test(self, test: ET.Element, executable: str):
        # Make file path relative to project directory.
        location = test.find('SourceInfo')
        assert location is not None

        file = location.find('File')
        assert file is not None
        file = file.text
        assert file is not None

        file = os.path.relpath(file, start=self.project_root_dir)

        line = location.find('Line')
        assert line is not None
        line = line.text
        assert line is not None

        path = []

        if self.custom_prefix is not None:
            path += self.custom_prefix.split(TEST_SEPARATOR)

        if self.path_prefix_style == 'full':
            path += os.path.normpath(executable).split(os.sep)
        elif self.path_prefix_style == 'basename':
            path.append(os.path.basename(executable))
        elif self.path_prefix_style == 'none':
            pass

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
            full_name=path, framework_id=self.framework_id, run_id=name,
            location=TestLocation(executable=executable, file=file, line=int(line)))

    def parse_discovery(self, output: str, executable: str) -> List[DiscoveredTest]:
        tests = []
        for t in ET.fromstring(output):
            if t.tag == 'TestCase':
                tests.append(self.parse_discovered_test(t, executable))

        return tests

    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        cwd = self.get_working_directory()

        def run_tests(executable, test_ids):
            logger.debug('starting tests from {}: "{}"'.format(executable, '" "'.join(test_ids)))

            run_args = [self.make_executable_path(executable), '-r', 'xml', ','.join([test.replace(',','\\,') for test in test_ids])]

            parser = xml.sax.make_parser()
            parser.setContentHandler(ResultsStreamHandler(self.test_data, self.framework_id))

            def stream_reader(parser, line):
                parser.feed(line)

            self.cmd_streamed(run_args + self.args, partial(stream_reader, parser),
                queue='catch2', ignore_errors=True, env=self.env, cwd=cwd)

        for executable, test_ids in grouped_tests.items():
            run_tests(executable, test_ids)


register_framework('catch2', Catch2.from_json)
