# coding: utf-8
import datetime
import os
import logging
from datetime import datetime
from functools import partial
from typing import Optional, List, Dict, Tuple

import sublime
from sublime_plugin import WindowCommand, TextCommand

from .util import find_views_by_settings, SettingsHelper
from .cmd import Cmd
from .helpers import TestDataHelper
from .test_data import get_test_stats, TestItem, TestData


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

TEST_EXPLORER_DEFAULT_VISIBILITY = {
    'failed': True,
    'skipped': True,
    'passed': True,
    'not_run': True
}

SECTION_SELECTOR_PREFIX = 'meta.test-explorer.'

TEST_SEPARATOR = '/'

STATUS_SYMBOL = {
    'not_run': '_',
    'failed':  'X',
    'skipped': 'S',
    'passed':  '✓',
    'running': 'R',
    'queued':  'Q'
}

STATUS_NAME = {
    'not_run': 'not-run',
    'failed':  'failed',
    'skipped': 'skipped',
    'passed':  'passed',
    'total':  'total'
}

NO_TESTS_FOUND = "No test found. Press 'd' to run discovery."
NO_TESTS_VISIBLE = "No test to show with the current filters."

TEST_EXPLORER_HELP = """
# Running:
#    d = run test discovery
#    s = run app/suite/case, S = run all tests
#    C = stop tests
#
# Other:
#    enter = open test file
#
# View:
#    r = refresh view
#    f = toggle show/hide failed tests
#    i = toggle show/hide skipped tests
#    p = toggle show/hide passed tests
#    n = toggle show/hide new tests
#    a = toggle show/hide all tests"""


class TestExplorerListBuilder(TestDataHelper, SettingsHelper):

    def build_list(self, data: TestData) -> str:
        status = self.build_test_list(data)

        if self.get_setting('explorer_show_help', True):
            status += TEST_EXPLORER_HELP

        return status

    def add_prefix(self, prefix: str, add: str) -> str:
        if len(add) == 0 and len(prefix) == 0:
            return ''
        elif len(add) == 0:
            return prefix + TEST_SEPARATOR
        elif len(prefix) == 0:
            return add + TEST_SEPARATOR
        else:
            return prefix + add + TEST_SEPARATOR

    def item_display_status(self, item: TestItem) -> str:
        if item.run_status != 'not_running':
            return item.run_status
        else:
            return item.last_status

    def item_is_visible(self, item: TestItem, visibility=None) -> bool:
        if not visibility:
            return True

        if item.children is not None:
            return any(self.item_is_visible(i, visibility=visibility) for i in item.children.values())

        if item.run_status != 'not_running':
            # Always show running tests
            return True

        return visibility[item.last_status]

    def build_items(self, items: Dict[str, TestItem], depth=0, prefix='', visibility=None) -> List[Tuple[TestItem, str]]:
        if len(items) == 1:
            item = next(iter(items.values()))
            if item.children is not None:
                return self.build_items(item.children, depth=depth, prefix=self.add_prefix(prefix, item.name), visibility=visibility)
            else:
                if self.item_is_visible(item, visibility=visibility):
                    return [(item, self.build_item(item, depth=depth, prefix=prefix))]
                else:
                    return []

        lines = []
        for item in items.values():
            if self.item_is_visible(item, visibility=visibility):
                lines += [(item, self.build_item(item, depth=depth, prefix=prefix))]
            if item.children is not None:
                lines += self.build_items(item.children, depth=depth+1, prefix=self.add_prefix(prefix, item.name), visibility=visibility)

        return lines

    def build_item(self, item: TestItem, depth=0, prefix='') -> str:
        indent = '  ' * depth
        symbol = f'[{STATUS_SYMBOL[self.item_display_status(item)]}]'
        fold = '- ' if item.children is not None else '  '
        return f'  {indent}{fold}{symbol} {prefix}{item.name}'

    def date_to_string(self, date: Optional[datetime]) -> str:
        return '--' if date is None else date.isoformat()

    def stats_to_string(self, stats) -> str:
        displays = ['failed', 'skipped', 'passed', 'not_run', 'total']
        return ' | '.join(f'{STATUS_NAME[k]}:{stats[k]}' for k in displays)

    def visible_to_string(self, visibility) -> str:
        displays = ['failed', 'skipped', 'passed', 'not_run']
        return ' | '.join(f'[X] {STATUS_NAME[k]}' if visibility[k] else f'[ ] {STATUS_NAME[k]}' for k in displays)

    def build_info(self, item: TestItem, line: str, max_length: int):
        padding = ' ' * (max_length - len(line))
        if item.children is not None:
            return f'{line}{padding}    {self.stats_to_string(get_test_stats(item))}'
        else:
            return f'{line}{padding}    last-run:{self.date_to_string(item.last_run)}'

    def build_tests(self, root: TestItem, visibility=None):
        assert root.children is not None

        lines = self.build_items(root.children, depth=0, prefix='', visibility=visibility)
        if len(lines) == 0:
            return []

        max_length = max([len(line) for _, line in lines])
        return [self.build_info(item, line, max_length) for item, line in lines]

    def build_test_list(self, data: TestData):
        last_discovery = self.date_to_string(data.get_last_discovery())
        tests_list = data.get_test_list()
        stats = data.get_global_test_stats()
        last_run = self.date_to_string(stats["last_run"])
        visibility = self.view.settings().get('visible_tests')

        status = ''
        status += f'Last discovery: {last_discovery}\n'
        status += f'Last run:       {last_run}\n'
        status += f'Tests status:   {self.stats_to_string(stats)}\n'
        status += f'Showing:        {self.visible_to_string(visibility)}\n'
        status += '\n\n'

        visible_tests = self.build_tests(tests_list.root, visibility=visibility)
        if tests_list.is_empty():
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

    def run(self, refresh_only=False, data_location=None):
        if not data_location:
            data_location = self.get_test_data_location()
        if not data_location:
            return

        views = find_views_by_settings(test_view='list', test_data_full_path=data_location)
        if not views and not refresh_only:
            view = self.window.new_file()

            project = self.get_project()
            assert project is not None

            title = TEST_EXPLORER_VIEW_TITLE + os.path.splitext(os.path.basename(project))[0]
            view.set_name(title)
            view.set_syntax_file(TEST_EXPLORER_VIEW_SYNTAX)
            view.set_scratch(True)
            view.set_read_only(True)

            view.settings().set('test_view', 'list')
            view.settings().set('visible_tests', TEST_EXPLORER_DEFAULT_VISIBILITY)
            view.settings().set('test_data_full_path', data_location)

            for key, val in list(TEST_EXPLORER_VIEW_SETTINGS.items()):
                view.settings().set(key, val)

            views = [view]

        for view in views:
            view.run_command('test_explorer_refresh')

        if views and not refresh_only:
            views[0].window().focus_view(views[0])
            views[0].window().bring_to_front()


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

    def run(self, edit):
        if not self.view.settings().get('test_view') == 'list':
            return

        data = self.get_test_data()
        if not data:
            return

        goto = None
        selected = self.get_selected_item()
        if selected:
            goto = f'item:{selected}'

        thread = self.worker_run_async(partial(self.build_list, data), on_complete=partial(self.set_tests, goto))
        thread.start()


