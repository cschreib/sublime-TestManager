from abc import ABC, abstractmethod
from typing import Callable, Dict, List

from .test_data import DiscoveredTest

registry: Dict[str, Callable] = {}

def register_framework(name: str, factory_function: Callable):
    global registry
    registry[name] = factory_function

class TestFramework(ABC):
    @staticmethod
    def from_json(json_data: Dict):
        global registry

        framework_type = json_data['type']
        if not framework_type in registry:
            raise Exception(f'Unknown test framework type "{framework_type}"')

        return registry[framework_type](json_data)

    @abstractmethod
    def discover(self, project_root_dir: str) -> List[DiscoveredTest]:
        pass
