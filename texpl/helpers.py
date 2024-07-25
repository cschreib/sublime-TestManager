# coding: utf-8
import os
import logging
import sublime
from .test_data import TestData

logger = logging.getLogger('TestExplorer.helpers')

DEFAULT_TEST_DATA_LOCATION = '.sublime-tests'

NO_PROJECT_DIALOG = ("Could not find an project based on the open files and folders. "
                     "Please make sure to run this command in a window with a loaded project.")

NO_TEST_DATAL_LOCATION_DIALOG = ("No configured location for storing test metadata. Use default?\n\n{}?")


class TestDataHelper(object):
    # Find project and data
    def get_project(self, silent=False):
        proj = None

        if hasattr(self, 'view') and self.view.window():
            proj = self.get_project_from_window(self.view.window(), silent=silent)
        elif hasattr(self, 'window'):
            proj = self.get_project_from_window(self.window, silent=silent)

        return proj

    def get_project_from_window(self, window=None, silent=True):
        if not window:
            logger.info('get_project_from_window(window=%s, silent=%s): None (no window)', None, silent)
            return

        # use the project from the window
        window_proj = window.project_file_name()
        if window_proj:
            logger.info('get_project_from_window(window=%s, silent=%s): %s (window project)', window.id(), silent, window_proj)
            return window_proj

        if silent:
            logger.info('get_project_from_window(window=%s, silent=%s): None (silent)', window.id(), silent)
            return

    def get_test_data_location(self, project=None, silent=False):
        location = None

        if hasattr(self, 'view'):
            location = self.get_test_data_location_from_view(self.view, silent=silent)
        elif hasattr(self, 'window'):
            active_view = self.window.active_view()
            if active_view:
                location = self.get_test_data_location_from_view(active_view, silent=silent)
            else:
                location = self.get_test_data_location_from_window(self.window, silent=silent)

        if location is None:
            if not project:
                project = self.get_project(silent=silent)
            if not project:
                sublime.error_message(NO_PROJECT_DIALOG)
                return

            location = self.get_default_test_data_location()
            if not sublime.ok_cancel_dialog(NO_TEST_DATAL_LOCATION_DIALOG.format(location), "Use default location"):
                return

            self.set_test_data_location(location)

        return location

    def get_test_data_location_from_view(self, view=None, silent=True):
        if view is None:
            return

        # Setting created programmatically when creating a test explorer view.
        # This is already a full path.
        location = view.settings().get('test_data_full_path')
        if location:
            logger.info('get_test_data_location_from_view(view=%s, silent=%s): %s (view settings)', view.id(), silent, location)
            return location

        # Setting from the project file. This is a relative path.
        location = view.settings().get('test_explorer_data_location')
        if location:
            logger.info('get_test_data_location_from_view(view=%s, silent=%s): %s (view settings)', view.id(), silent, location)
            project = self.get_project(silent=silent)
            if project:
                base = os.path.dirname(project)
                location = os.path.normpath(os.path.join(base, location))
                return location

        if silent:
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): None (silent)', window.id(), silent)
            return

    def get_test_data_location_from_window(self, window=None, silent=True):
        if not window:
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): None (no window)', None, silent)
            return

        # Setting from the project file. This is a relative path.
        location = window.settings().get('test_explorer_data_location')
        if location:
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): %s (window settings)', window.id(), silent, location)
            base = os.path.dirname(window.project_file_name())
            location = os.path.normpath(os.path.join(base, location))
            return location

        if silent:
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): None (silent)', window.id(), silent)
            return

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

        data = self.window.project_data()
        if not 'settings' in data:
            data['settings'] = {}
        data['settings']['test_explorer_data_location'] = os.path.relpath(location, start=base)
        self.window.set_project_data(data)

        if init:
            TestData(location).init()

    def get_test_data(self, location=None):
        if not location:
            location = self.get_test_data_location(silent=True)
        if not location:
            return

        return TestData(location)
