# coding: utf-8

__version__ = '1.0.0'


# Import all the commands

from .util import TestManagerPanelWriteCommand, TestManagerPanelAppendCommand

from .list import (TestManagerListCommand, TestManagerRefreshAllCommand, TestManagerRefreshCommand,
                   TestManagerReplaceCommand, TestManagerPartialReplaceCommand, TestManagerToggleShowCommand,
                   TestManagerOpenFile, TestManagerEventListener, TestManagerSetRootCommand)

from .output import (TestManagerOpenSelectedOutput, TestManagerOpenSingleOutput, TestManagerOpenRunOutput,
                     TestManagerOutputRefresh, TestManagerOutputRefreshAllCommand, TestManagerOutputEventListener)

from .discover import (TestManagerDiscoverCommand, TestManagerResetCommand)

from .run import (TestManagerStartSelectedCommand, TestManagerStartCommand, TestManagerStopCommand)

from .suites import (TestManagerAddTestSuiteCommand)

from .testmanager import (TestManagerVersionCommand)

# import test frameworks handlers

from . import test_frameworks

from . import process
