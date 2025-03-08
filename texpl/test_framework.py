from abc import ABC, abstractmethod
from typing import Callable, Dict, List

from .test_data import DiscoveredTest, TestData

registry: Dict[str, Callable] = {}


def register_framework(name: str, factory_function: Callable):
    global registry
    registry[name] = factory_function


class TestFramework(ABC):
    def __init__(self, test_data: TestData, project_root_dir: str):
        self.test_data = test_data
        self.project_root_dir = project_root_dir

    @staticmethod
    def from_json(test_data: TestData, project_root_dir: str, json_data: Dict):
        global registry

        framework_type = json_data['type']
        if not framework_type in registry:
            raise Exception(f'Unknown test framework type "{framework_type}"')

        return registry[framework_type](test_data, project_root_dir, json_data)

    @abstractmethod
    def get_id(self) -> str:
        """
        Return a string containing the unique ID of the framework instance.
        This will normally be the "id" field in the user JSON, but you can override that.
        """
        pass

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
