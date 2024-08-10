# coding: utf-8
import os
import subprocess
import sys
import logging
import threading
import queue
from functools import partial
import sys
import traceback
import time
from typing import Callable, List

def get_thread_stack(thread):
    frame = sys._current_frames().get(thread.ident, None)
    if not frame:
        return []

    return traceback.format_stack(f=frame)

import sublime


logger = logging.getLogger('TestExplorer.cmd')
worker_logger = logging.getLogger('TestExplorerWorker')

DECODING_ERROR = ("Could not decode output from {bin}. The following encodings "
                  "were tried:\n\n"
                  "{encodings}\n\n"
                  "Try adjusting the fallback_encodings setting.")

EXECUTABLE_ERROR = ("Executable '{bin}' was not found.")

class JobError(Exception):
    pass

worker_queue = queue.Queue(1)
output_queue = {}
output_queue_lock = threading.Lock()
last_task_id = 0
max_tries = 100

def get_output_queue(task_id):
    global output_queue_lock
    global output_queue

    with output_queue_lock:
        if not task_id in output_queue:
            output_queue[task_id] = queue.Queue(1)

        return output_queue[task_id]

def release_output_queue(task_id):
    global output_queue_lock
    global output_queue

    with output_queue_lock:
        if task_id in output_queue:
            del output_queue[task_id]

def process_queue_one():
    task_id, job = worker_queue.get(timeout=1)
    worker_logger.info("[%s,%s] got input, processing...", threading.get_ident(), task_id)

    try:
        outputs = job()
        worker_logger.info("[%s,%s] got output, sending...", threading.get_ident(), task_id)
    except Exception as e:
        worker_logger.warning("[%s,%s] got error: %s\n%s", threading.get_ident(), task_id, e, traceback.format_exc())
        worker_logger.warning("[%s,%s] sending...", threading.get_ident(), task_id)
        outputs = JobError("Unhandled exception in queue command: %s" % e)

    get_output_queue(task_id).put(outputs, timeout=1)

    worker_logger.info("[%s,%s] sent", threading.get_ident(), task_id)

def process_queue():
    while True:
        try:
            worker_logger.debug("wait for input...")
            process_queue_one()
        except:
            worker_logger.debug("no input")
            pass

def next_task_id():
    global last_task_id
    last_task_id += 1
    task_id = last_task_id
    return task_id

def dump_stack(operation, task_id):
    worker_logger.warning("[%s,%s] %s timed out, worker thread stack:", threading.get_ident(), task_id, operation)
    for entry in get_thread_stack(worker_thread):
        worker_logger.warning("[%s,%s] " + entry.replace('\r', '').split('\n')[0])

def push_new_job(task_id, job):
    num_tries = 0
    while True:
        try:
            worker_queue.put((task_id, job), timeout=0.1)
            return
        except Exception as e:
            worker_logger.debug("[%s,%s] put timed out, waiting some more...", threading.get_ident(), task_id)
            num_tries += 1
            if num_tries == max_tries:
                dump_stack('put', task_id)
                raise e

def get_job_output(task_id, timeout=None):
    try:
        num_tries = 0
        queue = get_output_queue(task_id)

        start = time.time()
        while timeout is None or time.time() - start < timeout:
            try:
                return queue.get(timeout=0.1)
            except Exception as e:
                worker_logger.debug("[%s,%s] get timed out, waiting some more...", threading.get_ident(), task_id)
                num_tries += 1
                if num_tries == max_tries:
                    dump_stack('get', task_id)
                    raise e

        raise Exception(f'Job timeout for task {task_id}')

    finally:
        release_output_queue(task_id)

worker_thread = threading.Thread(target=process_queue)
worker_thread.start()

