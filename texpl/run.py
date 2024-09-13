# coding: utf-8
import logging

import sublime
from sublime_plugin import WindowCommand

from .helpers import TestDataHelper

logger = logging.getLogger('TestExplorer.runner')

TEST_STOP_CONFIRM_DIALOG = ("You are about to stop all currently-running tests. Are you sure?")

CANNOT_START_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or stop the tests "
                                     "before running new tests.")

class TestExplorerStartCommand(WindowCommand, TestDataHelper):

    def run(self, start="all", tests=None):
        data = self.get_test_data()
        if not data:
            return

        if data.is_running_tests():
            sublime.error_message(CANNOT_START_WHILE_RUNNING_DIALOG)
            return

        if start == "one":
            # TODO: build list of tests and let user pick one
            sublime.error_message("Not implemented")
            self.start_tests(data, [test])
        elif start == "list":
            self.start_tests(data, tests)
        elif start == "all":
            self.start_all_tests(data)

    def start_tests(self, data, tests):
        sublime.error_message("Not implemented")

    def start_all_tests(self, data):
        sublime.error_message("Not implemented")


class TestExplorerStopCommand(WindowCommand, TestDataHelper):

    def run(self, edit):
        data = self.get_test_data()
        if not data:
            return

        if not data.is_running_tests():
            return

        if sublime.ok_cancel_dialog(TEST_STOP_CONFIRM_DIALOG, "Stop tests"):
            self.stop_all_tests(data)

    def stop_all_tests(self, data):
        sublime.error_message("Not implemented")
