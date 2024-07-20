# coding: utf-8
import os
import logging
import threading
from functools import partial

import sublime
from sublime_plugin import WindowCommand, TextCommand, EventListener

from .util import abbreviate_dir, find_view_by_settings, noop, SettingsHelper
from .cmd import Cmd
from .helpers import TestListHelper, TestProjectHelper


logger = logging.getLogger('TestExplorer.status')

GOTO_DEFAULT = 'list-top'

TEST_EXPLORER_VIEW_TITLE = '*test-explorer*: '
TEST_EXPLORER_VIEW_SYNTAX = 'Packages/TestExplorer/syntax/TestExplorer.tmLanguage'
TEST_EXPLORER_VIEW_SETTINGS = {
    'translate_tabs_to_spaces': False,
    'draw_white_space': 'none',
    'word_wrap': False,
    'test_explorer': True,
}

SECTION_SELECTOR_PREFIX = 'meta.test-explorer.'

TEST_SEPARATOR = '/'

STATUS_SYMBOL = {
    'not_run': '_',
    'failed':  'X',
    'skipped': '-',
    'passed':  '✓'
}

STATUS_NAME = {
    'not_run': 'not-run',
    'failed':  'failed',
    'skipped': 'skipped',
    'passed':  'passed',
    'total':  'total'
}

NO_TESTS_FOUND = "No test found. Press 'r' to run discovery."
NO_TESTS_VISIBLE = "No test to show with the current filters."

TEST_EXPLORER_HELP = """
# View:
#    r = refresh view
#    f = toggle show/hide failed tests
#    i = toggle show/hide skipped tests
#    p = toggle show/hide passed tests
#    n = toggle show/hide new tests
#    a = toggle show/hide all tests
#
# Running:
#    d = run test discovery
#    s = run app/suite/case, S = run all tests"""


NO_PROJECT_DIALOG = ("Could not find an project based on the open files and folders. "
                     "Please make sure to run this command in a window with a loaded project.")

NO_TEST_DATAL_LOCATION_DIALOG = ("No configured location for storing test metadata. Use default?\n\n{}?")

class TestExplorerListBuilder(TestListHelper, SettingsHelper):

    def build_list(self, project):
        status = self.build_test_list(project)

        if self.get_setting('explorer_show_help', True):
            status += TEST_EXPLORER_HELP

        return status

    def add_prefix(self, prefix, add):
        if len(add) == 0 and len(prefix) == 0:
            return ''
        elif len(add) == 0:
            return prefix + TEST_SEPARATOR
        elif len(prefix) == 0:
            return add + TEST_SEPARATOR
        else:
            return prefix + add + TEST_SEPARATOR

    def item_is_visible(self, item, visibility=None):
        if 'children' in item:
            return any(self.item_is_visible(i, visibility=visibility) for i in item['children'])

        return visibility[item['status']]

    def build_items(self, items, depth=0, prefix='', visibility=None):
        if len(items) == 1:
            if 'children' in items[0]:
                return self.build_items(items[0]['children'], depth=depth, prefix=self.add_prefix(prefix, items[0]['name']), visibility=visibility)
            else:
                if self.item_is_visible(items[0], visibility=visibility):
                    return [(items[0], self.build_item(items[0], depth=depth, prefix=prefix))]
                else:
                    return []

        lines = []
        for item in items:
            if self.item_is_visible(item, visibility=visibility):
                lines += [(item, self.build_item(item, depth=depth, prefix=prefix))]
            if 'children' in item:
                lines += self.build_items(item['children'], depth=depth+1, prefix=self.add_prefix(prefix, item['name']), visibility=visibility)

        return lines

    def build_item(self, item, depth=0, prefix=''):
        indent = '  ' * depth
        symbol = f'[{STATUS_SYMBOL[item["status"]]}]'
        fold = '- ' if 'children' in item else '  '
        return f'  {indent}{fold}{symbol} {prefix}{item["name"]}'

    def date_to_string(self, date):
        return '--' if date is None else date.isoformat()

    def stats_to_string(self, stats):
        displays = ['failed', 'skipped', 'passed', 'not_run', 'total']
        return ' | '.join(f'{STATUS_NAME[k]}:{stats[k]}' for k in displays)

    def visible_to_string(self, visibility):
        displays = ['failed', 'skipped', 'passed', 'not_run']
        return ' | '.join(f'[X] {STATUS_NAME[k]}' if visibility[k] else f'[ ] {STATUS_NAME[k]}' for k in displays)

    def build_info(self, item, line, max_length):
        padding = ' ' * (max_length - len(line))
        if 'children' in item:
            return f'{line}{padding}    {self.stats_to_string(self.get_tests_stats(item["children"]))}'
        else:
            return f'{line}{padding}    last-run:{self.date_to_string(item["last_run"])}'

    def build_tests(self, tests, visibility=None):
        lines = self.build_items(tests, depth=0, prefix='', visibility=visibility)
        if len(lines) == 0:
            return []

        max_length = max([len(line) for _, line in lines])
        return [self.build_info(item, line, max_length) for item, line in lines]

    def build_test_list(self, project):
        last_discovery = self.date_to_string(self.get_last_discovery())
        tests = self.get_tests_list(project)
        stats = self.get_tests_stats(tests)
        last_run = self.date_to_string(stats["last_run"])
        visibility = self.view.settings().get('visible_tests')

        status = ''
        status += f'Last discovery: {last_discovery}\n'
        status += f'Last run:       {last_run}\n'
        status += f'Tests status:   {self.stats_to_string(stats)}\n'
        status += f'Showing:        {self.visible_to_string(visibility)}\n'
        status += '\n\n'

        visible_tests = self.build_tests(tests, visibility=visibility)
        if not tests:
            status += NO_TESTS_FOUND + '\n'
        elif not visible_tests:
            status += NO_TESTS_VISIBLE + '\n'
        else:
            status += 'Tests:\n'
            status += '\n'.join(visible_tests)

        # TODO: display something if tests are running?

        status += '\n'

        return status


