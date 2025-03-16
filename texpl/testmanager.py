# coding: utf-8
import logging

import sublime
from sublime_plugin import WindowCommand

from . import __version__


logger = logging.getLogger('TestManager.TestManager')


class TestManagerVersionCommand(WindowCommand):
    """
    Show the currently installed version of TestManager.
    """

    def run(self):
        sublime.message_dialog("You have TestManager %s" % __version__)
