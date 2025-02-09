# coding: utf-8
import os
import logging
from datetime import datetime
from functools import partial
from typing import Callable, Optional, List, Dict, Tuple

import sublime
from sublime_plugin import ApplicationCommand, WindowCommand, TextCommand, EventListener

from .util import find_views_for_data, SettingsHelper, readable_date_delta
from .helpers import TestDataHelper
from .test_data import ROOT_NAME, TestList, get_test_stats, TestItem, TestData, RunStatus, test_name_to_path, test_path_to_name


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
#    k = stop tests
#
# Other:
#    enter = open test file
#    o = open test run output
#
# View:
#    r = refresh view
#    f = toggle show/hide failed tests
#    i = toggle show/hide skipped tests
#    p = toggle show/hide passed tests
#    n = toggle show/hide new tests
#    a = toggle show/hide all tests
#    e = focus on test executable/suite
#    backspace = focus on parent test executable/suite
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

    def build_list(self, data: TestData) -> Tuple[str, Dict[str,int]]:
        status = ''
        line_count = 0
        structure = {}

        def add_line(line: str):
            nonlocal status
            nonlocal line_count

            status += line
            status += '\n'
            line_count += 1

        # Build the header.
        for line in self.build_header(data):
            add_line(line)

        add_line('')
        add_line('')

        # Fetch settings.
        visibility = self.view.settings().get('visible_tests')
        settings = self.get_settings()
        column_width_percentile = settings.get('list_column_width_percentile', 0.95)
        column_width_factor = settings.get('list_column_width_factor', 1.1)
        sort_key_name = settings.get('list_sort_key', 'name')
        focus_test_path = self.view.settings().get('focus_test_path')

        # Now build the actual test list.
        tests_list = data.get_test_list()
        focus_test = tests_list.find_test(focus_test_path)
        if focus_test is None:
            focus_test = tests_list.root
            focus_test_path = []
            self.view.settings().set('focus_test_path', focus_test_path)

        sort_key = (lambda c: c.discovery_id) if sort_key_name == 'discovery' else (lambda c: c.full_name)
        visible_tests, max_length = self.build_tests(tests_list,
                                                     focus_test_path,
                                                     sort_key,
                                                     visibility=visibility,
                                                     column_width_percentile=column_width_percentile,
                                                     column_width_factor=column_width_factor)
        structure['max_length'] = max_length

        if tests_list.is_empty():
            add_line(NO_TESTS_FOUND)
        elif not visible_tests:
            add_line(NO_TESTS_VISIBLE)
        else:
            add_line('Tests:')

            line_ids = {}
            test_ids = {}
            for test, line in visible_tests:
                line_ids[test] = line_count
                test_ids[str(line_count)] = test
                add_line(line)

            structure['test_lines'] = line_ids
            structure['line_tests'] = test_ids

        add_line('')

        # Add help text.
        if settings.get('explorer_show_help', True):
            for line in TEST_EXPLORER_HELP.split('\n'):
                add_line(line)

        return status, structure

    def update_list(self, data: TestData, structure: dict, hint: List[str]) -> List[Tuple[int, str]]:
        lines = []

        def add_line(line: int, content: str):
            nonlocal lines
            lines.append((line, content))

        # Already rebuild the header; it's cheap and changes all the time anyway.
        line_count = 0
        for line in self.build_header(data):
            add_line(line_count, line)
            line_count += 1

        with data.mutex:
            # Now rebuild the lines for the selected tests
            test_lines = structure['test_lines']
            max_length = structure['max_length']
            for test in hint:
                line = test_lines.get(test)
                if line is None:
                    continue

                path = test_name_to_path(test)
                item = data.tests.find_test(path)
                if item is None:
                    continue

                content = self.build_item(item, self.item_depth(path))
                add_line(line, self.build_info(item, content, max_length))

        return lines

    def build_header(self, data: TestData) -> List[str]:
        last_discovery = self.date_to_string(data.get_last_discovery(), with_full=True)
        stats = data.get_global_test_stats()
        last_run = self.date_to_string(stats["last_run"], with_full=True)
        visibility = self.view.settings().get('visible_tests')
        root_path = self.view.settings().get('focus_test_path')
        if len(root_path) == 0:
            root_path = '<all>'
        else:
            root_path = test_path_to_name(root_path)

        lines = []
        lines.append(f'Last discovery: {last_discovery}')
        lines.append(f'Last run:       {last_run}')
        lines.append(f'Tests status:   {self.stats_to_string(stats)}')
        lines.append(f'Showing:        {self.visible_to_string(visibility)}')
        lines.append(f'Focus:          {root_path}')

        return lines

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

    def item_depth(self, path: List[str]) -> int:
        return len(path) - 1

    def build_items(self, test_list: TestList, item: TestItem, focus_path : List[str], sort_key: Callable, visibility=None, hide_parent=False) -> List[Tuple[TestItem, str]]:
        lines = []

        if len(focus_path) != 0 and item.name != focus_path[0]:
            return lines

        if item.children:
            if not hide_parent and self.item_is_visible(item, visibility=visibility):
                path = test_name_to_path(item.full_name)
                lines.append((item, self.build_item(item, depth=self.item_depth(path))))

            children = [c for c in item.children.values()]
            children.sort(key=sort_key)

            for child in children:
                lines += self.build_items(test_list, child, focus_path[1:], sort_key, visibility=visibility)
        else:
            if not hide_parent and self.item_is_visible(item, visibility=visibility):
                path = test_name_to_path(item.full_name)
                lines.append((item, self.build_item(item, depth=self.item_depth(path))))

        return lines

    def build_item(self, item: TestItem, depth=0) -> str:
        indent = '  ' * depth
        symbol = f'[{STATUS_SYMBOL[self.item_display_status(item)]}]'
        fold = '- ' if item.children is not None else '  '
        return f'  {indent}{fold}{symbol} {END_OF_NAME_MARKER}{item.name}{END_OF_NAME_MARKER}'

    def date_to_string(self, date: Optional[datetime], with_full=False) -> str:
        if date is None:
            return '--'
        elif with_full:
            return f'{readable_date_delta(date)} ({date.isoformat(timespec="seconds")})'
        else:
            return readable_date_delta(date)

    def stats_to_string(self, stats) -> str:
        stats['failed'] += stats['crashed']
        stats['not_run'] += stats['stopped']
        displays = ['failed', 'skipped', 'passed', 'not_run', 'total']
        return ' | '.join(f'{STATUS_NAME[k]}:{stats[k]}' for k in displays)

    def visible_to_string(self, visibility) -> str:
        displays = ['failed', 'skipped', 'passed', 'not_run']
        return ' | '.join(f'[X] {STATUS_NAME[k]}' if visibility[k] else f'[ ] {STATUS_NAME[k]}' for k in displays)

    def build_info(self, item: TestItem, line: str, max_length: int) -> str:
        padding = ' ' * (max_length - len(line))
        if item.children is not None:
            return f'{line}{padding} ({self.stats_to_string(get_test_stats(item))})'
        else:
            return f'{line}{padding} (last-run:{self.date_to_string(item.last_run)})'

    def build_tests(self, test_list: TestList, focus_path: List[str], sort_key: Callable, visibility=None, column_width_percentile=1.0, column_width_factor=1.0):
        lines = self.build_items(test_list, test_list.root, [ROOT_NAME] + focus_path, sort_key, visibility=visibility, hide_parent=True)
        if len(lines) == 0:
            return [], 0

        line_lengths = [len(line) for _, line in lines]
        line_lengths.sort()
        max_index = len(line_lengths) - 1
        max_length = int(line_lengths[min(max_index, int(max_index*column_width_percentile))]*column_width_factor)

        return [(item.full_name, self.build_info(item, line, max_length)) for item, line in lines], max_length


