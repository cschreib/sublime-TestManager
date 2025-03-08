import logging
import re
from typing import List, Optional

from ..test_data import TestData, StartedTest, FinishedTest, TestStatus, TestOutput

parser_logger = logging.getLogger('TestExplorerParser.teamcity')

class OutputParser:
    def __init__(self, test_data: TestData, framework: str, executable: str):
        self.test_data = test_data
        self.test_list = test_data.get_test_list()
        self.framework = framework
        self.executable = executable
        self.current_test: Optional[List[str]] = None
        self.current_status = TestStatus.PASSED

    def parse_test_id(self, line: str):
        return re.search("name='(.+)'", line).group(1)

    def feed(self, line: str):
        parser_logger.debug(line.rstrip())

        if self.current_test:
            self.test_data.notify_test_output(TestOutput(self.current_test, line))

        if not line.startswith('##teamcity['):
            return

        if line.startswith('##teamcity[testStarted'):
            self.current_test = self.test_list.find_test_by_report_id(self.framework, self.executable, self.parse_test_id(line))
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

