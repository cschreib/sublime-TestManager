from typing import Dict, List, Optional

from .errors import FrameworkError
from .test_data import TestData


class TestSuite:
    def __init__(self, suite_id: str, test_data: TestData, project_root_dir: str,
                 custom_prefix: Optional[str],
                 path_prefix_style: str,
                 framework_name: str, framework_settings: Dict):
        self.test_data = test_data
        self.project_root_dir = project_root_dir
        self.suite_id = suite_id
        self.custom_prefix = custom_prefix
        self.path_prefix_style = path_prefix_style

        from .test_framework import create_framework
        self.framework = create_framework(framework_name,
                                          self,
                                          framework_settings)

    @staticmethod
    def from_json(test_data: TestData, project_root_dir: str, settings: Dict):
        if 'id' not in settings:
            raise FrameworkError('Missing "id" in suite definition.')
        if 'framework' not in settings:
            raise FrameworkError('Missing "framework" in suite definition.')

        return TestSuite(suite_id=settings['id'],
                         test_data=test_data,
                         project_root_dir=project_root_dir,
                         custom_prefix=settings.get('custom_prefix', None),
                         path_prefix_style=settings.get('path_prefix_style', 'full'),
                         framework_name=settings['framework'],
                         framework_settings=settings)

    def discover(self):
        return self.framework.discover()

    def run(self, grouped_tests: Dict[str, List[str]]):
        self.framework.run(grouped_tests)
