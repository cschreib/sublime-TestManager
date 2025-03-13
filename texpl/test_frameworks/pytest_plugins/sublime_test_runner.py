# Inspired from https://github.com/kondratyev-nv/vscode-python-test-adapter
import pytest
import json
import os

# report.longreprtext requires >= 3.0
PYTEST_MIN_VERSION = 3

DISCOVERY_HEADER = 'SUBLIME_DISCOVERY: '
STATUS_HEADER = 'SUBLIME_STATUS: '


def get_file(item, config):
    try:
        # location is (file path, line, test name).
        return os.path.join(config.rootpath, item.location[0])
    except:
        return item.nodeid.split('::')[0]


def get_line_number(item):
    try:
        # location is (file path, line, test name).
        # Line number is zero-based.
        return item.location[1] + 1
    except:
        # Fall back to start of the file, for lack of better information.
        return 1


def make_name(item):
    if isinstance(item, pytest.File):
        return os.path.relpath(item.path, start=os.getcwd())
    else:
        return (make_name(item.parent) + '::' + item.name) if item.parent.name != "" else item.name


collected_errors = []


def pytest_collectreport(report):
    try:
        if report.failed:
            collected_errors.append({'message': report.longreprtext})
    except:
        pass


def pytest_collection_finish(session):
    global collected_errors

    try:
        tests = [{'name': make_name(item), 'file': get_file(item, session.config),
                  'line': get_line_number(item)} for item in session.items]
    except:
        tests = []

    if int(pytest.__version__.split('.')[0]) < PYTEST_MIN_VERSION:
        collected_errors = [{'location': None, 'message': f'Error: Pytest {PYTEST_MIN_VERSION}.0 or later is required for this SublimeText plugin to work.'}]
        tests = []

    print('\n' + DISCOVERY_HEADER + json.dumps({'tests': tests, 'errors': collected_errors}))


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_report_teststatus(report):
    print('\n' + STATUS_HEADER + json.dumps({'status': report.outcome}))
    yield


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_protocol(item):
    print('\n' + STATUS_HEADER + json.dumps({'test': make_name(item), 'status': 'started'}))
    yield
    print('\n' + STATUS_HEADER + json.dumps({'test': make_name(item), 'status': 'finished'}))


def make_header(text):
    total_length = 64
    remaining = max(0, total_length - len(text) - 2)
    return f"{'='*(remaining//2)} {text} {'='*(remaining - remaining//2)}"


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_logreport(report):
    longrepr = report.longreprtext
    prev = ''
    if len(longrepr) > 0:
        print('\n' + STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{make_header("FAILURES")}\n'}))
        for line in longrepr.split("\n"):
            print(STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{line}\n'}))
        prev = '\n\n'
    stdout = report.capstdout
    if len(stdout) > 0:
        print('\n' + STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{prev}{make_header("STDOUT")}\n'}))
        for line in stdout.split("\n"):
            print(STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{line}\n'}))
        prev = '\n\n'
    stderr = report.capstderr
    if len(stderr) > 0:
        print('\n' + STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{prev}{make_header("STDERR")}\n'}))
        for line in stderr.split("\n"):
            print(STATUS_HEADER + json.dumps({'status': 'output', 'content': f'{line}\n'}))
    yield