class TestExplorerTextCmd:

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

    def get_item_in_region(self, region: sublime.Region, line_map: Optional[Dict[str,str]] = None) -> str:
        if line_map is None:
            line_map = self.view.settings().get('test_structure')['line_tests']
            assert line_map is not None

        return line_map[str(self.view.rowcol(region.a)[0])]

    def get_item_line(self, item_name: str, test_map: Optional[Dict[str,int]] = None) -> int:
        if test_map is None:
            test_map = self.view.settings().get('test_structure')['test_lines']
            assert test_map is not None

        return test_map.get(item_name)

    def get_all_tests(self) -> List[str]:
        items = self.get_all_leaf_regions()
        line_map = self.view.settings().get('test_structure')['line_tests']
        return [self.get_item_in_region(l, line_map) for l in items]

    def get_all_folders(self) -> List[str]:
        items = self.get_all_node_regions()
        line_map = self.view.settings().get('test_structure')['line_tests']
        return [self.get_item_in_region(n, line_map) for n in items]

    def get_selected_leaf_regions(self):
        items = []
        lines = self.get_selected_line_regions()

        if not lines:
            return items

        for f in self.get_all_leaf_regions():
            items += [f for l in lines if l.contains(f)]

        return items

    def get_selected_tests(self) -> List[str]:
        line_map = self.view.settings().get('test_structure')['line_tests']
        return [self.get_item_in_region(r, line_map) for r in self.get_selected_leaf_regions()]

    def get_selected_node_regions(self):
        items = []
        lines = self.get_selected_line_regions()

        if not lines:
            return items

        for f in self.get_all_node_regions():
            items += [f for l in lines if l.contains(f)]

        return items

    def get_selected_folders(self) -> List[str]:
        line_map = self.view.settings().get('test_structure')['line_tests']
        return [self.get_item_in_region(r, line_map) for r in self.get_selected_node_regions()]

    def get_selected_item(self) -> Optional[str]:
        r = self.get_selected_item_region()
        return self.get_item_in_region(r) if r else None


