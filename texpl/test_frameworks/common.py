from typing import Optional
import os

from ..test_data import TestData
from .teamcity import OutputParser as TeamcityOutputParser


def get_working_directory(user_cwd: Optional[str], project_root_dir: str):
    if user_cwd is not None:
        cwd = user_cwd
        if not os.path.isabs(cwd):
            cwd = os.path.join(project_root_dir, cwd)
    else:
        cwd = project_root_dir

    return cwd


def make_executable_path(executable: str, project_root_dir: str):
    return os.path.join(project_root_dir, executable) if not os.path.isabs(executable) else executable


def get_generic_parser(parser: str, test_data: TestData, framework_id: str, executable: str):
    if parser == 'teamcity':
        return TeamcityOutputParser(test_data, framework_id, executable)

    return None
