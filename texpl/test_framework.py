from abc import ABC, abstractmethod
from typing import Callable, Dict, List
import copy
import traceback
import logging

from .test_data import DiscoveredTest
from .test_suite import TestSuite

logger = logging.getLogger('TestExplorer.frameworks')


class TestFrameworkFactory:
    def __init__(self, create: Callable, default_settings: Dict):
        self.create = create
        self.default_settings = default_settings


class FrameworkError(BaseException):
    def __init__(self, message: str):
        self.message = message


registry: Dict[str, TestFrameworkFactory] = {}


def register_framework(name: str, factory_function: Callable, default_settings: Dict):
    global registry
    registry[name] = TestFrameworkFactory(factory_function, default_settings)


def get_framework_factory(name: str):
    global registry

    if not name in registry:
        raise FrameworkError(f'Unknown test framework "{name}".')

    return registry[name]


def create_framework(name: str, suite: TestSuite, settings: Dict):
    factory = get_framework_factory(name)

    new_settings = copy.deepcopy(factory.default_settings)
    new_settings.update(settings)

    try:
        return factory.create(suite, new_settings)
    except Exception as e:
        logger.error(traceback.format_exc())
        raise FrameworkError(f'Error creating test suite "{suite.suite_id}": {str(e)}.')


def get_framework_default_settings(name: str):
    factory = get_framework_factory(name)
    return factory.default_settings


def get_available_frameworks():
    return list(registry.keys())


class TestFramework(ABC):
    def __init__(self, suite: TestSuite):
        self.test_data = suite.test_data
        self.project_root_dir = suite.project_root_dir
        self.suite = suite

    @abstractmethod
    def discover(self) -> List[DiscoveredTest]:
        """
        Run test discovery and return a list of discovered tests. The discovered tests will
        be registered with the TestData class automatically, you do not need to do this yourself.
        """
        pass

    @abstractmethod
    def run(self, grouped_tests: Dict[str, List[str]]) -> None:
        """
        Run the tests selected in 'grouped_tests'.
        The tests are grouped by "executable" (as defined during test discovery), for efficiency.
        While tests are running, it is expected that this function will notify the TestData
        class of any of the following events:
         - TestData.notify_test_started()
         - TestData.notify_test_output()
         - TestData.notify_test_finished()
        """
        pass