class Cmd:
    def worker_run(self, job: Callable, task_id=None, timeout=None):
        if not task_id:
            task_id = next_task_id()

        worker_logger.info("[%s,%s] running task", threading.get_ident(), task_id)

        if threading.get_ident() == worker_thread.ident:
            # We are already in the worker thread, execute immediately
            worker_logger.info("[%s,%s] immediate call", threading.get_ident(), task_id)
            outputs = job()
        else:
            # Schedule on the worker thread and wait for the output now
            try:
                worker_logger.info("[%s,%s] new input, sending...", threading.get_ident(), task_id)
                push_new_job(task_id, job)
                worker_logger.info("[%s,%s] wait for output...", threading.get_ident(), task_id)
                outputs = get_job_output(task_id, timeout=timeout)
            except Exception as e:
                outputs = JobError("Could not execute command: %s" % e)

        if isinstance(outputs, Exception):
            worker_logger.info("[%s,%s] got error", threading.get_ident(), task_id)
            raise outputs

        worker_logger.info("[%s,%s] got output: %s", threading.get_ident(), task_id, str(outputs)[:32])
        return outputs

    def worker_run_async(self, job: Callable, on_complete=None, on_exception=None, task_id=None, timeout=None):
        if not task_id:
            task_id = next_task_id()

        worker_logger.info("[%s,%s] running async task", threading.get_ident(), task_id)

        # Spawn a thread to schedule the job on the worker thread and wait for the output
        def async_inner(job, on_complete, on_exception, task_id, timeout):
            try:
                try:
                    worker_logger.info("[%s,%s] async new input, sending...", threading.get_ident(), task_id)
                    push_new_job(task_id, job)
                    worker_logger.info("[%s,%s] async wait for output...", threading.get_ident(), task_id)
                    outputs = get_job_output(task_id, timeout=timeout)
                except Exception as e:
                    outputs = JobError("Could not execute command: %s" % e)

                if isinstance(outputs, Exception):
                    worker_logger.info("[%s,%s] async got error", threading.get_ident(), task_id)
                    logger.debug('async-exception: %s', outputs)
                    if callable(on_exception):
                        sublime.set_timeout(partial(on_exception, outputs), 0)
                else:
                    worker_logger.info("[%s,%s] async got output", threading.get_ident(), task_id)
                    if callable(on_complete):
                        sublime.set_timeout(partial(on_complete, outputs), 0)
            except Exception as e:
                logger.error('async-exception [BUG]: %s', e)

        return threading.Thread(target=partial(async_inner, job, on_complete, on_exception, task_id, timeout))

    def cmd(self, command: List[str], stdin=None, cwd=None, env={}, ignore_errors=False, encoding='utf-8', fallback_encoding=[]):
        environment = os.environ.copy()
        environment.update(env)
        task_id = next_task_id()

        logger.debug("[%s,%s] cmd: %s", threading.get_ident(), task_id, command)

        def job(command, stdin, cwd, environment, ignore_errors, encoding, fallback_encoding, task_id):
            try:
                if stdin and hasattr(stdin, 'encode'):
                    stdin = stdin.encode(encoding)

                proc = subprocess.Popen(command,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        cwd=cwd,
                                        env=environment)

                stdout, stderr = proc.communicate(stdin)

                logger.debug("[%s,%s] out: (%s) %s", threading.get_ident(), task_id, proc.returncode, [stdout[:100]])

                return (proc.returncode, self.decode(stdout, encoding, fallback_encoding), self.decode(stderr, encoding, fallback_encoding))
            except OSError as e:
                if ignore_errors:
                    return (0, '', '')
                sublime.error_message(self.get_executable_error(command[0]))
                return JobError("[%s,%s] Could not execute command: %s" % (threading.get_ident(), task_id, e))
            except UnicodeDecodeError as e:
                if ignore_errors:
                    return (0, '', '')
                sublime.error_message(self.get_decoding_error(command[0], encoding, fallback_encoding))
                return JobError("[%s,%s] Could not execute command: %s" % (threading.get_ident(), task_id, command))

        return self.worker_run(partial(job, command, stdin, cwd, environment, ignore_errors, encoding, fallback_encoding, task_id), task_id=task_id)

    def cmd_string(self, command: List[str], ignore_errors=False, success_codes=[0], *args, **kwargs):
        error_code, stdout, stderr = self.cmd(command, *args, ignore_errors=ignore_errors, **kwargs)
        if not ignore_errors and error_code not in success_codes:
            command_str = ' '.join(command)
            message = stdout if stderr is None else stderr
            if message:
                raise JobError(f'Error when executing command "{command_str}" (exit code {error_code}):\n\n{message}')
            else:
                raise JobError(f'Error when executing command "{command_str}" (exit code {error_code}).')

        return stdout

    def cmd_lines(self, command: List[str], ignore_errors=False, success_codes=[0], *args, **kwargs):
        stdout = self.cmd_string(command, ignore_errors=ignore_errors, success_codes=success_codes, *args, **kwargs)
        return stdout.split('\n')

    def decode(self, stream, encoding, fallback_encoding=[]):
        if not hasattr(stream, 'decode'):
            return stream

        try:
            return stream.decode(encoding)
        except UnicodeDecodeError:
            for enc in fallback_encoding:
                try:
                    return stream.decode(enc)
                except UnicodeDecodeError:
                    pass
            raise

    def get_executable_error(self, bin):
        return EXECUTABLE_ERROR.format(bin=bin)

    def get_decoding_error(self, bin, encoding, fallback_encoding=[]):
        encodings = [encoding] + fallback_encoding
        return DECODING_ERROR.format(encodings="\n".join(encodings), bin=bin)
