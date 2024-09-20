# coding: utf-8
import os
import logging
import sublime
from .test_data import TestData
from .util import SettingsHelper

logger = logging.getLogger('TestExplorer.helpers')

DEFAULT_TEST_DATA_LOCATION = '.sublime-tests'

NO_PROJECT_DIALOG = ("Could not find an project based on the open files and folders. "
                     "Please make sure to run this command in a window with a loaded project.")

NO_TEST_DATAL_LOCATION_DIALOG = ("No configured location for storing test metadata. Use default?\n\n{}?")

TEST_DATA_LOOKUP = {}

class TestDataHelper(SettingsHelper):
    # Find project and data
    def get_project(self):
        proj = None

        if hasattr(self, 'view') and self.view.window():
            proj = self.get_project_from_window(self.view.window())
        elif hasattr(self, 'window'):
            proj = self.get_project_from_window(self.window)

        return proj

    def get_project_from_window(self, window=None):
        if not window:
            return

        # use the project from the window
        window_proj = window.project_file_name()
        if window_proj:
            return window_proj

    def get_test_data_location(self, project=None):
        location = None

        if hasattr(self, 'view'):
            location = self.get_test_data_location_from_view(self.view)
        elif hasattr(self, 'window'):
            active_view = self.window.active_view()
            if active_view:
                location = self.get_test_data_location_from_view(active_view)
            else:
                location = self.get_test_data_location_from_window(self.window)

        if location is None:
            if not project:
                project = self.get_project()
            if not project:
                sublime.error_message(NO_PROJECT_DIALOG)
                return

            location = self.get_default_test_data_location()
            if not sublime.ok_cancel_dialog(NO_TEST_DATAL_LOCATION_DIALOG.format(location), "Use default location"):
                return

            self.set_test_data_location(location)

        return location

    def get_test_data_location_from_view(self, view=None):
        if view is None:
            return

        # Setting created programmatically when creating a test explorer view.
        # This is already a full path.
        location = view.settings().get('test_data_full_path')
        if location:
            return location

        # Setting from the project file. This is a relative path.
        location = self.get_setting('data_location')
        if location:
            project = self.get_project()
            if project:
                base = os.path.dirname(project)
                location = os.path.normpath(os.path.join(base, location))
                return location

    def get_test_data_location_from_window(self, window=None):
        if not window:
            return

        # Setting from the project file. This is a relative path.
        location = self.get_setting('data_location')
        if location:
            base = os.path.dirname(window.project_file_name())
            location = os.path.normpath(os.path.join(base, location))
            return location

    def get_default_test_data_location(self):
        if not hasattr(self, 'window'):
            sublime.error_message('Cannot run this command without a window')

        data = self.window.project_data()
        base = os.path.dirname(self.window.project_file_name())
        if 'folders' in data and len(data['folders']) > 0 and 'path' in data['folders'][0]:
            base = os.path.join(base, data['folders'][0]['path'])

        return os.path.normpath(os.path.join(base, DEFAULT_TEST_DATA_LOCATION))

    def set_test_data_location(self, location, init=True):
        if not hasattr(self, 'window'):
            sublime.error_message('Cannot run this command without a window')

        base = os.path.dirname(self.window.project_file_name())
        self.set_project_setting('data_location', os.path.relpath(location, start=base))

        if init:
            TestData(location).init()

    def get_test_data(self, location=None):
        if not location:
            location = self.get_test_data_location()
        if not location:
            return

        if not location in TEST_DATA_LOOKUP:
            try:
                TEST_DATA_LOOKUP[location] = TestData(location)
            except Exception as e:
                logger.error(f'error creating TestData: {e}')
                raise

        return TEST_DATA_LOOKUP[location]
