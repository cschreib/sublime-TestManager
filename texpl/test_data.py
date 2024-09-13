import json
import os
import logging
import copy
import enum
from datetime import datetime
from typing import Optional, List, Dict

import sublime

TEST_SEPARATOR = '/'

class TestStatus(enum.Enum):
    PASSED = 'passed'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    NOT_RUN = 'not_run'

class RunStatus(enum.Enum):
    NOT_RUNNING = 'not_running'
    RUNNING = 'running'
    QUEUED = 'queued'

TEST_DATA_MAIN_FILE = 'main.json'
TEST_DATA_TESTS_FILE = 'tests.json'

logger = logging.getLogger('TestExplorer.test_data')


def date_from_json(data: Optional[str]) -> Optional[datetime]:
    if data is None:
        return None

    return datetime.fromisoformat(data)

def date_to_json(data: Optional[datetime]) -> Optional[str]:
    if data is None:
        return None

    return data.isoformat()


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


class TestItem:
    def __init__(self, name='', framework_id='', run_id='', location=None,
                 last_status=TestStatus.NOT_RUN, run_status=RunStatus.NOT_RUNNING,
                 last_run=None, children: Optional[Dict] = None):
        self.name: str = name
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
                        framework_id=json_data['framework_id'],
                        run_id=json_data['id'],
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
            'framework_id': self.framework_id,
            'id': self.run_id,
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
        return TestItem(name=test.full_name[-1], framework_id=test.framework_id, run_id=test.run_id, location=test.location)

    def update_from_discovered(self, test: DiscoveredTest):
        self.location = test.location
        self.run_id = test.run_id

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
    def __init__(self, root: Optional[TestItem] = None):
        if not root:
            self.root = TestItem(name='root', children={})
            self.run_id_lookup = {}
        else:
            self.root = root
            self.run_id_lookup = {}
            self.make_run_id_lookup(self.root, ignore_parent=True)

    @staticmethod
    def from_json(json_data: Dict):
        return TestList(root=TestItem.from_json(json_data))

    @staticmethod
    def from_file(file_path):
        with open(file_path, 'r') as f:
            json_data = json.load(f)

        return TestList.from_json(json_data)

    def json(self) -> Dict:
        return self.root.json()

    def save(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.json(), f, indent=2)

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
        if not item.framework_id in self.run_id_lookup:
            self.run_id_lookup[item.framework_id] = {}

        self.run_id_lookup[item.framework_id][item.run_id] = item_path

    def make_run_id_lookup(self, item: TestItem, parent=[], ignore_parent=False):
        item_path = copy.deepcopy(parent)
        if not ignore_parent:
            item_path.append(item.name)

        if item.children is None:
            self.add_item_to_run_id_lookup(item, item_path)
            return

        for child in item.children.values():
            self.make_run_id_lookup(child, parent=item_path)

    def find_test_by_run_id(self, framework: str, run_id: str) -> Optional[List[str]]:
        return self.run_id_lookup.get(framework, {}).get(run_id, None)

    def update_test(self, item_path: List[str], item: TestItem):
        parent = self.root
        for i in range(len(item_path)):
            assert parent.children is not None

            if not item_path[i] in parent.children:
                if i == len(item_path) - 1:
                    parent.children[item_path[i]] = item
                    self.add_item_to_run_id_lookup(item, item_path)
                else:
                    parent.children[item_path[i]] = TestItem(item_path[i], children={})

            parent = parent.children[item_path[i]]

        return parent


class TestMetaData:
    def __init__(self):
        self.last_discovery: Optional[datetime] = None
        self.running = False
        pass

    @staticmethod
    def from_json(json_data: Dict):
        data = TestMetaData()
        data.last_discovery = date_from_json(json_data['last_discovery'])
        data.running = json_data['running']
        return data

    @staticmethod
    def from_file(file_path):
        with open(file_path, 'r') as f:
            json_data = json.load(f)

        return TestMetaData.from_json(json_data)

    def json(self) -> Dict:
        return {
            'last_discovery': date_to_json(self.last_discovery),
            'running': self.running
        }

    def save(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.json(), f, indent=2)


class TestData:
    def __init__(self, location):
        self.location = location
        self.tests = None
        self.stats = None
        self.meta = None

        if not os.path.exists(location) or \
            not os.path.exists(os.path.join(location, TEST_DATA_MAIN_FILE)) or \
            not os.path.exists(os.path.join(location, TEST_DATA_TESTS_FILE)):
            self.init()

    def init(self):
        self.commit(meta=TestMetaData(), tests=TestList())

    def refresh_views(self):
        logger.debug(f'refreshing views for {self.location}')
        sublime.run_command('test_explorer_refresh_all', {'data_location': self.location})

    def commit(self, meta=None, tests=None):
        # TODO: put this into the cmd for the 'data' queue
        os.makedirs(self.location, exist_ok=True)

        if meta is not None:
            self.meta = meta
            self.meta.save(os.path.join(self.location, TEST_DATA_MAIN_FILE))

        if tests is not None:
            self.tests = tests
            self.tests.save(os.path.join(self.location, TEST_DATA_TESTS_FILE))

        if meta is not None or tests is not None:
            self.refresh_views()

    def get_test_list(self, cached=True) -> TestList:
        if self.tests and cached:
            return self.tests

        # TODO: put this into the cmd for the 'data' queue
        self.tests = TestList.from_file(os.path.join(self.location, TEST_DATA_TESTS_FILE))
        self.stats = None

        return self.tests

    def get_test_metadata(self, cached=True) -> TestMetaData:
        if self.meta and cached:
            return self.meta

        # TODO: put this into the cmd for the 'data' queue
        self.meta = TestMetaData.from_file(os.path.join(self.location, TEST_DATA_MAIN_FILE))

        return self.meta

    def get_last_discovery(self, cached=True):
        return self.get_test_metadata(cached=cached).last_discovery

    def is_running_tests(self, cached=True):
        return self.get_test_metadata(cached=cached).running

    def get_global_test_stats(self, cached=True):
        if self.stats and cached:
            return self.stats

        self.stats = get_test_stats(self.get_test_list(cached=cached).root)
        return self.stats

    def notify_discovered_tests(self, discovered_tests: List[DiscoveredTest], discovery_time: datetime):
        logger.info('discovery complete')

        meta = self.get_test_metadata(cached=False)
        meta.last_discovery = discovery_time

        old_tests = self.get_test_list(cached=False)
        new_tests = TestList()
        for test in discovered_tests:
            item = old_tests.find_test(test.full_name)
            if not item:
                item = TestItem.from_discovered(test)
            else:
                item.update_from_discovered(test)

            new_tests.update_test(test.full_name, item)

        self.commit(meta=meta, tests=new_tests)
