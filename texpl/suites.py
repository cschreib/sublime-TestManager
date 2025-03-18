# coding: utf-8
import logging
from typing import List, Dict, Any
from functools import partial

import sublime
from sublime_plugin import WindowCommand

from .test_framework import get_available_frameworks, get_framework_default_settings
from .helpers import TestDataHelper, NO_PROJECT_DIALOG
from .util import SettingsHelper, merge_deep

logger = logging.getLogger('TestManager.setup')


class TestManagerAddTestSuiteCommand(WindowCommand, TestDataHelper, SettingsHelper):

    def is_visible(self):
        return True

    def add_suite(self, existing_suites, settings, suite_id):
        settings['id'] = suite_id
        existing_suites.append(settings)

        new_data = {
            'settings': {
                'TestManager': {
                    'test_suites': existing_suites
                }
            }
        }

        data = self.window.project_data()
        merge_deep(data, new_data)
        self.window.set_project_data(data)


    def select_suite_id(self, frameworks: List[Dict[str,Any]], framework_id: int):
        if framework_id < 0:
            return

        framework = frameworks[framework_id]['name']
        settings = get_framework_default_settings(framework)
        settings['framework'] = framework

        existing_suites = self.get_setting('test_suites', [])
        assert existing_suites is not None
        existing_suite_ids = [s['id'] for s in existing_suites]

        suite_id = 1
        default_suite_name = framework + '1'
        while default_suite_name in existing_suite_ids:
            suite_id += 1
            default_suite_name = framework + str(suite_id)

        self.window.show_input_panel(
            'Test suite ID:',
            default_suite_name,
            partial(self.add_suite, existing_suites, settings),
            None,
            None)

    def run(self):
        project = self.get_project()
        if project is None:
            sublime.error_message(NO_PROJECT_DIALOG)
            return

        frameworks = get_available_frameworks()
        choices = [[f['name'], f['description']] for f in frameworks]

        self.window.show_quick_panel(
            choices,
            partial(self.select_suite_id, frameworks),
            flags=sublime.MONOSPACE_FONT,
            placeholder='Test framework used by the test suite')
