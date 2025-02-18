import os
import logging
import time
import queue
import copy
import enum
import threading
from datetime import datetime
from typing import Optional, List, Dict
from functools import partial
import sqlite3
from contextlib import closing

import sublime

ROOT_NAME = ''
TEST_SEPARATOR = '/'
MIN_REFRESH_INTERVAL = 0.1 # seconds

class TestStatus(enum.Enum):
    PASSED = 'passed'
    FAILED = 'failed'
    CRASHED = 'crashed'
    STOPPED = 'stopped'
    SKIPPED = 'skipped'
    NOT_RUN = 'not_run'


class RunStatus(enum.Enum):
    NOT_RUNNING = 'not_running'
    RUNNING = 'running'
    QUEUED = 'queued'


STATUS_PRIORITY = {
    None: -1,
    TestStatus.NOT_RUN: 0,
    TestStatus.STOPPED: 1,
    TestStatus.SKIPPED: 2,
    TestStatus.PASSED: 3,
    TestStatus.FAILED: 4,
    TestStatus.CRASHED: 5
}

RUN_STATUS_PRIORITY = {
    None: -1,
    RunStatus.NOT_RUNNING: 0,
    RunStatus.QUEUED: 1,
    RunStatus.RUNNING: 2
}

DB_FILE = 'tests.sqlite3'

logger = logging.getLogger('TestExplorer.test_data')


def status_merge(status1, status2):
    return status1 if STATUS_PRIORITY[status1] > STATUS_PRIORITY[status2] else status2

def run_status_merge(status1, status2):
    return status1 if RUN_STATUS_PRIORITY[status1] > RUN_STATUS_PRIORITY[status2] else status2

def date_from_db(data: Optional[str]) -> Optional[datetime]:
    if data is None:
        return None

    return datetime.fromisoformat(data)

def test_name_to_path(name: str):
    path = name.split(TEST_SEPARATOR)
    if len(path) == 1 and len(path[0]) == 0:
        path = []
    return path

def test_path_to_name(path: List[str]):
    return TEST_SEPARATOR.join(path)

def parents_in_path(path: List[str]):
    return [test_path_to_name(path[:i]) for i in range(1, len(path))]


class TestLocation:
    def __init__(self, executable='', file='', line=0):
        self.executable = executable
        self.file = file
        self.line = line

    @staticmethod
    def from_row(row: sqlite3.Row):
        if row['location_executable'] is None:
            return None

        return TestLocation(executable=row['location_executable'],
                            file=row['location_file'],
                            line=row['location_line'])

class DiscoveryError(Exception):
    def __init__(self, message, details : Optional[List[str]] = None):
        super().__init__(message)
        self.details = details


class DiscoveredTest:
    def __init__(self, full_name: List[str] = [], discovery_id = 0, framework_id='', run_id='', location=TestLocation()):
        self.full_name = full_name
        self.discovery_id = discovery_id
        self.framework_id = framework_id
        self.run_id = run_id
        self.location = location


class StartedTest:
    def __init__(self, full_name: List[str] = [], start_time=None):
        self.full_name = full_name
        self.start_time = datetime.now() if start_time is None else start_time


class FinishedTest:
    def __init__(self, full_name: List[str] = [], status=TestStatus.NOT_RUN, message=''):
        self.full_name = full_name
        self.status = status
        self.message = message


class TestOutput:
    def __init__(self, full_name: List[str] = [], output=''):
        self.full_name = full_name
        self.output = output


class StartedRun:
    def __init__(self, tests: List[List[str]]):
        self.tests = tests


class FinishedRun:
    def __init__(self, tests: List[List[str]]):
        self.tests = tests