class TestExplorerTextCmd(Cmd):

    def run(self, edit, *args):
        sublime.error_message("Unimplemented!")

    # status update
    def update_list(self, goto=None):
        self.view.run_command('test_explorer_refresh', {'goto': goto})

    # selection commands
    def get_first_point(self):
        sels = self.view.sel()
        if sels:
            return sels[0].begin()

    def get_all_points(self):
        sels = self.view.sel()
        return [s.begin() for s in sels]

    # line helpers
    def get_selected_line_regions(self):
        sels = self.view.sel()
        selected_lines = []
        for selection in sels:
            lines = self.view.lines(selection)
            for line in lines:
                if self.view.score_selector(line.begin(), 'meta.test-explorer.test-list.line') > 0:
                    selected_lines.append(line)
        return selected_lines

    # test helpers
    def get_selected_item_region(self):
        point = self.get_first_point()
        if not point:
            return None

        line = self.view.line(point)
        for f in self.get_all_leaf_regions():
            if line.contains(f):
                return f

        for f in self.get_all_node_regions():
            if line.contains(f):
                return f

    def get_all_item_regions(self):
        return self.get_all_leaf_regions() + self.get_all_node_regions()

    def get_all_leaf_regions(self):
        return self.view.find_by_selector('meta.test-explorer.test-list.leaf')

    def get_all_node_regions(self):
        return self.view.find_by_selector('meta.test-explorer.test-list.node')

    def get_all_tests(self):
        items = self.get_all_leaf_regions()
        return [self.view.substr(l) for l in items]

    def get_all_folders(self):
        items = self.get_all_node_regions()
        return [self.view.substr(n) for n in items]

    def get_selected_leaf_regions(self):
        items = []
        lines = self.get_selected_line_regions()

        if not lines:
            return items

        for f in self.get_all_leaf_regions():
            items += [f for l in lines if l.contains(f)]

        return items

    def get_selected_tests(self):
        return [self.view.substr(r) for r in self.get_selected_leaf_regions()]

    def get_selected_node_regions(self):
        items = []
        lines = self.get_selected_line_regions()

        if not lines:
            return items

        for f in self.get_all_node_regions():
            items += [f for l in lines if l.contains(f)]

        return items

    def get_selected_folders(self):
        return [self.view.substr(r) for r in self.get_selected_node_regions()]

    def get_selected_item(self):
        r = self.get_selected_item_region()
        return self.view.substr(r) if r else None


class TestExplorerListCommand(WindowCommand, TestExplorerListBuilder):
    """
    Documentation coming soon.
    """

    def run(self, refresh_only=False):
        project = self.get_project(silent=True if refresh_only else False)
        if not project:
            sublime.error_message(NO_PROJECT_DIALOG)

        data_location = self.get_test_data_location()
        if not data_location:
            data_location = self.get_default_test_data_location()
            if not sublime.ok_cancel_dialog(NO_TEST_DATAL_LOCATION_DIALOG.format(data_location), "Use default location"):
                return
            self.set_test_data_location(data_location)

        title = TEST_EXPLORER_VIEW_TITLE + os.path.splitext(os.path.basename(project))[0]

        view = find_view_by_settings(self.window, test_view='list')
        if not view and not refresh_only:
            view = self.window.new_file()

            view.set_name(title)
            view.set_syntax_file(TEST_EXPLORER_VIEW_SYNTAX)
            view.set_scratch(True)
            view.set_read_only(True)

            view.settings().set('test_view', 'list')
            view.settings().set('visible_tests', {'failed': True, 'skipped': True, 'passed': True, 'not_run': True})
            view.settings().set('test_project', project)
            view.settings().set('test_metadata_location', data_location)

            for key, val in list(TEST_EXPLORER_VIEW_SETTINGS.items()):
                view.settings().set(key, val)

        if view is not None:
            self.window.focus_view(view)
            view.run_command('test_explorer_refresh')