class TestExplorerToggleShowCommand(TextCommand, TestExplorerTextCmd):

    def is_visible(self):
        return False

    def run(self, edit, toggle="all"):
        visibility = self.view.settings().get('visible_tests')
        if toggle == "all":
            if any([not v for v in visibility.values()]):
                visibility = dict.fromkeys(visibility, True)
            else:
                visibility = dict.fromkeys(visibility, False)
        else:
            visibility[toggle] = not self.view.settings().get('visible_tests')[toggle]

        self.view.settings().set('visible_tests', visibility)
        self.view.run_command('test_explorer_refresh')


class TestExplorerOpenFile(TextCommand, TestExplorerTextCmd, TestDataHelper, SettingsHelper):

    def is_visible(self):
        return False

    def run(self, edit, toggle="all"):
        data = self.get_test_data()
        if not data:
            return

        project = self.get_project()
        if not project:
            return

        root_folder = os.path.dirname(project)
        transient = self.get_setting('explorer_open_files_transient', True) is True
        tests = self.get_selected_tests()
        window = self.view.window()

        for test in tests:
            item = data.get_test_list().find_test(test.split(TEST_SEPARATOR))
            if not item:
                continue

            location = item.location
            if location is None:
                continue

            filename = os.path.join(root_folder, location.file)
            if not os.path.exists(filename):
                logger.warning('f{filename} does not exists')
                continue

            location = f'{filename}:{location.line}'
            if transient:
                window.open_file(location, sublime.ENCODED_POSITION | sublime.TRANSIENT)
            else:
                window.open_file(location, sublime.ENCODED_POSITION)


class TestExplorerStartSelectedCommand(TextCommand, TestExplorerTextCmd):

    def is_visible(self):
        return False

    def run(self, edit, start="all"):
        if start == "item":
            tests = self.get_selected_tests()
            if tests:
                self.start_tests(tests)
        elif start == "all":
            self.start_all_tests()

    def start_tests(self, tests):
        self.view.run_command('test_explorer_start_command', {'start': 'list', 'tests': tests})

    def start_all_tests(self):
        self.view.run_command('test_explorer_start_command', {'start': 'all'})
