import json
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

import sublime

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

TEST_DATA_MAIN_FILE = 'main.json'
TEST_DATA_TESTS_FILE = 'tests.json'

logger = logging.getLogger('TestExplorer.test_data')


def status_merge(status1, status2):
    return status1 if STATUS_PRIORITY[status1] > STATUS_PRIORITY[status2] else status2

def run_status_merge(status1, status2):
    return status1 if RUN_STATUS_PRIORITY[status1] > RUN_STATUS_PRIORITY[status2] else status2

def date_from_json(data: Optional[str]) -> Optional[datetime]:
    if data is None:
        return None

    return datetime.fromisoformat(data)

def date_to_json(data: Optional[datetime]) -> Optional[str]:
    if data is None:
        return None

    return data.isoformat()

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
    def from_json(json_data: Optional[dict]):
        if json_data is None:
            return None

        return TestLocation(executable=json_data['executable'],
                            file=json_data['file'],
                            line=json_data['line'])

    def json(self) -> Dict:
        return {'executable': self.executable, 'file': self.file, 'line': self.line}


class DiscoveryError(Exception):
    def __init__(self, message, details : Optional[List[str]] = None):
        super().__init__(message)
        self.details = details


class DiscoveredTest:
    def __init__(self, full_name: List[str] = [], framework_id='', run_id='', location=TestLocation()):
        self.full_name = full_name
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


class StartedRun:
    def __init__(self, tests: List[List[str]]):
        self.tests = tests


class FinishedRun:
    def __init__(self, tests: List[List[str]]):
        self.tests = tests


