import json
import os
from datetime import datetime
from typing import Optional, List, Dict

TEST_DATA_MAIN_FILE = 'main.json'
TEST_DATA_TESTS_FILE = 'tests.json'

def date_from_json(data: Optional[str]) -> Optional[datetime]:
    if data is None:
        return None

    return datetime.fromisoformat(data)

def date_to_json(data: Optional[datetime]) -> Optional[str]:
    if data is None:
        return None

    return data.isoformat()


class TestLocation:
    def __init__(self, file='', line=0):
        self.file = file
        self.line = line

    @staticmethod
    def from_json(json_data: Optional[dict]):
        if json_data is None:
            return None

        return TestLocation(file=json_data['file'], line=json_data['line'])

    def json(self) -> Dict:
        return {'file': self.file, 'line': self.line}


class DiscoveredTest:
    def __init__(self, full_name: List[str] = [], location=TestLocation()):
        self.full_name = full_name
        self.location = location


class TestItem:
    def __init__(self, name='', location=None, last_status='not_run', run_status='not_running', last_run=None, children: Optional[Dict] = None):
        self.name: str = name
        self.location: Optional[TestLocation] = location
        self.last_status: str = last_status
        self.run_status: str = run_status
        self.last_run: Optional[datetime] = last_run
        self.children: Optional[Dict[str, TestItem]] = children

    @staticmethod
    def from_json(json_data: Dict):
        item = TestItem(name=json_data['name'],
                        location=TestLocation.from_json(json_data.get('location', None)),
                        last_status=json_data['last_status'],
                        run_status=json_data['run_status'],
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
            'location': self.location.json() if self.location is not None else None,
            'last_status': self.last_status,
            'run_status': self.run_status,
            'last_run': date_to_json(self.last_run)
        }

        if self.children is not None:
            data['children'] = [c.json() for c in self.children.values()]

        return data

    @staticmethod
    def from_discovered(test: DiscoveredTest):
        return TestItem(name=test.full_name[-1], location=test.location)

    def update_from_discovered(self, test: DiscoveredTest):
        self.location = test.location

def get_test_stats(item: TestItem):
    def add_one_to_stats(stats: Dict, item: TestItem):
        stats[item.last_status] += 1
        stats[item.run_status] += 1
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

    stats = {'failed': 0, 'skipped': 0, 'passed': 0, 'not_run': 0, 'not_running': 0, 'running': 0, 'queued': 0, 'total': 0, 'last_run': None}
    add_to_stats(stats, item)
    return stats


class TestList:
    def __init__(self, root: Optional[TestItem] = None):
        if not root:
            self.root = TestItem(name='root', children={})
        else:
            self.root = root

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

    def update_test(self, item_path: List[str], item: TestItem):
        parent = self.root
        for i in range(len(item_path)):
            assert parent.children is not None

            if not item_path[i] in parent.children:
                if i == len(item_path) - 1:
                    parent.children[item_path[i]] = item
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

    def commit(self, meta=None, tests=None):
        os.makedirs(self.location, exist_ok=True)

        if meta is not None:
            self.meta = meta
            self.meta.save(os.path.join(self.location, TEST_DATA_MAIN_FILE))

        if tests is not None:
            self.tests = tests
            self.tests.save(os.path.join(self.location, TEST_DATA_TESTS_FILE))

    def get_test_list(self, cached=True) -> TestList:
        if self.tests and cached:
            return self.tests

        self.tests = TestList.from_file(os.path.join(self.location, TEST_DATA_TESTS_FILE))
        self.stats = None

        return self.tests

    def get_test_metadata(self, cached=True) -> TestMetaData:
        if self.meta and cached:
            return self.meta

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
