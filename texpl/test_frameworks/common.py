import sys
from typing import Optional, List
import os
import xml.sax
from abc import ABC, abstractmethod
import logging
import glob

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


def get_file_prefix(path: str, path_prefix_style='full') -> List[str]:
    if path_prefix_style == 'full':
        return os.path.normpath(path).split(os.sep)
    elif path_prefix_style == 'basename':
        return [os.path.basename(path)]
    elif path_prefix_style == 'none':
        return []
    else:
        raise Exception(f"Unimplemented path style '{path_prefix_style}'")


def change_parent_dir(path: str, old_cwd='.', new_cwd='.'):
    return os.path.normpath(os.path.relpath(os.path.join(old_cwd, path), start=new_cwd))


def is_executable(path: str):
    if sys.platform == 'Windows':
        return os.path.splitext(path)[1].lower() == '.exe'
    else:
        return (os.stat(path).st_mode & 0o111) != 0


def discover_executables(executable_pattern: str, cwd='.') -> List[str]:
    if '*' in executable_pattern:
        old_cwd = os.getcwd()
        os.chdir(cwd)
        executables = [e for e in glob.glob(executable_pattern, recursive=True) if is_executable(e)]
        os.chdir(old_cwd)
        return executables
    else:
        return [executable_pattern]


def get_generic_parser(parser: str, test_data: TestData, framework_id: str, executable: str):
    if parser == 'teamcity':
        return TeamcityOutputParser(test_data, framework_id, executable)

    return None


def make_header(text, length=64, pattern='='):
    remaining = max(0, length - len(text) - 2)
    return f"{pattern*(remaining//2)} {text} {pattern*(remaining - remaining//2)}"


class XmlParser(ABC):
    @abstractmethod
    def startElement(self, name, attrs) -> None:
        """
        Called when a new XML element is open. Includes all attributes.
        """
        pass

    @abstractmethod
    def endElement(self, name, content) -> None:
        """
        Called when an XML element is closed. Includes the inner content, but only
        if this element is listed among the "captured" elements.
        """
        pass

    @abstractmethod
    def output(self, content) -> None:
        """
        Called for non-captured inner content. Generally, this is standard output
        interleaved between elements.
        """
        pass


xml_parser_logger = logging.getLogger('TestExplorerParser.xml-base')


class XmlStreamHandler(xml.sax.handler.ContentHandler):
    def __init__(self, parser: XmlParser, captured_elements: List[str] = []):
        self.parser = parser
        self.captured_elements = captured_elements

        self.current_element: List[str] = []
        self.content = {}

    def clean_xml_content(self, content, tag):
        # Remove first and last entry; will be line jump and indentation whitespace, ignored.
        if not tag in content:
            return ''

        returned_content = content[tag]
        del content[tag]

        if len(returned_content) <= 2:
            return ''

        return ''.join(returned_content[1:-1])

    def startElement(self, name, attrs):
        if len(self.current_element) > 0 and self.current_element[-1] not in self.captured_elements:
            content = self.clean_xml_content(self.content, self.current_element[-1])
            self.parser.output(content)

        attrs_str = ', '.join(['"{}": "{}"'.format(k, v) for k, v in attrs.items()])
        xml_parser_logger.debug('startElement(' + name + ', ' + attrs_str + ')')
        self.current_element.append(name)

        self.parser.startElement(name, attrs)

    def endElement(self, name):
        if name not in self.captured_elements:
            content = self.clean_xml_content(self.content, name)
            self.parser.output(content)

        xml_parser_logger.debug('endElement(' + name + ')')
        self.current_element.pop()

        self.parser.endElement(name, self.clean_xml_content(self.content, name))

    def characters(self, content):
        xml_parser_logger.debug('characters(' + content + ')')
        if len(self.current_element) > 0:
            self.content.setdefault(self.current_element[-1], []).append(content)

            if self.current_element[-1] not in self.captured_elements:
                content = self.content[self.current_element[-1]]
                if len(content) > 1 and len(content[-1].strip()) > 0:
                    output_content = ''.join(content[1:])
                    del content[1:]
                    self.parser.output(output_content)