class TestItem:
    def __init__(self, name='', full_name='', discovery_id=0, framework_id='', run_id='', location=None,
                 last_status=TestStatus.NOT_RUN, run_status=RunStatus.NOT_RUNNING,
                 last_run=None, children: Optional[Dict] = None):
        self.name: str = name
        self.full_name: str = full_name
        self.discovery_id: int = discovery_id
        self.framework_id: str = framework_id
        self.run_id: str = run_id
        self.location: Optional[TestLocation] = location
        self.last_status: TestStatus = last_status
        self.run_status: RunStatus = run_status
        self.last_run: Optional[datetime] = last_run
        self.children: Optional[Dict[str, TestItem]] = children

    @staticmethod
    def from_row(row: sqlite3.Row):
        return TestItem(name=row['name'],
                        full_name=row['full_name'],
                        discovery_id=row['discovery_id'],
                        framework_id=row['framework_id'],
                        run_id=row['run_id'],
                        location=TestLocation.from_row(row),
                        last_status=TestStatus[row['last_status'].upper()],
                        run_status=RunStatus[row['run_status'].upper()],
                        last_run=date_from_db(row['last_run']),
                        children=None if row['leaf'] else {})


    def save(self, con: sqlite3.Connection):
        con.execute('INSERT OR REPLACE INTO tests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (self.full_name,
            self.name,
            self.discovery_id,
            self.framework_id,
            self.run_id,
            self.location.executable if self.location is not None else None,
            self.location.file if self.location is not None else None,
            self.location.line if self.location is not None else None,
            self.last_status.value,
            self.run_status.value,
            self.last_run,
            self.children is None))

        if self.children is not None:
            for c in self.children.values():
                c.save(con)

    def save_children(self, con: sqlite3.Connection):
        self.save(con)
        if self.children is not None:
            for c in self.children.values():
                c.save_children(con)

    @staticmethod
    def from_discovered(test: DiscoveredTest):
        return TestItem(name=test.full_name[-1],
                        full_name=test_path_to_name(test.full_name),
                        framework_id=test.framework_id,
                        run_id=test.run_id,
                        location=test.location)

    def update_from_discovered(self, test: DiscoveredTest):
        self.discovery_id = test.discovery_id
        self.framework_id = test.framework_id
        self.run_id = test.run_id
        self.location = test.location

    def notify_run_queued(self):
        self.run_status = RunStatus.QUEUED

    def notify_run_stopped(self):
        if self.run_status == RunStatus.RUNNING:
            self.last_status = TestStatus.CRASHED
        elif self.run_status == RunStatus.QUEUED:
            self.last_status = TestStatus.STOPPED
        self.run_status = RunStatus.NOT_RUNNING

    def update_from_started(self, test: StartedTest):
        self.last_run = test.start_time
        self.run_status = RunStatus.RUNNING

    def update_from_finished(self, test: FinishedTest):
        self.last_status = test.status
        self.run_status = RunStatus.NOT_RUNNING

    def recompute_status(self):
        if self.children is None:
            return

        new_status = TestStatus.NOT_RUN
        for child in self.children.values():
            new_status = status_merge(new_status, child.last_status)

        new_run_status = RunStatus.NOT_RUNNING
        for child in self.children.values():
            new_run_status = run_status_merge(new_run_status, child.run_status)

        self.last_status = new_status
        self.run_status = new_run_status


def get_test_stats(item: TestItem):
    def add_one_to_stats(stats: Dict, item: TestItem):
        stats[item.last_status.value] += 1
        stats[item.run_status.value] += 1
        stats['total'] += 1
        if item.last_run is not None:
            if stats['last_run'] is not None:
                stats['last_run'] = max(stats['last_run'], item.last_run)
            else:
                stats['last_run'] = item.last_run

    def add_to_stats(stats: Dict, item: TestItem):
        if item.children is not None:
            for c in item.children.values():
                add_to_stats(stats, c)
        else:
            add_one_to_stats(stats, item)

    stats = {'total': 0, 'last_run': None}

    for status in TestStatus:
        stats[status.value] = 0

    for status in RunStatus:
        stats[status.value] = 0

    add_to_stats(stats, item)
    return stats


