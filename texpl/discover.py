# coding: utf-8
import logging
from datetime import datetime
from functools import partial

import sublime
from sublime_plugin import WindowCommand

from .cmd import Cmd
from .helpers import TestDataHelper
from .test_data import TestLocation, TestData, DiscoveredTest


logger = logging.getLogger('TestExplorer.discovery')


CANNOT_DISCOVER_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or "
                                        "stop the tests before running test discovery.")


class TestExplorerDiscoverCommand(WindowCommand, TestDataHelper, Cmd):

    def is_visible(self):
        return True

    def run(self):
        data = self.get_test_data()
        if not data:
            return

        if data.is_running_tests():
            sublime.error_message(CANNOT_DISCOVER_WHILE_RUNNING_DIALOG)
            return

        thread = self.worker_run_async(partial(self.discover_tests, data))
        thread.start()

    def discover_tests(self, data: TestData):
        start = datetime.now()

        discovered_tests = [
            DiscoveredTest(full_name=['Test.exe', 'TestCase1', 'test_this'], location=TestLocation(file='../texpl/list.py', line=5)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase1', 'test_that'], location=TestLocation(file='../texpl/list.py', line=6)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase1', 'test_them'], location=TestLocation(file='../texpl/list.py', line=7)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase1', 'test_new'], location=TestLocation(file='../texpl/list.py', line=10)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase2', 'test_me'], location=TestLocation(file='../texpl/util.py', line=5)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase3', 'test_me1'], location=TestLocation(file='../texpl/cmd.py', line=5)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase3', 'test_me2'], location=TestLocation(file='../texpl/cmd.py', line=6)),
            DiscoveredTest(full_name=['Test.exe', 'TestCase3', 'test_me'], location=TestLocation(file='../texpl/cmd.py', line=7)),
        ]

        data.notify_discovered_tests(discovered_tests, discovery_time=start)

        self.window.run_command('test_explorer_list', {'refresh_only': True, 'data_location': data.location})
