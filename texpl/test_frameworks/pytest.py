import os
import json
import logging
from typing import Dict, List, Optional

from ..test_framework import TestFramework, register_framework
from ..test_data import DiscoveredTest, DiscoveryError, TestLocation
from ..cmd import Cmd

PYTEST_DISCOVERY_PLUGIN_PATH = 'pytest_plugins'
PYTEST_DISCOVERY_PLUGIN = 'sublime_discovery'
PYTEST_DISCOVERY_HEADER = 'SUBLIME_DISCOVERY: '

# Pytest returns 5 if no test was found.
PYTEST_SUCCESS_CODES = [0, 5]

logger = logging.getLogger('TestExplorer.pytest')

def get_os_python_path():
    python_path = os.environ.get('PYTHONPATH')
    if not python_path:
        return []

    return python_path.split(os.pathsep)


def get_os_pytest_plugins():
    plugins = os.environ.get('PYTEST_PLUGINS')
    if not plugins:
        return []

    return plugins.split(',')


class PyTest(TestFramework, Cmd):
    def __init__(self, python: str = 'python', env: Dict[str,str] = {}, cwd: Optional[str] = None, args: List[str] = []):
        self.python = python
        self.env = env
        self.cwd = cwd
        self.args = args

    @staticmethod
    def from_json(json_data: Dict):
        assert json_data['type'] == 'pytest'
        return PyTest(python=json_data.get('python', 'python'),
                      env=json_data.get('env', {}),
                      cwd=json_data.get('cwd', None),
                      args=json_data.get('args', []))

    def discover(self, project_root_dir: str) -> List[DiscoveredTest]:
        # Default discovery output of pytest does not contain file & line numbers.
        # We can import our own pytest plugin to fill the gap.
        env = self.env.copy()
        env['PYTEST_PLUGINS'] = ','.join(get_os_pytest_plugins() + [PYTEST_DISCOVERY_PLUGIN])
        here_path = os.path.dirname(os.path.abspath(__file__))
        plugin_path = os.path.join(here_path, PYTEST_DISCOVERY_PLUGIN_PATH)
        env['PYTHONPATH'] = os.pathsep.join(get_os_python_path() + [plugin_path])

        # Set up current working directory. Default to the project root dir.
        if self.cwd is not None:
            cwd = self.cwd
            if not os.path.isabs(cwd):
                cwd = os.path.join(project_root_dir, cwd)
        else:
            cwd = project_root_dir

        discover_args = [self.python, '-m', 'pytest', '--collect-only', '-q']
        lines = self.cmd_lines(discover_args + self.args, env=env, cwd=cwd, success_codes=PYTEST_SUCCESS_CODES)
        return self.parse_discovery(lines, cwd, project_root_dir)

    def parse_discovered_test(self, test: Dict, working_directory: str, project_directory: str):
        # Make file path relative to project directory.
        file = os.path.relpath(os.path.join(working_directory, test['file']), start=project_directory)

        # Make full name relative to project directory.
        # NB: the 'path' here points to the file where the test was discovered.
        # The 'file' variable above points to the file where the test is defined.
        # They are usually the same, except when tests are imported.
        path = test['name'].split('::')
        relfile =  os.path.normpath(os.path.relpath(os.path.join(working_directory, path[0]), start=project_directory))
        path = relfile.split(os.sep) + path[1:]

        return DiscoveredTest(full_name=path, location=TestLocation(file=file, line=test['line']))

    def parse_discovery(self, lines: List[str], working_directory: str, project_directory: str) -> List[DiscoveredTest]:
        for line in lines:
            if PYTEST_DISCOVERY_HEADER in line:
                line = line.replace(PYTEST_DISCOVERY_HEADER, '')
                logger.info(line)

                data = json.loads(line)
                if data['errors']:
                    raise DiscoveryError('Error when discovering tests. See panel for more information.', details='\n'.join(data['errors']))

                return [self.parse_discovered_test(t, working_directory, project_directory) for t in data['tests']]

        raise DiscoveryError('Could not find test discovery data; pytest plugin compatibility issue?')

register_framework('pytest', PyTest.from_json)
