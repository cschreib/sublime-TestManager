import json
import os
from datetime import datetime

TEST_DATA_MAIN_FILE = 'main.json'
TEST_DATA_TESTS_FILE = 'tests.json'

def get_test_stats(item: dict):
    def add_one_to_stats(stats: dict, item: dict):
        stats[item['last_status']] += 1
        stats[item['run_status']] += 1
        stats['total'] += 1
        if item['last_run'] is not None:
            if stats['last_run'] is not None:
                stats['last_run'] = max(stats['last_run'], item['last_run'])
            else:
                stats['last_run'] = item['last_run']

    def add_to_stats(stats: dict, item: dict):
        if 'children' in item:
            for c in item['children']:
                add_to_stats(stats, c)
        else:
            add_one_to_stats(stats, item)

    stats = {'failed': 0, 'skipped': 0, 'passed': 0, 'not_run': 0, 'not_running': 0, 'running': 0, 'queued': 0, 'total': 0, 'last_run': None}
    add_to_stats(stats, item)
    return stats

class TestData:
    def __init__(self, location):
        self.location = location
        self.tests = None
        self.stats = None
        self.meta = None

    def init(self):
        self.meta = {
            'last_discovery': '2024-05-04T11:05:12',
            'running': False
        }

        self.tests = {'children': [
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

        os.makedirs(self.location, exist_ok=True)

        with open(os.path.join(self.location, TEST_DATA_MAIN_FILE), 'w') as f:
            json.dump(self.meta, f)

        with open(os.path.join(self.location, TEST_DATA_TESTS_FILE), 'w') as f:
            json.dump(self.tests, f)

    def convert_dates(self, data):
        if 'last_discovery' in data and data['last_discovery']:
            data['last_discovery'] = datetime.fromisoformat(data['last_discovery'])
        if 'last_run' in data and data['last_run']:
            data['last_run'] = datetime.fromisoformat(data['last_run'])

        if 'children' in data:
            for c in data['children']:
                self.convert_dates(c)

    def get_test_list(self, cached=True):
        if self.tests and cached:
            return self.tests

        with open(os.path.join(self.location, TEST_DATA_TESTS_FILE), 'r') as f:
            self.tests = json.load(f)

        self.convert_dates(self.tests)
        self.stats = None

        return self.tests

    def get_test_metadata(self, cached=True):
        if self.meta and cached:
            return self.meta

        with open(os.path.join(self.location, TEST_DATA_MAIN_FILE), 'r') as f:
            self.meta = json.load(f)

        self.convert_dates(self.meta)
        return self.meta

    def get_last_discovery(self, cached=True):
        return self.get_test_metadata(cached=cached)['last_discovery']

    def is_running_tests(self, cached=True):
        return self.get_test_metadata(cached=cached)['running']

    def find_test(self, item_path, cached=True):
        found = None
        lst = self.get_test_list(cached=cached)
        for p in item_path:
            found = None
            if lst is None:
                break

            for item in lst:
                if item['name'] == p:
                    found = item
                    break

            if found is None:
                return None

            if 'children' in found:
                lst = found['children']
            else:
                lst = None

        return found

    def get_global_test_stats(self, cached=True):
        if self.stats and cached:
            return self.stats

        self.stats = get_test_stats(self.get_test_list(cached=cached))
        return self.stats