class TestItem:
    def __init__(self, name='', full_name='', framework_id='', run_id='', location=None,
                 last_status=TestStatus.NOT_RUN, run_status=RunStatus.NOT_RUNNING,
                 last_run=None, children: Optional[Dict] = None):
        self.name: str = name
        self.full_name: str = full_name
        self.framework_id: str = framework_id
        self.run_id: str = run_id
        self.location: Optional[TestLocation] = location
        self.last_status: TestStatus = last_status
        self.run_status: RunStatus = run_status
        self.last_run: Optional[datetime] = last_run
        self.children: Optional[Dict[str, TestItem]] = children

    @staticmethod
    def from_json(json_data: Dict):
        item = TestItem(name=json_data['name'],
                        full_name=json_data['full_name'],
                        framework_id=json_data['framework_id'],
                        run_id=json_data['run_id'],
                        location=TestLocation.from_json(json_data.get('location', None)),
                        last_status=TestStatus[json_data['last_status'].upper()],
                        run_status=RunStatus[json_data['run_status'].upper()],
                        last_run=date_from_json(json_data.get('last_run', None)))

        if 'children' in json_data and json_data['children'] is not None:
            item.children = {}
            for c in json_data['children']:
                child = TestItem.from_json(c)
                item.children[child.name] = child

        return item

    def json(self) -> Dict:
        data = {
            'name': self.name,
            'full_name': self.full_name,
            'framework_id': self.framework_id,
            'run_id': self.run_id,
            'location': self.location.json() if self.location is not None else None,
            'last_status': self.last_status.value,
            'run_status': self.run_status.value,
            'last_run': date_to_json(self.last_run)
        }

        if self.children is not None:
            data['children'] = [c.json() for c in self.children.values()]

        return data

    @staticmethod
    def from_discovered(test: DiscoveredTest):
        return TestItem(name=test.full_name[-1],
                        full_name=test_path_to_name(test.full_name),
                        framework_id=test.framework_id,
                        run_id=test.run_id,
                        location=test.location)

    def update_from_discovered(self, test: DiscoveredTest):
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
    def __init__(self, location: str, root: Optional[TestItem] = None):
        self.location = location
        if not root:
            self.root = TestItem(name='root', full_name='root', children={})
            self.run_id_lookup = {}
        else:
            self.root = root
            self.run_id_lookup = {}
            self.make_run_id_lookup(self.root, ignore_parent=True)

    @staticmethod
    def from_json(location: str, json_data: Dict):
        return TestList(location, root=TestItem.from_json(json_data))

    @staticmethod
    def from_location(location):
        file_path = os.path.join(location, TEST_DATA_TESTS_FILE)
        with open(file_path, 'r') as f:
            json_data = json.load(f)

        return TestList.from_json(location, json_data)

    @staticmethod
    def is_initialised(location):
        return os.path.exists(os.path.join(location, TEST_DATA_TESTS_FILE))

    def json(self) -> Dict:
        return self.root.json()

    def save_to(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.json(), f, indent=2)

    def save(self, refresh_hints=[]):
        os.makedirs(self.location, exist_ok=True)
        self.save_to(os.path.join(self.location, TEST_DATA_TESTS_FILE))

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

    def add_item_to_run_id_lookup(self, item: TestItem, item_path: List[str]):
        if item.framework_id not in self.run_id_lookup:
            self.run_id_lookup[item.framework_id] = {}

        assert item.location is not None
        if item.location.executable not in self.run_id_lookup[item.framework_id]:
            self.run_id_lookup[item.framework_id][item.location.executable] = {}

        self.run_id_lookup[item.framework_id][item.location.executable][item.run_id] = item_path

    def make_run_id_lookup(self, item: TestItem, parent=[], ignore_parent=False):
        item_path = copy.deepcopy(parent)
        if not ignore_parent:
            item_path.append(item.name)

        if item.children is None:
            self.add_item_to_run_id_lookup(item, item_path)
            return

        for child in item.children.values():
            self.make_run_id_lookup(child, parent=item_path)

    def find_test_by_run_id(self, framework: str, executable: str, run_id: str) -> Optional[List[str]]:
        return self.run_id_lookup.get(framework, {}).get(executable, {}).get(run_id, None)

    def update_test(self, item_path: List[str], item: TestItem):
        parent = self.root
        for i in range(len(item_path)):
            assert parent.children is not None

            if not item_path[i] in parent.children:
                if i == len(item_path) - 1:
                    parent.children[item_path[i]] = item
                    self.add_item_to_run_id_lookup(item, item_path)
                else:
                    parent.children[item_path[i]] = TestItem(name=item_path[i],
                                                             full_name=test_path_to_name(item_path[:i+1]),
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


class TestMetaData:
    def __init__(self, location: str):
        self.location = location
        self.last_discovery: Optional[datetime] = None
        self.running = False
        pass

    @staticmethod
    def from_json(location: str, json_data: Dict):
        data = TestMetaData(location)
        data.last_discovery = date_from_json(json_data['last_discovery'])
        data.running = json_data['running']
        return data

    @staticmethod
    def from_location(location):
        file_path = os.path.join(location, TEST_DATA_MAIN_FILE)
        with open(file_path, 'r') as f:
            json_data = json.load(f)

        return TestMetaData.from_json(location, json_data)

    @staticmethod
    def is_initialised(location):
        return os.path.exists(os.path.join(location, TEST_DATA_MAIN_FILE))

    def json(self) -> Dict:
        return {
            'last_discovery': date_to_json(self.last_discovery),
            'running': self.running
        }

    def save_to(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.json(), f, indent=2)

    def save(self):
        os.makedirs(self.location, exist_ok=True)
        self.save_to(os.path.join(self.location, TEST_DATA_MAIN_FILE))


class TestData:
    def __init__(self, location):
        self.location = location
        self.mutex = threading.Lock()
        self.stats: Optional[dict] = None
        self.last_test_finished: Optional[List[str]] = None
        self.stop_tests_event = threading.Event()
        self.refresh_thread: Optional[threading.Thread] = None
        self.stop_refresh_thread = threading.Event()
        self.refresh_queue = queue.Queue()

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
        self.commit(meta=TestMetaData(self.location), tests=TestList(self.location))

    def refresh_views(self, refresh_hints=[]):
        if self.is_running_tests() and len(refresh_hints) > 0:
            self.refresh_queue.put(refresh_hints)
        else:
            self.refresh_views_now(refresh_hints=refresh_hints)

    def refresh_views_now(self, refresh_hints=[]):
        logger.debug(f'refreshing views for {self.location}')
        sublime.run_command('test_explorer_refresh_all', {'data_location': self.location, 'hints': refresh_hints})

    def refresh_views_continuously(self, stop_token):
        accumulated_hints = set()
        last_refresh: Optional[float] = None

        while not stop_token.is_set():
            try:
                refresh_hints = self.refresh_queue.get(timeout=0.05)
                for hint in refresh_hints:
                    accumulated_hints.add(hint)
            except:
                pass

            now = time.time()
            if last_refresh is None or now - last_refresh > MIN_REFRESH_INTERVAL:
                sublime.set_timeout(partial(self.refresh_views_now, list(accumulated_hints)))
                last_refresh = now
                accumulated_hints = set()

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
            self.refresh_queue = queue.Queue()
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
            self.refresh_thread.join()

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
            refresh_hints += parents_in_path(test.full_name)

        self.commit(tests=self.tests, refresh_hints=refresh_hints)

    def notify_test_finished(self, test: FinishedTest):
        logger.info('finished {}'.format(test_path_to_name(test.full_name)))

        with self.mutex:
            item = self.tests.find_test(test.full_name)
            if not item:
                raise Exception('Unknown test "{}"'.format(test_path_to_name(test.full_name)))

            item.update_from_finished(test)
            refresh_hints = [item.full_name]

            self.last_test_finished = test.full_name

        self.commit(tests=self.tests, refresh_hints=refresh_hints)
