# coding: utf-8
import logging
from functools import partial
from typing import List

import sublime
from sublime_plugin import ApplicationCommand, WindowCommand, TextCommand, EventListener

from .helpers import TestDataHelper
from .util import SettingsHelper, find_views_for_test
from .test_data import test_name_to_path
from .list import TestExplorerTextCmd


logger = logging.getLogger('TestExplorer.output')

TEST_EXPLORER_TEST_OUTPUT_TITLE = '*test-output*: '

class TestExplorerOpenSelectedOutput(TextCommand, TestExplorerTextCmd):

    def is_visible(self):
        return False

    def run(self, edit):
        tests = self.get_selected_tests()

        for test in tests:
            self.view.window().run_command('test_explorer_open_run_output', {'test': test})


class TestExplorerOpenSingleOutput(WindowCommand, TestDataHelper):

    def is_visible(self):
        return True

    def run(self):
        project = self.get_project()
        if not project:
            return

        data = self.get_test_data()
        if not data:
            return

        choices = [t.full_name for t in data.get_test_list().tests()]
        if len(choices) == 0:
            return

        self.window.show_quick_panel(choices, partial(self.open_output, choices), sublime.MONOSPACE_FONT)

    def open_output(self, choices: List[str], test_id: int):
        self.window.run_command('test_explorer_open_run_output', {'test': choices[test_id]})


class TestExplorerOpenRunOutput(WindowCommand, TestDataHelper):

    def is_visible(self):
        return False

    def run(self, test):
        data = self.get_test_data()
        if not data:
            return

        logger.debug(f'opening output for {test}...')

        views = find_views_for_test(data.location, test)
        if not views:
            view = self.window.new_file()

            title = TEST_EXPLORER_TEST_OUTPUT_TITLE + test
            view.set_name(title)
            view.set_scratch(True)
            view.set_read_only(True)

            view.settings().set('test_view', 'output')
            view.settings().set('test_output', test)
            view.settings().set('test_data_full_path', data.location)

            views = [view]

        for view in views:
            view.run_command('test_explorer_output_refresh')

        if views:
            views[0].window().focus_view(views[0])
            views[0].window().bring_to_front()


class TestExplorerOutputRefresh(TextCommand, TestDataHelper):

    def is_visible(self):
        return False

    def run(self, edit):
        data = self.get_test_data()
        if not data:
            return

        test = self.view.settings().get('test_output')
        logger.debug(f'refreshing output for {test}...')

        test_list = data.get_test_list()
        output = test_list.get_test_output(test_name_to_path(test))

        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), output)
        self.view.set_read_only(True)
        self.view.sel().clear()

        autoscroll = self.get_setting('explorer_output_auto_scroll', True) is True
        if autoscroll:
            self.view.show(self.view.size())


class TestExplorerOutputRefreshAllCommand(ApplicationCommand, TestDataHelper):

    def run(self, data_location=None, test=''):
        if not data_location:
            return

        views = find_views_for_test(data_location, test)
        for view in views:
            view.run_command('test_explorer_output_refresh')


class TestExplorerOutputEventListener(EventListener, SettingsHelper):

    def on_activated(self, view):
        if view.settings().get('test_view') == 'output' and self.get_setting('explorer_update_on_focus', True):
            view.run_command('test_explorer_output_refresh')
