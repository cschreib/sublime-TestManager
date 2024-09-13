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
        pass

    @abstractmethod
    def discover(self) -> List[DiscoveredTest]:
        pass
