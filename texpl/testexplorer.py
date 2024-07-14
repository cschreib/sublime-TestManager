# coding: utf-8
import sys
import logging

import sublime
from sublime_plugin import WindowCommand

from . import __version__


logger = logging.getLogger('TestExplorer.testexplorer')


class TestExplorerVersionCommand(WindowCommand):
    """
    Show the currently installed version of TestExplorer.
    """

    def run(self):
        sublime.message_dialog("You have TestExplorer %s" % __version__)
