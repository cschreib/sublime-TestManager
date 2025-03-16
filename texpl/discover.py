# coding: utf-8
import os
import logging
from datetime import datetime
from functools import partial
from typing import List

import sublime
from sublime_plugin import WindowCommand

from .helpers import TestDataHelper
from .test_suite import TestSuite
from .test_data import DiscoveryError, TestData, clear_test_data
from .errors import FrameworkError
from .util import SettingsHelper

logger = logging.getLogger('TestExplorer.discovery')


CANNOT_DISCOVER_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or "
                                        "stop the tests before running test discovery.")
CANNOT_RESET_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or "
                                     "stop the tests before reseting the test data.")


NO_TEST_SUITE_CONFIGURED = ("No test suite is currently configured.")

MAX_ERROR_LENGTH = 256


class TestExplorerResetCommand(WindowCommand, TestDataHelper):

    def is_visible(self):
        return True

    def run(self):
        data = self.get_test_data(create=False)
        if not data:
            location = self.get_test_data_location()
            if not location:
                return

            clear_test_data(location)
            self.get_test_data()
            return
        else:
            if data.is_running_tests():
                sublime.error_message(CANNOT_RESET_WHILE_RUNNING_DIALOG)
                return

            data.init()
            sublime.run_command('test_explorer_refresh_all', {'data_location': data.location})


class TestExplorerDiscoverCommand(WindowCommand, TestDataHelper, SettingsHelper):

    def is_visible(self):
        return True

    def run(self):
        data = self.get_test_data()
        if not data:
            return

        project = self.get_project()
        if not project:
            return

        if data.is_running_tests():
            sublime.error_message(CANNOT_DISCOVER_WHILE_RUNNING_DIALOG)
            return

        suites_json = self.get_setting('test_suites')
        if not suites_json:
            # TODO: change this into a "Do you want to configure a test suite now?"
            # Then propose a dropdown list of all available frameworks, and init to default.
            # Also add a command to init a new suite to default.
            sublime.error_message(NO_TEST_SUITE_CONFIGURED)
            return

        root_dir = os.path.dirname(project)
        try:
            suites = [TestSuite.from_json(data, root_dir, f) for f in suites_json]
        except FrameworkError as e:
            sublime.error_message(e.message)
            return

        sublime.set_timeout_async(partial(self.discover_tests, data, suites))

    def display_in_panel(self, content):
        panel_name = 'TestExplorer.discovery'
        panel = self.window.create_output_panel(panel_name)
        panel.run_command('test_explorer_panel_write', {'content': content})
        self.window.run_command('show_panel', {'panel': f'output.{panel_name}'})

    def discover_tests(self, data: TestData, suites: List[TestSuite]):
        start = datetime.now()

        # TODO: turn this into parallel jobs
        try:
            discovered_tests = [t for s in suites for t in s.discover()]
        except DiscoveryError as e:
            sublime.error_message(str(e))
            logger.error(str(e))
            logger.error(e.details)
            if e.details:
                self.display_in_panel('\n'.join(e.details))
            return
        except Exception as e:
            message = str(e)
            logger.error(message)
            if len(message) < MAX_ERROR_LENGTH:
                sublime.error_message(message)
            else:
                sublime.error_message('Error running test discovery; see panel for more information.')
                self.display_in_panel(message)
            return

        logger.info(f'Discovered {len(discovered_tests)} tests')

        disc_id = 0
        for t in discovered_tests:
            t.discovery_id = disc_id
            disc_id += 1

        data.notify_discovered_tests(discovered_tests, discovery_time=start)
        sublime.run_command('test_explorer_refresh_all', {'data_location': data.location})
