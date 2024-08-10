# coding: utf-8

__version__ = '1.0.0'


# Import all the commands

from .util import TestExplorerPanelWriteCommand, TestExplorerPanelAppendCommand

from .list import (TestExplorerListCommand, TestExplorerRefreshCommand,
                   TestExplorerReplaceCommand, TestExplorerToggleShowCommand,
                   TestExplorerStartSelectedCommand,
                   TestExplorerOpenFile)

from .discover import (TestExplorerDiscoverCommand)

from .run import (TestExplorerStartCommand, TestExplorerStopCommand)

from .testexplorer import (TestExplorerVersionCommand)

# import test frameworks handlers

from . import test_frameworks
