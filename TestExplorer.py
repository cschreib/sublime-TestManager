# coding: utf-8
import logging

log_format = "[%(asctime)s - %(levelname)-8s - %(name)-32s] %(message)s"

def setup_log_file(logger, filename):
    for handler in logger.handlers:
        logger.removeHandler(handler)

    if filename:
        handler = logging.FileHandler(filename)
        handler.setFormatter(logging.Formatter(fmt=log_format, style='%'))
        logger.addHandler(handler)

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
    setup_log_file(logger, settings.get('log_file'))
    setup_log_file(worker_logger, settings.get('worker_log_file'))
    setup_log_file(parser_logger, settings.get('parser_log_file'))

def plugin_unloaded():
    logging.shutdown()
