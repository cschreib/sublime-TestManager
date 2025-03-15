from abc import ABC, abstractmethod
from typing import Callable, Dict, List

from .test_data import DiscoveredTest
from .test_suite import TestSuite

registry: Dict[str, Callable] = {}


def register_framework(name: str, factory_function: Callable):
    global registry
    registry[name] = factory_function


def create_framework(name: str, suite: TestSuite, settings: Dict):
    global registry

    if not name in registry:
        raise Exception(f'Unknown test framework "{name}"')

    return registry[name](suite, settings)


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
