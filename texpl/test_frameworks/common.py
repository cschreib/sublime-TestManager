from typing import Optional
import os

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
