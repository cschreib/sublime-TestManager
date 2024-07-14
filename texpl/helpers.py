# coding: utf-8
import re
import os
import logging
from datetime import datetime
import sublime

logger = logging.getLogger('TestExplorer.helpers')

DEFAULT_TEST_DATA_LOCATION = '.sublime-tests'

def datetime_to_iso(time):
    return time.strftime('')

last_discovery = datetime.fromisoformat('2024-05-04T11:05:12')
tests_list = [
            {'name': 'Test.exe', 'status': 'failed', 'children': [
                {'name': 'TestCase1', 'status': 'failed', 'children': [
                    {'name': 'test_this', 'status': 'passed', 'last_run': datetime.fromisoformat('2024-05-04T12:05:12')},
                    {'name': 'test_that', 'status': 'failed', 'last_run': datetime.fromisoformat('2024-05-04T11:05:12')},
                    {'name': 'test_them', 'status': 'skipped', 'last_run': datetime.fromisoformat('2024-05-04T11:05:14')},
                    {'name': 'test_new', 'status': 'not_run', 'last_run': None},
                ]},
                {'name': 'TestCase2', 'status': 'passed', 'children': [
                    {'name': 'test_me', 'status': 'passed', 'last_run': datetime.fromisoformat('2024-05-03T13:05:12')}
                ]},
                {'name': 'TestCase3', 'status': 'passed', 'children': [
                    {'name': 'test_me', 'status': 'passed', 'last_run': datetime.fromisoformat('2024-05-04T12:05:12')},
                    {'name': 'test_me', 'status': 'passed', 'last_run': datetime.fromisoformat('2024-05-04T12:05:12')},
                    {'name': 'test_me', 'status': 'passed', 'last_run': datetime.fromisoformat('2024-05-04T12:05:12')},
                ]}
            ]}
        ]

class TestProjectHelper(object):
    # Find project and data
    def get_project(self, silent=False):
        proj = None

        if hasattr(self, 'view'):
            proj = self.get_project_from_view(self.view, silent=silent)
            if self.view.window() and not proj:
                proj = self.get_project_from_window(self.view.window(), silent=silent)
        elif hasattr(self, 'window'):
            proj = self.get_project_from_window(self.window, silent=silent)

        return proj

    def get_project_from_view(self, view=None, silent=True):
        if view is None:
            return

        # first try the view settings (for things like status, diff, etc)
        view_proj = view.settings().get('test_project')
        if view_proj:
            logger.info('get_project_from_view(view=%s, silent=%s): %s (view settings)', view.id(), silent, view_proj)
            return view_proj

    def get_project_from_window(self, window=None, silent=True):
        if not window:
            logger.info('get_project_from_window(window=%s, silent=%s): None (no window)', None, silent)
            return

        active_view = window.active_view()
        if active_view is not None:
            # if the active view has a setting, use that
            active_view_project = active_view.settings().get('test_project')
            if active_view_project:
                logger.info('get_project_from_window(window=%s, silent=%s): %s (view settings)', window.id(), silent, active_view_project)
                return active_view_project

        # use the project from the window
        window_proj = window.project_file_name()
        if window_proj:
            logger.info('get_project_from_window(window=%s, silent=%s): %s (window project)', window.id(), silent, window_proj)
            return window_proj

        if silent:
            logger.info('get_project_from_window(window=%s, silent=%s): None (silent)', window.id(), silent)
            return

    def get_test_data_location(self, silent=False):
        location = None

        if hasattr(self, 'view'):
            location = self.get_test_data_location_from_view(self.view, silent=silent)
            if self.view.window() and not location:
                location = self.get_test_data_location_from_window(self.view.window(), silent=silent)
        elif hasattr(self, 'window'):
            proj = self.get_test_data_location_from_window(self.window, silent=silent)

        return location

    def get_test_data_location_from_view(self, view=None, silent=True):
        if view is None:
            return

        # first try the view settings (for things like status, diff, etc)
        location = view.settings().get('test_metadata_location')
        if location:
            logger.info('get_test_data_location_from_view(view=%s, silent=%s): %s (view settings)', view.id(), silent, location)
            return location

    def get_test_data_location_from_window(self, window=None, silent=True):
        if not window:
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): None (no window)', None, silent)
            return

        active_view = window.active_view()
        if active_view is not None:
            # if the active view has a setting, use that
            location = active_view.settings().get('test_metadata_location')
            if location:
                logger.info('get_test_data_location_from_window(window=%s, silent=%s): %s (view settings)', window.id(), silent, location)
                return location

        # Read the location from the project file
        data = window.project_data()
        if 'settings' in data and 'test_metadata_location' in data['settings']:
            base = os.path.dirname(self.window.project_file_name())
            location = os.path.join(base, data['settings']['test_explorer_metadata_location'])
            logger.info('get_test_data_location_from_window(window=%s, silent=%s): %s (window project)', window.id(), silent, location)
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

    def set_test_data_location(self, location):
        if not hasattr(self, 'window'):
            sublime.error_message('Cannot run this command without a window')

        base = os.path.dirname(self.window.project_file_name())

        data = self.window.project_data()
        if not 'settings' in data:
            data['settings'] = {}
        data['settings']['test_explorer_metadata_location'] = os.path.relpath(location, start=base)
        self.window.set_project_data(data)

    # Test data
    def get_last_discovery(self, project=None):
        if project is None:
            project = self.get_project()

        global last_discovery
        return last_discovery

    def get_tests_list(self, project=None):
        if project is None:
            project = self.get_project()

        global tests_list
        return tests_list

    def find_test(self):
        lst = self.get_tests_list()
        for p in item_path:
            found = None
            if lst is None:
                break

            for item in lst:
                if item['name'] == p:
                    found = item
                    break

            if found is None:
                return None

            if 'children' in found:
                lst = found['children']
            else:
                lst = None

        return found


class TestListHelper(TestProjectHelper):

    def get_tests_stats(self, tests, total_stats=None):
        for item in tests:
            if 'children' in item:
                total_stats = self.get_tests_stats(item['children'], total_stats=total_stats)
            else:
                total_stats = self.add_to_stats(total_stats, item)

        return total_stats

    def add_to_stats(self, stats, item):
        if stats is None:
            stats = {'failed': 0, 'skipped': 0, 'passed': 0, 'not_run': 0, 'total': 0, 'last_run': None}

        stats[item['status']] += 1
        stats['total'] += 1
        if item['last_run'] is not None:
            if stats['last_run'] is not None:
                stats['last_run'] = max(stats['last_run'], item['last_run'])
            else:
                stats['last_run'] = item['last_run']

        return stats