class TestList:
    def __init__(self, location: str):
        self.location = location
        self.root = TestItem(name=ROOT_NAME, full_name=ROOT_NAME, children={})
        self.run_id_lookup = {}
        self.test_output_buffer = {}

    @staticmethod
    def from_location(location):
        tests = TestList(location=location)
        with closing(sqlite3.connect(os.path.join(location, DB_FILE))) as con:
            with con:
                con.row_factory = sqlite3.Row
                cur = con.execute('SELECT * from tests')
                while True:
                    rows = cur.fetchmany(size=128)
                    if len(rows) == 0:
                        break

                    for row in rows:
                        test = TestItem.from_row(row)
                        tests.update_test(test_name_to_path(test.full_name), test)

        return tests

    @staticmethod
    def is_initialised(location):
        return os.path.exists(os.path.join(location, DB_FILE))

    def save(self, refresh_hints=[]):
        os.makedirs(self.location, exist_ok=True)
        with closing(sqlite3.connect(os.path.join(self.location, DB_FILE))) as con:
            with con:
                tables = [r[0] for r in con.execute('SELECT name FROM sqlite_master').fetchall()]
                if not 'tests' in tables:
                    con.execute("""CREATE TABLE tests(
                        full_name TEXT PRIMARY KEY,
                        name TEXT,
                        discovery_id INT,
                        framework_id TEXT,
                        run_id TEXT,
                        location_executable TEXT,
                        location_file TEXT,
                        location_line INT,
                        last_status TEXT,
                        run_status TEXT,
                        last_run TIMESTAMP,
                        leaf BOOL
                        )""")

                    con.execute("""CREATE TABLE test_ouputs(
                        full_name TEXT PRIMARY KEY,
                        output TEXT
                        )""")

                if len(refresh_hints) == 0:
                    assert self.root.children is not None
                    for c in self.root.children.values():
                        c.save_children(con)
                else:
                    for hint in refresh_hints:
                        test = self.find_test(test_name_to_path(hint))
                        if test is None:
                            continue
                        test.save(con)

    def is_empty(self):
        return not self.root.children

    def find_test(self, item_path: List[str]) -> Optional[TestItem]:
        parent = self.root
        for p in item_path:
            if parent.children is None:
                return None

            if not p in parent.children:
                return None

            parent = parent.children[p]

        return parent

    def add_item_to_run_id_lookup(self, item: TestItem):
        if item.framework_id not in self.run_id_lookup:
            self.run_id_lookup[item.framework_id] = {}

        assert item.location is not None
        if item.location.executable not in self.run_id_lookup[item.framework_id]:
            self.run_id_lookup[item.framework_id][item.location.executable] = {}

        self.run_id_lookup[item.framework_id][item.location.executable][item.run_id] = test_name_to_path(item.full_name)

    def make_run_id_lookup(self, item: TestItem):
        if item.children is None:
            self.add_item_to_run_id_lookup(item)
            return

        for child in item.children.values():
            self.make_run_id_lookup(child)

    def find_test_by_run_id(self, framework: str, executable: str, run_id: str) -> Optional[List[str]]:
        return self.run_id_lookup.get(framework, {}).get(executable, {}).get(run_id, None)

    def update_test(self, item_path: List[str], item: TestItem):
        parent = self.root
        for i in range(len(item_path)):
            assert parent.children is not None

            if not item_path[i] in parent.children:
                if i == len(item_path) - 1:
                    parent.children[item_path[i]] = item
                    if item.children is None:
                        self.add_item_to_run_id_lookup(item)
                else:
                    parent.children[item_path[i]] = TestItem(name=item_path[i],
                                                             full_name=test_path_to_name(item_path[:i+1]),
                                                             discovery_id=item.discovery_id,
                                                             framework_id=item.framework_id,
                                                             children={})

            parent = parent.children[item_path[i]]

        return parent

    def update_parent_status(self, item_path: List[str]):
        parent = self.root
        parents = []
        for p in item_path:
            if parent.children is None:
                return

            if not p in parent.children:
                return

            parents.append(parent)
            parent = parent.children[p]

        parents.reverse()

        for parent in parents:
            parent.recompute_status()

    def update_parent_statuses(self):
        def recompute(item: TestItem):
            if item.children is None:
                return

            for child in item.children.values():
                recompute(child)

            item.recompute_status()

        recompute(self.root)

    def tests(self):
        def get_tests(item: TestItem):
            if item.children is not None:
                for child in item.children.values():
                    yield from get_tests(child)
            else:
                yield item

        yield from get_tests(self.root)

    def clear_test_output(self, item_path: List[str]):
        test_name = test_path_to_name(item_path)
        with closing(sqlite3.connect(os.path.join(self.location, DB_FILE))) as con:
            with con:
                con.execute('INSERT OR REPLACE INTO test_ouputs VALUES (?,"")', (test_name,))

    def add_test_output(self, item_path: List[str], output: str):
        test_name = test_path_to_name(item_path)
        if not test_name in self.test_output_buffer:
            self.test_output_buffer[test_name] = output
        else:
            self.test_output_buffer[test_name] += output

    def flush_test_output(self, item_path: List[str]):
        test_name = test_path_to_name(item_path)
        if not test_name in self.test_output_buffer:
            return

        output = self.test_output_buffer[test_name]
        del self.test_output_buffer[test_name]

        with closing(sqlite3.connect(os.path.join(self.location, DB_FILE))) as con:
            with con:
                con.execute('UPDATE test_ouputs SET output=? WHERE full_name=?',
                    (output, test_name))

    def get_test_output(self, item_path: List[str]) -> str:
        test_name = test_path_to_name(item_path)
        if test_name in self.test_output_buffer:
            return self.test_output_buffer[test_name]

        with closing(sqlite3.connect(os.path.join(self.location, DB_FILE))) as con:
            with con:
                output = con.execute('SELECT output FROM test_ouputs WHERE full_name=?',
                    (test_path_to_name(item_path),)).fetchone()

                return '' if output is None else output[0]


