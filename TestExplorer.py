# coding: utf-8
import sys
import logging

import sublime

# set up some logging
logging.basicConfig(level=logging.WARNING, format="[%(asctime)s - %(levelname)-8s - %(name)s] %(message)s")
logger = logging.getLogger('TestExplorer')
worker_logger = logging.getLogger('TestExplorerWorker')

# reload modules if necessary
LOAD_ORDER = [
    # base
    '',
    '.util',
    '.cmd',
    '.test_data',
    '.helpers',

    # commands
    '.list',

    # meta
    '.TestExplorer',
]

needs_reload = [n for n, m in list(sys.modules.items()) if n[0:4] == 'texpl' and m is not None]

reloaded = []
for postfix in LOAD_ORDER:
    module = 'texpl' + postfix
    if module in needs_reload:
        reloaded.append(module)
        reload(sys.modules[module])
if reloaded:
    logger.info('Reloaded %s' % ", ".join(reloaded))

# import commands and listeners
from .texpl import *  # noqa

def plugin_loaded():
    settings = sublime.load_settings('TestExplorer.sublime-settings')

    # set log level
    lvl = getattr(logging, settings.get('log_level', '').upper(), logging.WARNING)
    logger.setLevel(lvl)

    worker_lvl = getattr(logging, settings.get('worker_log_level', '').upper(), logging.WARNING)
    worker_logger.setLevel(worker_lvl)

def plugin_unloaded():
    logging.shutdown()
