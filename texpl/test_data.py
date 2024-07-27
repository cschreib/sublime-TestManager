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

class TestLocation:
    def __init__(self, file='', line=0):
        self.file = file
        self.line = line

    @staticmethod
    def from_json(json_data: Optional[dict]):
        if json_data is None:
            return None

        return TestLocation(file=json_data['file'], line=json_data['line'])

class TestItem:
    def __init__(self, name='root', location=None, last_status='not_run', run_status='not_running', last_run=None):
        self.name: str = name
        self.location: Optional[TestLocation] = location
        self.last_status: str = last_status
        self.run_status: str = run_status
        self.last_run: Optional[datetime] = last_run
        self.children: Optional[Dict[str, TestItem]] = None

    @staticmethod
    def from_json(json_data: dict):
        item = TestItem(name=json_data['name'],
                        location=TestLocation.from_json(json_data.get('location', None)),
                        last_status=json_data['last_status'],
                        run_status=json_data['run_status'],
                        last_run=date_from_json(json_data.get('last_run', None)))

        if 'children' in json_data:
            item.children = {}
            for c in json_data['children']:
                child = TestItem.from_json(c)
                item.children[child.name] = child

        return item

def get_test_stats(item: TestItem):
    def add_one_to_stats(stats: dict, item: TestItem):
        stats[item.last_status] += 1
        stats[item.run_status] += 1
        stats['total'] += 1
        if item.last_run is not None:
            if stats['last_run'] is not None:
                stats['last_run'] = max(stats['last_run'], item.last_run)
            else:
                stats['last_run'] = item.last_run

    def add_to_stats(stats: dict, item: TestItem):
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
            self.root = TestItem()
        else:
            self.root = root

    @staticmethod
    def from_json(json_data: dict):
        return TestList(root=TestItem.from_json(json_data))

    @staticmethod
    def from_file(file_path):
        with open(file_path, 'r') as f:
            json_data = json.load(f)

        return TestList.from_json(json_data)

    def is_empty(self):
        return not self.root.children

    def find_test(self, item_path) -> Optional[TestItem]:
        parent = self.root
        for i in range(len(item_path)):
            if parent.children is None:
                return None

            if not item_path[i] in parent.children:
                return None

            parent = parent.children[item_path[i]]

        return parent


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
        os.makedirs(self.location, exist_ok=True)

        json_meta = {
            'last_discovery': '2024-05-04T11:05:12',
            'running': False
        }

        json_tests = {'name': 'root', 'last_status': 'failed', 'run_status': 'not_running', 'children': [
            {'name': 'Test.exe', 'last_status': 'failed', 'run_status': 'not_running', 'children': [
                {'name': 'TestCase1', 'last_status': 'failed', 'run_status': 'not_running', 'children': [
                    {'name': 'test_this', 'last_status': 'passed', 'run_status': 'not_running', 'location': {'file': '../texpl/list.py', 'line': 5}, 'last_run': '2024-05-04T12:05:12'},
                    {'name': 'test_that', 'last_status': 'failed', 'run_status': 'not_running', 'location': {'file': '../texpl/list.py', 'line': 6}, 'last_run': '2024-05-04T11:05:12'},
                    {'name': 'test_them', 'last_status': 'skipped', 'run_status': 'not_running', 'location': {'file': '../texpl/list.py', 'line': 7}, 'last_run': '2024-05-04T11:05:14'},
                    {'name': 'test_new', 'last_status': 'not_run', 'run_status': 'not_running', 'location': {'file': '../texpl/list.py', 'line': 10}, 'last_run': None},
                ]},
                {'name': 'TestCase2', 'last_status': 'passed', 'run_status': 'not_running', 'children': [
                    {'name': 'test_me', 'last_status': 'passed', 'run_status': 'not_running', 'location': {'file': '../texpl/util.py', 'line': 5}, 'last_run': '2024-05-03T13:05:12'}
                ]},
                {'name': 'TestCase3', 'last_status': 'passed', 'run_status': 'running', 'children': [
                    {'name': 'test_me1', 'last_status': 'passed', 'run_status': 'not_running', 'location': {'file': '../texpl/cmd.py', 'line': 5}, 'last_run': '2024-05-04T12:05:12'},
                    {'name': 'test_me2', 'last_status': 'passed', 'run_status': 'queued', 'location': {'file': '../texpl/cmd.py', 'line': 6}, 'last_run': '2024-05-04T12:05:12'},
                    {'name': 'test_me', 'last_status': 'passed', 'run_status': 'running', 'location': {'file': '../texpl/cmd.py', 'line': 7}, 'last_run': '2024-05-04T12:05:12'},
                ]}
            ]}
        ]}

        with open(os.path.join(self.location, TEST_DATA_MAIN_FILE), 'w') as f:
            json.dump(json_meta, f, indent=2)

        with open(os.path.join(self.location, TEST_DATA_TESTS_FILE), 'w') as f:
            json.dump(json_tests, f, indent=2)

    def get_test_list(self, cached=True) -> TestList:
        if self.tests and cached:
            return self.tests

        self.tests = TestList.from_file(os.path.join(self.location, TEST_DATA_TESTS_FILE))
        self.stats = None

        return self.tests

    def get_test_metadata(self, cached=True):
        if self.meta and cached:
            return self.meta

        with open(os.path.join(self.location, TEST_DATA_MAIN_FILE), 'r') as f:
            self.meta = json.load(f)

        self.meta['last_discovery'] = date_from_json(self.meta['last_discovery'])

        return self.meta

    def get_last_discovery(self, cached=True):
        return self.get_test_metadata(cached=cached)['last_discovery']

    def is_running_tests(self, cached=True):
        return self.get_test_metadata(cached=cached)['running']

    def get_global_test_stats(self, cached=True):
        if self.stats and cached:
            return self.stats

        self.stats = get_test_stats(self.get_test_list(cached=cached).root)
        return self.stats