class TestExplorerMoveCmd(TestExplorerTextCmd):

    def goto(self, goto):
        what, which, where = self.parse_goto(goto)
        if what == "item":
            self.move_to_item(which, where)
        elif what == 'list-top':
            self.move_to_list_top()
        elif what == "point":
            try:
                point = int(which)
                self.move_to_point(point)
            except ValueError:
                pass

    def parse_goto(self, goto):
        what, which, where = None, None, None
        parts = goto.split(':')
        what = parts[0]
        if len(parts) > 1:
            try:
                which = int(parts[1])
            except ValueError:
                which = parts[1]
        if len(parts) > 2:
            try:
                where = int(parts[2])
            except ValueError:
                where = parts[2]
        return (what, which, where)

    def move_to_point(self, point):
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(point))

        pointrow, _ = self.view.rowcol(point)
        pointstart = self.view.text_point(max(pointrow - 3, 0), 0)
        pointend = self.view.text_point(pointrow + 3, 0)

        pointregion = sublime.Region(pointstart, pointend)

        if pointrow < 10:
            self.view.set_viewport_position((0.0, 0.0), False)
        elif not self.view.visible_region().contains(pointregion):
            self.view.show(pointregion, False)

    def move_to_region(self, region):
        self.move_to_point(self.view.line(region).begin())

    def prev_region(self, regions, point):
        before = [r for r in regions if self.view.line(r).end() < point]
        return before[-1] if before else regions[-1]

    def next_region(self, regions, point):
        after = [r for r in regions if self.view.line(r).begin() > point]
        return after[0] if after else regions[0]

    def next_or_prev_region(self, direction, regions, point):
        if direction == "next":
            return self.next_region(regions, point)
        else:
            return self.prev_region(regions, point)

    def move_to_item(self, which='', where=None):
        tests = [r for r in self.get_all_item_regions() if which == self.view.substr(r)]
        if not tests:
            self.move_to_list_top()
            return

        self.move_to_region(tests[0])

    def move_to_list_top(self):
        regs = self.view.find_by_selector('meta.test-explorer.test-list.node')
        if not regs:
            regs = self.view.find_by_selector('markup.inserted.test-explorer.no-tests')

        if regs:
            self.move_to_region(regs[0])

class TestExplorerReplaceCommand(TextCommand, TestExplorerMoveCmd):

    def is_visible(self):
        return False

    def run(self, edit, goto, tests):
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), tests)
        self.view.set_read_only(True)
        self.view.sel().clear()

        if goto:
            self.goto(goto)
        else:
            self.goto(GOTO_DEFAULT)


class TestExplorerRefreshCommand(TextCommand, TestExplorerTextCmd, TestExplorerListBuilder):

    def is_visible(self):
        return False

    def set_tests(self, goto, tests):
        self.view.run_command('test_explorer_replace', {'goto': goto, 'tests': tests})

    def run(self, edit, goto=None):
        if not self.view.settings().get('test_view') == 'list':
            return

        project = self.get_project()
        if not project:
            return

        goto = None
        selected = self.get_selected_item()
        if selected:
            goto = f'item:{selected}'

        thread = self.worker_run_async(partial(self.build_list, project), on_complete=partial(self.set_tests, goto))
        thread.start()


class TestExplorerDiscoverCommand(TextCommand, TestExplorerTextCmd, TestProjectHelper):

    def is_visible(self):
        return True

    def run(self, edit, goto=None):
        project = self.get_project()
        if not project:
            return

        goto = None
        selected = self.get_selected_item()
        if selected:
            goto = f'item:{selected}'

        thread = self.worker_run_async(partial(self.discover_tests, project), on_complete=partial(self.update_list, goto))
        thread.start()

    def discover_tests(self, project):
        sublime.error_message("Not implemented")


class TestExplorerStartCommand(TextCommand, TestExplorerTextCmd, TestProjectHelper):

    def run(self, edit, start="all"):
        project = self.get_project()
        if not project:
            return

        if start == "item":
            tests = self.get_selected_tests()
            if tests:
                self.start_tests(project, tests)

        elif start == "all":
            self.start_all_tests(project)

    def start_tests(self, project, tests):
        sublime.error_message("Not implemented")

    def start_all_tests(self, project):
        sublime.error_message("Not implemented")


class TestExplorerToggleShowCommand(TextCommand, TestExplorerTextCmd):

    def run(self, edit, toggle="all"):
        visibility = self.view.settings().get('visible_tests')
        if toggle == "all":
            if any([not v for v in visibility.values()]):
                visibility = dict.fromkeys(visibility, True)
            else:
                visibility = dict.fromkeys(visibility, False)
        else:
            visibility[toggle] = not self.view.settings().get('visible_tests')[toggle]

        goto = None
        selected = self.get_selected_item()
        if selected:
            goto = f'item:{selected}'

        self.view.settings().set('visible_tests', visibility)
        self.update_list(goto=goto)