class TestMetaData:
    def __init__(self, location: str):
        self.location = location
        self.last_discovery: Optional[datetime] = None
        self.running = False
        pass

    @staticmethod
    def from_row(location: str, row: sqlite3.Row):
        data = TestMetaData(location)
        data.last_discovery = date_from_db(row['last_discovery'])
        data.running = row['running']
        return data

    @staticmethod
    def from_location(location):
        with closing(sqlite3.connect(os.path.join(location, DB_FILE))) as con:
            with con:
                con.row_factory = sqlite3.Row
                row = con.execute('SELECT * from meta').fetchone()
                assert row is not None
                return TestMetaData.from_row(location, row)

    @staticmethod
    def is_initialised(location):
        return os.path.exists(os.path.join(location, DB_FILE))

    def save(self):
        os.makedirs(self.location, exist_ok=True)
        with closing(sqlite3.connect(os.path.join(self.location, DB_FILE))) as con:
            with con:
                tables = [r[0] for r in con.execute('SELECT name FROM sqlite_master').fetchall()]
                if not 'meta' in tables:
                    con.execute("""CREATE TABLE meta(
                        last_discovery TIMESTAMP,
                        running BOOL
                        )""")
                    con.execute('INSERT INTO meta VALUES (?,?)',
                        (self.last_discovery, self.running))
                else:
                    con.execute("""UPDATE meta SET
                        last_discovery=?,
                        running=?
                        """,
                        (self.last_discovery, self.running))


def clear_test_data(location):
    try:
        db_path = os.path.join(location, DB_FILE)
        os.remove(db_path)
    except:
        pass