class TestExplorerListCommand(WindowCommand, TestDataHelper):
    """
    Documentation coming soon.
    """

    def run(self, data_location=None):
        if not data_location:
            data_location = self.get_test_data_location()
        if not data_location:
            return

        views = find_views_for_data(data_location)
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
            view.settings().set('focus_test_path', [])
            view.settings().set('test_data_full_path', data_location)
            view.settings().set('tab_size', 2)

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

    def goto(self, goto, no_scroll=False):
        parts = goto.split(':')
        if parts[0] == 'item':
            self.move_to_item(':'.join(parts[1:]), no_scroll=no_scroll)
        elif parts[0] == 'list-top':
            self.move_to_list_top(no_scroll=no_scroll)
        elif parts[0] == 'point':
            point = int(parts[1])
            self.move_to_point(point, no_scroll=no_scroll)
        elif parts[0] == 'line':
            line = int(parts[1])
            self.move_to_point(self.view.text_point(line, 0), no_scroll=no_scroll)

    def move_to_point(self, point, no_scroll=False):
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(point))

        if not no_scroll:
            pointrow, _ = self.view.rowcol(point)
            pointstart = self.view.text_point(max(pointrow - 3, 0), 0)
            pointend = self.view.text_point(pointrow + 3, 0)

            pointregion = sublime.Region(pointstart, pointend)

            if pointrow < 10:
                self.view.set_viewport_position((0.0, 0.0), False)
            elif not self.view.visible_region().contains(pointregion):
                self.view.show(pointregion, False)

    def move_to_region(self, region, no_scroll=False):
        self.move_to_point(self.view.line(region).begin(), no_scroll=no_scroll)

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

    def move_to_item(self, which='', where=None, no_scroll=False):
        try:
            line = self.get_item_line(which)
            self.move_to_region(self.view.text_point(line, 0), no_scroll=no_scroll)
        except:
            self.move_to_list_top()

    def move_to_list_top(self, no_scroll=False):
        regs = self.view.find_by_selector('meta.test-explorer.test-list.node')
        if not regs:
            regs = self.view.find_by_selector('markup.inserted.test-explorer.no-tests')

        if regs:
            self.move_to_region(regs[0], no_scroll=no_scroll)


