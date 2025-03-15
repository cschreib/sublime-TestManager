from abc import ABC, abstractmethod
from typing import Callable, Dict, List
import copy

from .test_data import DiscoveredTest
from .test_suite import TestSuite


class TestFrameworkFactory:
    def __init__(self, create: Callable, default_settings: Dict):
        self.create = create
        self.default_settings = default_settings


registry: Dict[str, TestFrameworkFactory] = {}


def register_framework(name: str, factory_function: Callable, default_settings: Dict):
    global registry
    registry[name] = TestFrameworkFactory(factory_function, default_settings)


def create_framework(name: str, suite: TestSuite, settings: Dict):
    global registry

    if not name in registry:
        raise Exception(f'Unknown test framework "{name}"')

    factory = registry[name]

    new_settings = copy.deepcopy(factory.default_settings)
    new_settings.update(settings)

    return factory.create(suite, new_settings)


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
