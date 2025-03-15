# coding: utf-8
import datetime
import sys
from os import path
import logging
from datetime import datetime
from typing import Optional

import sublime
from sublime_plugin import TextCommand

logger = logging.getLogger('TestExplorer.util')

# Constants

SETTINGS_FILE = 'TestExplorer.sublime-settings'
SETTINGS_ROOT = 'TestExplorer'


# Compatibility

PY2 = sys.version_info[0] == 2

text_type = str
string_types = (str,)
unichr = chr


# Callback helpers

def noop(*args, **kwargs):
    pass


# View helpers

def find_views_for_data(data_path):
    views = []
    for window in sublime.windows():
        for view in window.views():
            s = view.settings()
            if 'test_view' in s and s['test_view'] == 'list' and s['test_data_full_path'] == data_path:
                views.append(view)

    return views


def find_views_for_test(data_path, test):
    views = []
    for window in sublime.windows():
        for view in window.views():
            s = view.settings()
            if 'test_view' in s and \
                    s['test_view'] == 'output' and \
                    s['test_data_full_path'] == data_path and \
                    s['test_output'] == test:
                views.append(view)

    return views

# progress helper


class StatusSpinner(object):

    SIZE = 10  # 10 equal signs
    TIME = 50  # 50 ms delay

    def __init__(self, thread, msg):
        self.counter = 0
        self.direction = 1
        self.msg = msg
        self.thread = thread

    def progress(self):
        if not self.thread.is_alive():
            sublime.status_message('')
            return

        left, right = self.counter, (self.SIZE - 1 - self.counter)
        self.counter += self.direction
        if self.counter in (0, self.SIZE - 1):
            self.direction *= -1

        status = "[%s=%s] %s" % (' ' * left, ' ' * right, self.msg)

        sublime.status_message(status)
        sublime.set_timeout(self.progress, self.TIME)

    def start(self):
        self.thread.start()
        sublime.set_timeout(self.progress, 0)


# Panel Helper

class TestExplorerPanelWriteCommand(TextCommand):

    def is_visible(self):
        return False

    def run(self, edit, content=''):
        self.view.set_read_only(False)
        if self.view.size() > 0:
            self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, content)
        self.view.set_read_only(True)


class TestExplorerPanelAppendCommand(TextCommand):

    def is_visible(self):
        return False

    def run(self, edit, content='', scroll=False):
        self.view.insert(edit, self.view.size(), content)
        if scroll:
            self.view.show(self.view.size())


# Directory helpers

def get_user_dir():
    user_dir = ''
    try:
        user_dir = path.expanduser(u'~')
    except:
        try:
            user_dir = path.expanduser('~')
        except:
            pass

    if PY2 and isinstance(user_dir, str):
        try:
            user_dir = user_dir.decode('utf-8')
        except:
            pass

    return user_dir


def abbreviate_dir(dirname):
    user_dir = get_user_dir()
    try:
        if dirname.startswith(user_dir):
            dirname = u'~%s' % dirname[len(user_dir):]
    except:
        pass
    return dirname


# Date helpers

def readable_date_delta(from_date: datetime, until_date: Optional[datetime] = None):
    # From https://stackoverflow.com/a/5333305

    if until_date is None:
        until_date = datetime.now()

    delta = until_date - from_date

    # deltas store time as seconds and days, we have to get hours and minutes ourselves
    delta_minutes = delta.seconds // 60
    delta_hours = delta_minutes // 60
    delta_minutes = delta_minutes % 60

    def plur(it: int):
        return '' if it == 1 else 's'

    # show a fuzzy but useful approximation of the time delta
    if delta.days:
        return '%d day%s ago' % (delta.days, plur(delta.days))
    elif delta_hours:
        return '%d hour%s %d minute%s ago' % (delta_hours, plur(delta_hours), delta_minutes, plur(delta_minutes))
    elif delta_minutes:
        return '%d minute%s ago' % (delta_minutes, plur(delta_minutes))
    else:
        return '%d second%s ago' % (delta.seconds, plur(delta.seconds))

# settings helpers


global_settings = {}


class SettingsHelper(object):

    def load_settings(self):
        self.settings = sublime.load_settings(SETTINGS_FILE).to_dict()

        if hasattr(self, 'view'):
            local_settings = self.view.settings().get(SETTINGS_ROOT, {})
        else:
            if hasattr(self, 'window'):
                window = self.window
            else:
                window = sublime.active_window()

            if window.active_view():
                local_settings = window.active_view().settings().get(SETTINGS_ROOT, {})
            else:
                local_settings = window.settings().get(SETTINGS_ROOT, {})

        for k, v in local_settings.items():
            self.settings[k] = v

    def get_settings(self):
        # TODO: avoid reloading all the time; maybe there's a way to trigger?
        self.load_settings()
        return self.settings

    def get_setting(self, key, default=None):
        settings = self.get_settings()
        return settings[key] if key in settings else default

    def set_view_setting(self, key, value):
        if not hasattr(self, 'view'):
            sublime.error_message('Can only be called on views')

        local_settings = self.view.settings().get(SETTINGS_ROOT, {})
        local_settings[key] = value

        self.view.settings().set(SETTINGS_ROOT, local_settings)

    def set_project_setting(self, key, value):
        if hasattr(self, 'view'):
            window = self.view().window()
        else:
            window = self.window

        data = window.project_data()
        local_settings = data.setdefault('settings', {}).setdefault(SETTINGS_ROOT, {})
        local_settings[key] = value
        window.set_project_data(data)

# General helpers

def merge_deep(dict1, dict2):
    for k, v in dict2.items():
        if not k in dict1 or not isinstance(v, dict):
            dict1[k] = v
            continue

        merge_deep(dict1[k], v)
