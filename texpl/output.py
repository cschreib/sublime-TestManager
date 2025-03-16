# coding: utf-8
import logging
from functools import partial
from typing import List

import sublime
from sublime_plugin import ApplicationCommand, WindowCommand, TextCommand, ViewEventListener

from .helpers import TestDataHelper
from .util import SettingsHelper, find_views_for_test
from .test_data import test_name_to_path
from .list import TestManagerTextCmd


logger = logging.getLogger('TestManager.output')

TEST_MANAGER_TEST_OUTPUT_TITLE = '*test-output*: '


class TestManagerOpenSelectedOutput(TextCommand, TestManagerTextCmd):

    def is_visible(self):
        return False

    def run(self, edit):
        tests = self.get_selected_tests()

        for test in tests:
            self.view.window().run_command('test_manager_open_run_output', {'test': test})


class TestManagerOpenSingleOutput(WindowCommand, TestDataHelper):

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
        self.window.run_command('test_manager_open_run_output', {'test': choices[test_id]})


class TestManagerOpenRunOutput(WindowCommand, TestDataHelper):

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

            title = TEST_MANAGER_TEST_OUTPUT_TITLE + test
            view.set_name(title)
            view.set_scratch(True)
            view.set_read_only(True)

            view.settings().set('test_view', 'output')
            view.settings().set('test_output', test)
            view.settings().set('test_data_full_path', data.location)

            views = [view]

        for view in views:
            view.run_command('test_manager_output_refresh')

        if views:
            views[0].window().focus_view(views[0])
            views[0].window().bring_to_front()

            refresh_interval = self.get_setting('output_refresh_interval', 0.1) * 1000

            views[0].run_command('test_manager_output_refresh')
            sublime.set_timeout(partial(refresh_loop, views[0], refresh_interval), refresh_interval)


class TestManagerOutputRefresh(TextCommand, TestDataHelper):

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

        old_content = self.view.substr(sublime.Region(0, self.view.size()))
        was_at_end = len(old_content) in self.view.visible_region()

        self.view.set_read_only(False)

        replaced = False
        if output.startswith(old_content):
            self.view.insert(edit, self.view.size(), output[len(old_content):])
        else:
            self.view.replace(edit, sublime.Region(0, self.view.size()), output)
            self.view.sel().clear()
            replaced = True

        self.view.set_read_only(True)

        autoscroll = self.get_setting('list_output_auto_scroll', True) is True
        if autoscroll and (replaced or was_at_end):
            self.view.show(self.view.size())


class TestManagerOutputRefreshAllCommand(ApplicationCommand, TestDataHelper):

    def run(self, data_location=None, test=''):
        if not data_location:
            return

        views = find_views_for_test(data_location, test)
        for view in views:
            view.run_command('test_manager_output_refresh')


def refresh_loop(view, refresh_interval):
    if view.window() is None or view.window().active_view() is None or view.id() != view.window().active_view().id():
        return

    view.run_command('test_manager_output_refresh')
    sublime.set_timeout(partial(refresh_loop, view, refresh_interval), refresh_interval)


class TestManagerOutputEventListener(ViewEventListener, SettingsHelper):

    def __init__(self, view):
        self.view = view

    @classmethod
    def is_applicable(cls, settings):
        return settings.get('test_view') == 'output'

    def on_activated(self):
        if self.get_setting('list_update_on_focus', True):
            refresh_interval = self.get_setting('output_refresh_interval', 0.1) * 1000

            self.view.run_command('test_manager_output_refresh')
            sublime.set_timeout(partial(refresh_loop, self.view, refresh_interval), refresh_interval)
