# coding: utf-8
import os
import logging
from datetime import datetime
from functools import partial
from typing import List

import sublime
from sublime_plugin import WindowCommand

from .cmd import Cmd
from .helpers import TestDataHelper
from .test_framework import TestFramework
from .test_data import DiscoveryError, TestData
from .util import SettingsHelper

logger = logging.getLogger('TestExplorer.discovery')


CANNOT_DISCOVER_WHILE_RUNNING_DIALOG = ("Tests are currently running; please wait or "
                                        "stop the tests before running test discovery.")


NO_FRAMEWORK_CONFIGURED = ("No test framework is currently configured.")

MAX_ERROR_LENGTH = 256


class TestExplorerDiscoverCommand(WindowCommand, TestDataHelper, SettingsHelper, Cmd):

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

        frameworks = self.get_setting('frameworks')
        if not frameworks:
            # TODO: change this into a "Do you want to configure a framework now?"
            # Then propose a dropdown list of all available frameworks, and init to default.
            # Also add a command to init a new framework to default.
            sublime.error_message(NO_FRAMEWORK_CONFIGURED)
            return

        frameworks = [TestFramework.from_json(f) for f in frameworks]

        sort = self.get_setting('sort_tests')
        assert isinstance(sort, bool)

        thread = self.worker_run_async(partial(self.discover_tests, data, project, frameworks, sort=sort))
        thread.start()

    def display_in_panel(self, content):
        panel_name = 'TestExplorer.discovery'
        panel = self.window.create_output_panel(panel_name)
        panel.run_command('test_explorer_panel_write', {'content': content})
        self.window.run_command('show_panel', {'panel': f'output.{panel_name}'})

    def discover_tests(self, data: TestData, project: str, frameworks: List[TestFramework], sort=False):
        start = datetime.now()

        root_dir = os.path.dirname(project)

        # TODO: turn this into parallel jobs
        try:
            discovered_tests = [t for f in frameworks for t in f.discover(root_dir)]
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

        if sort:
            # Sort by increasing depth first, then by name.
            comparator = lambda test: (len(test.full_name), '/'.join(test.full_name))
            discovered_tests = sorted(discovered_tests, key=comparator)

        data.notify_discovered_tests(discovered_tests, discovery_time=start)

        self.window.run_command('test_explorer_list', {'refresh_only': True, 'data_location': data.location})
