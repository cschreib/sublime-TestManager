# coding: utf-8

__version__ = '1.0.0'


# Import all the commands

from .list import (TestExplorerListCommand, TestExplorerRefreshCommand,
                   TestExplorerDiscoverCommand,TestExplorerReplaceCommand,
                   TestExplorerStartCommand, TestExplorerStopCommand,
                   TestExplorerToggleShowCommand)

from .testexplorer import (TestExplorerVersionCommand)

# import test frameworks handlers

from . import test_frameworks