class TestExplorerReplaceCommand(TextCommand, TestExplorerMoveCmd):

    def is_visible(self):
        return False

    def run(self, edit, goto, tests, no_scroll=False):
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), tests)
        self.view.set_read_only(True)
        self.view.sel().clear()

        if goto:
            self.goto(goto, no_scroll=no_scroll)
        else:
            self.goto(GOTO_DEFAULT, no_scroll=no_scroll)


class TestExplorerPartialReplaceCommand(TextCommand, TestExplorerMoveCmd):

    def is_visible(self):
        return False

    def run(self, edit, goto, tests, no_scroll=False):
        selection = None
        if len(self.view.sel()) > 0:
            selection = self.view.rowcol(self.view.sel()[0].a)[0]

        self.view.set_read_only(False)
        for line, content in tests:
            line_region = sublime.Region(self.view.text_point(line, 0),
                                         self.view.text_point(line + 1, 0))
            self.view.replace(edit, line_region, content + '\n')
        self.view.set_read_only(True)
        self.view.sel().clear()

        if selection:
            self.goto('line:' + str(selection), no_scroll=no_scroll)


class TestExplorerRefreshCommand(TextCommand, TestExplorerTextCmd, TestExplorerListBuilder):

    def is_visible(self):
        return False

    def refresh(self, data, goto, no_scroll, hints):
        try:
            if len(hints) == 0:
                tests, structure = self.build_list(data)
                self.view.settings().set('test_structure', structure)
                self.view.run_command('test_explorer_replace', {'goto': goto, 'tests': tests, 'no_scroll': no_scroll})
            else:
                tests = self.update_list(data, self.view.settings().get('test_structure'), hints)
                self.view.run_command('test_explorer_partial_replace', {'goto': goto, 'tests': tests, 'no_scroll': no_scroll})

        except Exception as e:
            logger.error('error building test list: {}'.format(str(e)))
            raise

    def run(self, edit, no_scroll=False, hints=[], goto=None):
        data = self.get_test_data()
        if not data:
            return

        if goto is None:
            selected = self.get_selected_item()
            if selected:
                goto = f'item:{selected}'

        sublime.set_timeout(partial(self.refresh, data, goto, no_scroll, hints))


class TestExplorerRefreshAllCommand(ApplicationCommand, TestDataHelper):

    def run(self, data_location=None, hints=[]):
        if not data_location:
            return

        views = find_views_for_data(data_location)
        for view in views:
            view.run_command('test_explorer_refresh', {'no_scroll': True, 'hints': hints})


class TestExplorerEventListener(EventListener, SettingsHelper):

    def on_activated(self, view):
        if view.settings().get('test_view') == 'list' and self.get_setting('explorer_update_on_focus', True):
            view.run_command('test_explorer_refresh')


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
        test_list = data.get_test_list()
        window = self.view.window()

        for test in tests:
            logger.debug(f'opening {test}...')
            item = test_list.find_test(test_name_to_path(test))
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


class TestExplorerSetRootCommand(TextCommand, TestExplorerTextCmd, TestDataHelper):

    def is_visible(self):
        return False

    def run(self, edit, parent : Optional[bool] = None):
        data = self.get_test_data()
        if not data:
            return

        project = self.get_project()
        if not project:
            return

        if parent is not None:
            current_root = self.view.settings().get('focus_test_path')
            if len(current_root) == 0:
                return

            current_root.pop()
            self.view.settings().set('focus_test_path', current_root)
            goto = None
        else:
            tests = self.get_selected_folders()
            if len(tests) != 1:
                return

            self.view.settings().set('focus_test_path', test_name_to_path(tests[0]))
            goto = 'list-top'

        self.view.run_command('test_explorer_refresh', {'goto': goto})
