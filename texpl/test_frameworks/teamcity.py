import logging
import re
from typing import List, Optional

from ..test_data import (TestData, StartedTest, FinishedTest, TestStatus, TestOutput)

parser_logger = logging.getLogger('TestExplorerParser.teamcity')


class OutputParser:
    def __init__(self, test_data: TestData, suite_id: str, executable: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.suite_id = suite_id
        self.executable = executable
        self.current_test: Optional[List[str]] = None
        self.current_status = TestStatus.PASSED

    def parse_test_id(self, line: str):
        return re.search("name='(.+)'", line).group(1)

    def finish_current_test(self):
        if self.current_test is not None:
            self.test_data.notify_test_finished(FinishedTest(self.current_test, TestStatus.CRASHED))
            self.current_test = None

    def close(self):
        self.finish_current_test()

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())

        if self.current_test:
            self.test_data.notify_test_output(TestOutput(self.current_test, line))

        if not line.startswith('##teamcity['):
            return

        if line.startswith('##teamcity[testStarted'):
            self.finish_current_test()
            self.current_test = self.test_list.find_test_by_report_id(
                self.suite_id, self.executable, self.parse_test_id(line))
            self.current_status = TestStatus.PASSED
            if self.current_test is None:
                return

            self.test_data.notify_test_started(StartedTest(self.current_test))

        if line.startswith('##teamcity[testFinished'):
            if self.current_test is None:
                return

            self.test_data.notify_test_finished(FinishedTest(self.current_test, self.current_status))
            self.current_test = None

        if line.startswith('##teamcity[testIgnored'):
            self.current_status = TestStatus.SKIPPED

        if line.startswith('##teamcity[testFailed'):
            self.current_status = TestStatus.FAILED
