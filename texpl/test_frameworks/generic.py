from ..test_data import TestData
from .teamcity import OutputParser as TeamcityOutputParser


def get_generic_parser(parser: str, test_data: TestData, framework_id: str, executable: str):
    if parser == 'teamcity':
        return TeamcityOutputParser(test_data, framework_id, executable)

    return None
