# coding: utf-8
import logging
import os
from typing import List
from functools import partial

import sublime
from sublime_plugin import WindowCommand, TextCommand

from .helpers import TestDataHelper
from .list import TestExplorerTextCmd
from .test_framework import TestFramework
from .discover import NO_FRAMEWORK_CONFIGURED
from .util import SettingsHelper
from .test_data import TestData, StartedRun, FinishedRun, TEST_SEPARATOR

logger = logging.getLogger('TestExplorer.runner')

TEST_STOP_CONFIRM_DIALOG = ("You are about to stop all currently-running tests. Are you sure?")

CANNOT_START_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or stop the tests "
                                     "before running new tests.")

class TestExplorerStartSelectedCommand(TextCommand, TestDataHelper, SettingsHelper, TestExplorerTextCmd):

    def is_visible(self):
        return False

    def run(self, edit):
        project = self.get_project()
        if not project:
            return

        data = self.get_test_data()
        if not data:
            return

        if data.is_running_tests():
            sublime.error_message(CANNOT_START_WHILE_RUNNING_DIALOG)
            return

        frameworks_json = self.get_setting('frameworks')
        if not frameworks_json:
            # TODO: change this into a "Do you want to configure a framework now?"
            # Then propose a dropdown list of all available frameworks, and init to default.
            # Also add a command to init a new framework to default.
            sublime.error_message(NO_FRAMEWORK_CONFIGURED)
            return

        root_dir = os.path.dirname(project)
        frameworks: List[TestFramework] = [TestFramework.from_json(data, root_dir, f) for f in frameworks_json]

        tests = self.get_selected_tests()

        sublime.set_timeout_async(partial(self.run_tests, data, project, frameworks, tests))

    def run_tests(self, data: TestData, project: str, frameworks: List[TestFramework], tests: List[str]):
        test_ids = {}
        test_paths = []
        for test in tests:
            logger.debug(f'running {test}...')
            path = test.split(TEST_SEPARATOR)
            item = data.get_test_list().find_test(path)
            if not item:
                logger.warning(f'{test} not found in list')
                continue
            if item.location is None:
                logger.warning(f'{test} is not runnable (no location)')
                continue

            test_paths.append(path)
            test_ids.setdefault(item.framework_id, {}).setdefault(item.location.executable, []).append(item.run_id)

        # TODO: put this in background thread
        data.notify_run_started(StartedRun(test_paths))
        try:
            for framework_id, grouped_tests in test_ids.items():
                logger.warn(f'running tests for {framework_id}...')
                framework = next((f for f in frameworks if f.get_id() == framework_id), None)
                if framework is None:
                    logger.warning(f'{framework_id} not found in frameworks')
                    continue

                framework.run(grouped_tests)
                logger.warning(f'done.')
        finally:
            data.notify_run_finished(FinishedRun(test_paths))


class TestExplorerStartCommand(WindowCommand, TestDataHelper, TestExplorerTextCmd):

    def run(self, start="all"):
        data = self.get_test_data()
        if not data:
            return

        if data.is_running_tests():
            sublime.error_message(CANNOT_START_WHILE_RUNNING_DIALOG)
            return

        if start == "one":
            # TODO: build list of tests and let user pick one
            sublime.error_message("Not implemented")
            # self.start_tests(data, [test])
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
