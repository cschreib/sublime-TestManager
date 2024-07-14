# coding: utf-8
import re
import os
import logging
from datetime import datetime
import sublime

logger = logging.getLogger('TestExplorer.helpers')


NO_PROJECT_DIALOG = ("Could not find an project based on the open files and folders. Please make sure to run this command in a window with a loaded project.")


class TestProjectHelper(object):
    # working dir remake
    def get_dir_from_view(self, view=None):
        d = None
        if view is not None and view.file_name():
            d = os.path.realpath(os.path.dirname(view.file_name()))
            logger.info('get_dir_from_view(view=%s): %s', view.id(), d)
        return d

    def get_dirs_from_window_folders(self, window=None):
        dirs = set()
        if window is not None:
            dirs = set(f for f in window.folders())
            logger.info('get_dirs_from_window_folders(window=%s): %s', window.id(), dirs)
        return dirs

    def get_dirs_from_window_views(self, window=None):
        dirs = set()
        if window is not None:
            view_dirs = [self.get_dir_from_view(v) for v in window.views()]
            dirs = set(d for d in view_dirs if d)
            logger.info('get_dirs_from_window_views(window=%s): %s', window.id(), dirs)
        return dirs

    def get_dirs(self, window=None):
        dirs = set()
        if window is not None:
            dirs |= self.get_dirs_from_window_folders(window)
            dirs |= self.get_dirs_from_window_views(window)
            logger.info('get_dirs(window=%s): %s', window.id(), dirs)
        return dirs

    def get_dirs_prioritized(self, window=None):
        dirs = list()
        if window is not None:
            all_dirs = self.get_dirs(window)
            active_view_dir = self.get_dir_from_view(window.active_view())
            if active_view_dir:
                dirs.append(active_view_dir)
                all_dirs.discard(active_view_dir)
            for d in sorted(list(all_dirs), key=lambda x: len(x), reverse=True):
                dirs.append(d)
            logger.info('get_dirs_prioritized(window=%s): %s', window.id(), dirs)
        return dirs

    # path walking
    def all_dirnames(self, directory):
        dirnames = [directory]
        while directory and directory != os.path.dirname(directory):
            directory = os.path.dirname(directory)
            dirnames.append(directory)

        logger.info('all_dirs(directory=%s): %s', directory, dirnames)
        return dirnames

    # projects
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

        sublime.error_message(NO_PROJECT_DIALOG)


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

class TestListHelper(object):

    def get_last_discovery(self):
        global last_discovery
        return last_discovery

    def get_tests_list(self, project):
        global tests_list
        return tests_list

    def find_item(self, lst, item_path):
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
