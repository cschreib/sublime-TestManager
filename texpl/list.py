# coding: utf-8
import datetime
import os
import logging
from datetime import datetime
from functools import partial
from typing import Optional, List, Dict, Tuple

import sublime
from sublime_plugin import ApplicationCommand, WindowCommand, TextCommand

from .util import find_views_by_settings, SettingsHelper
from .cmd import Cmd
from .helpers import TestDataHelper
from .test_data import get_test_stats, TestItem, TestData, TEST_SEPARATOR, RunStatus


logger = logging.getLogger('TestExplorer.status')

GOTO_DEFAULT = 'list-top'

TEST_EXPLORER_VIEW_TITLE = '*test-explorer*: '
TEST_EXPLORER_VIEW_SYNTAX = 'Packages/TestExplorer/syntax/TestExplorer.tmLanguage'
TEST_EXPLORER_VIEW_SETTINGS = {
    'translate_tabs_to_spaces': False,
    'draw_white_space': 'none',
    'draw_unicode_white_space': 'none',
    'word_wrap': False,
    'test_explorer': True,
}

TEST_EXPLORER_DEFAULT_VISIBILITY = {
    'failed': True,
    'crashed': True,
    'stopped': True,
    'skipped': True,
    'passed': True,
    'not_run': True
}

SECTION_SELECTOR_PREFIX = 'meta.test-explorer.'

END_OF_NAME_MARKER = '\u200B'

STATUS_SYMBOL = {
    'not_run': '_',
    'failed':  'X',
    'crashed': '!',
    'stopped': '?',
    'skipped': 'S',
    'passed':  '✓',
    'running': 'R',
    'queued':  'Q'
}

STATUS_NAME = {
    'not_run': 'not-run',
    'failed':  'failed',
    'crashed':  'crashed',
    'stopped':  'stopped',
    'skipped': 'skipped',
    'passed':  'passed',
    'total':  'total'
}

NO_TESTS_FOUND = "No test found. Press 'd' to run discovery."
NO_TESTS_VISIBLE = "No test to show with the current filters."

TEST_EXPLORER_HELP = f"""
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
#    a = toggle show/hide all tests
#
# Legend:
#    [{STATUS_SYMBOL['not_run']}] = not run
#    [{STATUS_SYMBOL['queued']}] = queued
#    [{STATUS_SYMBOL['stopped']}] = stopped
#    [{STATUS_SYMBOL['running']}] = running
#    [{STATUS_SYMBOL['skipped']}] = skipped
#    [{STATUS_SYMBOL['failed']}] = failed
#    [{STATUS_SYMBOL['crashed']}] = crashed
#    [{STATUS_SYMBOL['passed']}] = passed
"""


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
        if item.run_status != RunStatus.NOT_RUNNING:
            return item.run_status.value
        else:
            return item.last_status.value

    def item_is_visible(self, item: TestItem, visibility=None) -> bool:
        if not visibility:
            return True

        if item.children is not None:
            return any(self.item_is_visible(i, visibility=visibility) for i in item.children.values())

        if item.run_status != RunStatus.NOT_RUNNING:
            # Always show running tests
            return True

        return visibility[item.last_status.value]

    def build_items(self, item: TestItem, depth=0, prefix='', visibility=None, hide_parent=False) -> List[Tuple[TestItem, str]]:
        lines = []

        if item.children:
            fold = len(item.children) == 1

            if not hide_parent and not fold and self.item_is_visible(item, visibility=visibility):
                lines += [(item, self.build_item(item, depth=depth, prefix=prefix))]

            if not hide_parent:
                new_depth = depth + 1 if not fold else depth
                new_prefix = self.add_prefix(prefix, item.name)
            else:
                new_depth = depth
                new_prefix = ''

            for child in item.children.values():
                lines += self.build_items(child, depth=new_depth, prefix=new_prefix, visibility=visibility)
        else:
            if not hide_parent and self.item_is_visible(item, visibility=visibility):
                lines += [(item, self.build_item(item, depth=depth, prefix=prefix))]

        return lines

    def build_item(self, item: TestItem, depth=0, prefix='') -> str:
        indent = '  ' * depth
        symbol = f'[{STATUS_SYMBOL[self.item_display_status(item)]}]'
        fold = '- ' if item.children is not None else '  '
        return f'  {indent}{fold}{symbol} {END_OF_NAME_MARKER}{prefix}{item.name}{END_OF_NAME_MARKER}'

    def date_to_string(self, date: Optional[datetime]) -> str:
        return '--' if date is None else date.isoformat()

    def stats_to_string(self, stats) -> str:
        stats['failed'] += stats['crashed']
        stats['not_run'] += stats['stopped']
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

        lines = self.build_items(root, depth=0, prefix='', visibility=visibility, hide_parent=True)
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

    def get_all_tests(self) -> List[str]:
        items = self.get_all_leaf_regions()
        return [self.view.substr(l) for l in items]

    def get_all_folders(self) -> List[str]:
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

    def get_selected_tests(self) -> List[str]:
        return [self.view.substr(r) for r in self.get_selected_leaf_regions()]

    def get_selected_node_regions(self):
        items = []
        lines = self.get_selected_line_regions()

        if not lines:
            return items

        for f in self.get_all_node_regions():
            items += [f for l in lines if l.contains(f)]

        return items

    def get_selected_folders(self) -> List[str]:
        return [self.view.substr(r) for r in self.get_selected_node_regions()]

    def get_selected_item(self) -> Optional[List[str]]:
        r = self.get_selected_item_region()
        return self.view.substr(r) if r else None