class TestData:
    def __init__(self, location):
        self.location = location
        self.mutex = threading.Lock()
        self.stats: Optional[dict] = None
        self.last_test_finished: Optional[List[str]] = None
        self.stop_tests_event = threading.Event()
        self.refresh_thread: Optional[threading.Thread] = None
        self.stop_refresh_thread = threading.Event()
        self.refresh_list_queue = queue.Queue()
        self.refresh_output_queue = queue.Queue()
        self.test_output_buffer = ''

        if not self.is_initialised():
            self.init()
            return

        self.load()

        if self.meta.running:
            # Plugin was reloaded or SublimeText killed while running tests, so we didn't
            # register a "run finished" event. Generate it now to clean everything up.
            self.meta.running = False

            for item in self.tests.tests():
                item.notify_run_stopped()

            self.tests.update_parent_statuses()
            self.commit(meta=self.meta, tests=self.tests, no_refresh=True)

    def is_initialised(self):
        return TestMetaData.is_initialised(self.location) and TestList.is_initialised(self.location)

    def load(self):
        try:
            self.tests = TestList.from_location(self.location)
            self.meta = TestMetaData.from_location(self.location)
        except Exception as e:
            logger.error(f'error during load: {e}')
            raise

    def init(self):
        clear_test_data(self.location)
        self.commit(meta=TestMetaData(self.location), tests=TestList(self.location))

    def refresh_views(self, refresh_hints=[]):
        if self.is_running_tests() and len(refresh_hints) > 0:
            self.refresh_list_queue.put(refresh_hints)
        else:
            self.refresh_views_now(refresh_hints=refresh_hints)

    def refresh_views_now(self, refresh_hints=[]):
        logger.debug(f'refreshing views for {self.location}')
        sublime.run_command('test_explorer_refresh_all', {'data_location': self.location, 'hints': refresh_hints})

    def refresh_output_views_now(self, test: str):
        logger.debug(f'refreshing output views for {test}')
        sublime.run_command('test_explorer_output_refresh_all', {'data_location': self.location, 'test': test})

    def refresh_views_continuously(self, stop_token):
        accumulated_hints = set()
        accumulated_tests_with_output = set()
        last_refresh: Optional[float] = None

        while not stop_token.is_set():
            try:
                while not stop_token.is_set():
                    refresh_hints = self.refresh_list_queue.get(block=False)
                    for hint in refresh_hints:
                        accumulated_hints.add(hint)
            except:
                pass

            try:
                while not stop_token.is_set():
                    accumulated_tests_with_output.add(self.refresh_output_queue.get(block=False))
            except:
                pass

            now = time.time()
            if last_refresh is None or now - last_refresh > MIN_REFRESH_INTERVAL:
                self.refresh_views_now(list(accumulated_hints))

                for test in accumulated_tests_with_output:
                    self.refresh_output_views_now(test)

                last_refresh = now
                accumulated_hints = set()
                accumulated_tests_with_output = set()

    def commit(self, meta=None, tests=None, refresh_hints=[], no_refresh=False):
        with self.mutex:
            # TODO: put this into the cmd for the 'data' queue
            try:
                if meta is not None:
                    self.meta = meta
                    self.meta.save()

                if tests is not None:
                    self.tests = tests
                    self.stats = None
                    self.tests.save(refresh_hints=refresh_hints)
            except Exception as e:
                logger.error(f'error during commit: {e}')
                raise

        if not no_refresh and (meta is not None or tests is not None):
            self.refresh_views(refresh_hints=refresh_hints)

    def get_test_list(self) -> TestList:
        with self.mutex:
            return copy.deepcopy(self.tests)

    def get_test_metadata(self) -> TestMetaData:
        with self.mutex:
            return copy.deepcopy(self.meta)

    def get_last_discovery(self):
        return self.get_test_metadata().last_discovery

    def is_running_tests(self):
        return self.get_test_metadata().running

    def get_global_test_stats(self, cached=True):
        with self.mutex:
            if not cached or self.stats is None:
                self.stats = get_test_stats(self.tests.root)

            return copy.deepcopy(self.stats)

    def notify_discovered_tests(self, discovered_tests: List[DiscoveredTest], discovery_time: datetime):
        logger.info('discovery complete')

        with self.mutex:
            self.meta.last_discovery = discovery_time

            old_tests = self.tests
            new_tests = TestList(self.location)
            for test in discovered_tests:
                item = old_tests.find_test(test.full_name)
                if not item:
                    item = TestItem.from_discovered(test)
                else:
                    item.update_from_discovered(test)

                new_tests.update_test(test.full_name, item)
                new_tests.update_parent_status(test.full_name)

        self.commit(meta=self.meta, tests=new_tests)

    def notify_run_started(self, run: StartedRun):
        logger.info('test run started')

        with self.mutex:
            self.meta.running = True
            self.stop_tests_event = threading.Event()

            for path in run.tests:
                item = self.tests.find_test(path)
                if not item:
                    raise Exception('Unknown test "{}"'.format(test_path_to_name(path)))

                item.notify_run_queued()
                self.tests.update_parent_status(path)

            self.stop_refresh_thread = threading.Event()
            self.refresh_list_queue = queue.Queue()
            self.refresh_thread = threading.Thread(target=partial(self.refresh_views_continuously, self.stop_refresh_thread))
            self.refresh_thread.start()

        self.commit(meta=self.meta, tests=self.tests)

    def notify_run_finished(self, run: FinishedRun):
        logger.info('test run finished')

        with self.mutex:
            self.meta.running = False

            for path in run.tests:
                item = self.tests.find_test(path)
                if not item:
                    raise Exception('Unknown test "{}"'.format(test_path_to_name(path)))

                item.notify_run_stopped()
                self.tests.update_parent_status(path)

            assert self.refresh_thread is not None
            self.stop_refresh_thread.set()
            self.refresh_thread.join(timeout=2)

        self.commit(meta=self.meta, tests=self.tests)

    def notify_test_started(self, test: StartedTest):
        logger.info('started {}'.format(test_path_to_name(test.full_name)))

        with self.mutex:
            item = self.tests.find_test(test.full_name)
            if not item:
                raise Exception('Unknown test "{}"'.format(test_path_to_name(test.full_name)))

            item.update_from_started(test)
            refresh_hints = [item.full_name]

            if self.last_test_finished is not None:
                # Update parents of last tests now, rather than in notify_test_finished().
                # This prevents status flicker.
                self.tests.update_parent_status(self.last_test_finished)
                refresh_hints += parents_in_path(self.last_test_finished)
                self.last_test_finished = None

            self.tests.update_parent_status(test.full_name)
            self.tests.clear_test_output(test.full_name)
            refresh_hints += parents_in_path(test.full_name)

        self.refresh_output_views_now(test_path_to_name(test.full_name))
        self.commit(tests=self.tests, refresh_hints=refresh_hints)

    def notify_test_output(self, test: TestOutput):
        with self.mutex:
            self.tests.add_test_output(test.full_name, test.output)

        self.refresh_output_queue.put(test_path_to_name(test.full_name))

    def notify_test_finished(self, test: FinishedTest):
        logger.info('finished {}'.format(test_path_to_name(test.full_name)))

        with self.mutex:
            item = self.tests.find_test(test.full_name)
            if not item:
                raise Exception('Unknown test "{}"'.format(test_path_to_name(test.full_name)))

            item.update_from_finished(test)
            refresh_hints = [item.full_name]

            self.last_test_finished = test.full_name
            self.tests.flush_test_output(test.full_name)

        self.refresh_output_views_now(test_path_to_name(test.full_name))
        self.commit(tests=self.tests, refresh_hints=refresh_hints)
