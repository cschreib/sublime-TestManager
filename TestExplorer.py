# coding: utf-8
import logging

log_format = "[%(asctime)s - %(levelname)-8s - %(name)s] %(message)s"
logging.basicConfig(level=logging.WARNING, format=log_format)
logging.basicConfig(filename='~/.subl.log', encoding='utf-8', level=logging.DEBUG)

logger = logging.getLogger('TestExplorer')
worker_logger = logging.getLogger('TestExplorerWorker')
parser_logger = logging.getLogger('TestExplorerParser')

import sublime
from .texpl import *

def plugin_loaded():
    settings = sublime.load_settings('TestExplorer.sublime-settings')

    # set log level
    lvl = getattr(logging, settings.get('log_level', '').upper(), logging.WARNING)
    logger.setLevel(lvl)

    worker_lvl = getattr(logging, settings.get('worker_log_level', '').upper(), logging.WARNING)
    worker_logger.setLevel(worker_lvl)

    parser_lvl = getattr(logging, settings.get('parser_log_level', '').upper(), logging.WARNING)
    parser_logger.setLevel(parser_lvl)

    # set file output
    filename = settings.get('log_file')
    if filename:
        handler = logging.FileHandler(filename)
        formatter = logging.Formatter(fmt=log_format, style='%')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

def plugin_unloaded():
    logging.shutdown()