class TestExplorerRefreshAllCommand(ApplicationCommand, TestDataHelper):

    def run(self, data_location=None):
        if not data_location:
            data_location = self.get_test_data_location()
        if not data_location:
            return

        logger.debug(f'refreshing lists with location: {data_location}')

        views = find_views_by_settings(test_view='list', test_data_full_path=data_location)
        for view in views:
            view.run_command('test_explorer_refresh')


class TestExplorerListCommand(WindowCommand, TestDataHelper):
    """
    Documentation coming soon.
    """

    def run(self, data_location=None):
        if not data_location:
            data_location = self.get_test_data_location()
        if not data_location:
            return

        logger.debug(f'opening list with location: {data_location}')

        views = find_views_by_settings(test_view='list', test_data_full_path=data_location)
        if not views:
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

            separators = view.settings().get('word_separators', '')
            view.settings().set('word_separators', separators + END_OF_NAME_MARKER)

            for key, val in list(TEST_EXPLORER_VIEW_SETTINGS.items()):
                view.settings().set(key, val)

            views = [view]

        for view in views:
            view.run_command('test_explorer_refresh')

        if views:
            views[0].window().focus_view(views[0])
            views[0].window().bring_to_front()


class TestExplorerMoveCmd(TestExplorerTextCmd):

    def goto(self, goto):
        parts = goto.split(':')
        if parts[0] == 'item':
            self.move_to_item(':'.join(parts[1:]))
        elif parts[0] == 'list-top':
            self.move_to_list_top()
        elif parts[0] == "point":
            try:
                point = int(parts[1])
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

    def refresh(self, data, goto):
        try:
            tests = self.build_list(data)
        except Exception as e:
            logger.error('error building test list: {}'.format(str(e)))
            raise

        self.view.run_command('test_explorer_replace', {'goto': goto, 'tests': tests})

    def run(self, edit):
        if not self.view.settings().get('test_view') == 'list':
            return

        data = self.get_test_data()
        if not data:
            return

        logger.debug(f'refreshing list with location: {data.location}')

        goto = None
        selected = self.get_selected_item()
        if selected:
            goto = f'item:{selected}'

        sublime.set_timeout(partial(self.refresh, data, goto))


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
            if toggle == 'failed':
                visibility['crashed'] = visibility['failed']
            if toggle == 'not_run':
                visibility['stopped'] = visibility['not_run']

        self.view.settings().set('visible_tests', visibility)
        self.view.run_command('test_explorer_refresh')


class TestExplorerOpenFile(TextCommand, TestExplorerTextCmd, TestDataHelper, SettingsHelper):

    def is_visible(self):
        return False

    def run(self, edit):
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
            logger.debug(f'opening {test}...')
            item = data.get_test_list().find_test(test.split(TEST_SEPARATOR))
            if not item:
                logger.warning(f'{test} not found in list')
                continue

            location = item.location
            if location is None:
                logger.warning(f'no location for {item.name}')
                continue

            filename = os.path.join(root_folder, location.file)
            if not os.path.exists(filename):
                logger.warning(f'{filename} does not exists')
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
