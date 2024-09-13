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

class WorkQueue:
    max_tries = 100

    def __init__(self, name):
        self.name = name
        self.worker_queue = queue.Queue(10)
        self.output_queue = {}
        self.output_queue_lock = threading.Lock()
        self.last_task_id = 0

        self.worker_thread = threading.Thread(target=self.process_queue)
        self.worker_thread.start()

    def get_output_queue(self, task_id):
        with self.output_queue_lock:
            if not task_id in self.output_queue:
                self.output_queue[task_id] = queue.Queue(1)

            return self.output_queue[task_id]

    def release_output_queue(self, task_id):
        with self.output_queue_lock:
            if task_id in self.output_queue:
                del self.output_queue[task_id]

    def process_queue_one(self):
        task_id, job = self.worker_queue.get(timeout=1)
        worker_logger.info("[%s,%s,%s] got input, processing...", self.name, threading.get_ident(), task_id)

        try:
            outputs = job()
            worker_logger.info("[%s,%s,%s] got output, sending...", self.name, threading.get_ident(), task_id)
        except Exception as e:
            worker_logger.warning("[%s,%s,%s] got error: %s\n%s", self.name, threading.get_ident(), task_id, e, traceback.format_exc())
            worker_logger.warning("[%s,%s,%s] sending...", self.name, threading.get_ident(), task_id)
            outputs = JobError("Unhandled exception in queue command: %s" % e)

        self.get_output_queue(task_id).put(outputs, timeout=1)

        worker_logger.info("[%s,%s,%s] sent", threading.get_ident(), task_id)

    def process_queue(self):
        while True:
            try:
                worker_logger.debug("wait for input...")
                self.process_queue_one()
            except:
                worker_logger.debug("no input")
                pass

    def next_task_id(self):
        self.last_task_id += 1
        task_id = self.last_task_id
        return task_id

    def dump_stack(self, operation, task_id):
        worker_logger.warning("[%s,%s,%s] %s timed out, worker thread stack:", self.name, threading.get_ident(), task_id, operation)
        for entry in get_thread_stack(self.worker_thread):
            worker_logger.warning("[%s,%s,%s] " + entry.replace('\r', '').split('\n')[0])

    def push_new_job(self, task_id, job, timeout=None):
        self.worker_queue.put((task_id, job), timeout=timeout)

    def get_job_output(self, task_id, timeout=None):
        try:
            queue = self.get_output_queue(task_id)
            return queue.get(timeout=timeout)
        finally:
            self.release_output_queue(task_id)


work_queues = {}
queue_list_lock = threading.Lock()

def get_queue(name: str) -> WorkQueue:
    global work_queues
    global queue_list_lock

    with queue_list_lock:
        if not name in work_queues:
            work_queues[name] = WorkQueue(name)

        return work_queues[name]


def decode(stream, encoding, fallback_encoding=[]):
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


class Cmd:
    def worker_run(self, job: Callable, queue : WorkQueue, task_id=None, timeout=None):
        if not task_id:
            task_id = queue.next_task_id()

        worker_logger.info("[%s,%s,%s] running task", queue.name, threading.get_ident(), task_id)

        if threading.get_ident() == queue.worker_thread.ident:
            # We are already in the worker thread, execute immediately
            worker_logger.info("[%s,%s,%s] immediate call", queue.name, threading.get_ident(), task_id)
            outputs = job()
        else:
            # Schedule on the worker thread and wait for the output now
            try:
                worker_logger.info("[%s,%s,%s] new input, sending...", queue.name, threading.get_ident(), task_id)
                queue.push_new_job(task_id, job)
                worker_logger.info("[%s,%s,%s] wait for output...", queue.name, threading.get_ident(), task_id)
                outputs = queue.get_job_output(task_id, timeout=timeout)
            except Exception as e:
                outputs = JobError("Could not execute command: %s" % e)

        if isinstance(outputs, Exception):
            worker_logger.info("[%s,%s,%s] got error", queue.name, threading.get_ident(), task_id)
            raise outputs

        worker_logger.info("[%s,%s,%s] got output: %s", queue.name, threading.get_ident(), task_id, str(outputs)[:32])
        return outputs

    def cmd(self, command: List[str], queue='default', stdin=None, cwd=None, env={}, stream_reader=None, ignore_errors=False, encoding='utf-8', fallback_encoding=[]):
        queue = get_queue(queue)

        environment = os.environ.copy()
        environment.update(env)
        task_id = queue.next_task_id()

        logger.debug("[%s,%s] cmd: %s", threading.get_ident(), task_id, command)

        def job(command, queue, stdin, cwd, environment, stream_reader, ignore_errors, encoding, fallback_encoding, task_id):
            try:
                if stdin and hasattr(stdin, 'encode'):
                    stdin = stdin.encode(encoding)

                with subprocess.Popen(command,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        cwd=cwd,
                                        env=environment) as proc:
                    if stream_reader is not None:
                        for line in proc.stdout:
                            try:
                                stream_reader(decode(line, encoding, fallback_encoding))
                            except Exception as e:
                                logger.error("[%s,%s,%s] error in stream reader for line: %s\n%s", queue.name, threading.get_ident(), task_id, e, traceback.format_exc())

                        return (proc.poll(), None, None)
                    else:
                        stdout, stderr = proc.communicate(stdin)
                        stdout = decode(stdout, encoding, fallback_encoding)
                        stderr = decode(stderr, encoding, fallback_encoding)

                        logger.debug("[%s,%s,%s] out: (%s) %s", queue.name, threading.get_ident(), task_id, proc.returncode, [stdout[:100]])

                        return (proc.returncode, stdout, stderr)
            except OSError as e:
                if ignore_errors:
                    return (0, '', '')
                sublime.error_message(self.get_executable_error(command[0]))
                return JobError("[%s,%s,%s] Could not execute command: %s" % (threading.get_ident(), task_id, e))
            except UnicodeDecodeError as e:
                if ignore_errors:
                    return (0, '', '')
                sublime.error_message(self.get_decoding_error(command[0], encoding, fallback_encoding))
                return JobError("[%s,%s,%s] Could not execute command: %s" % (threading.get_ident(), task_id, command))

        return self.worker_run(partial(job, command, queue, stdin, cwd, environment, stream_reader, ignore_errors, encoding, fallback_encoding, task_id), queue, task_id=task_id)

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

    def cmd_streamed(self, command: List[str], stream_reader, ignore_errors=False, success_codes=[0], *args, **kwargs):
        error_code, _, _ = self.cmd(command, *args, stream_reader=stream_reader, ignore_errors=ignore_errors, **kwargs)
        if not ignore_errors and error_code not in success_codes:
            command_str = ' '.join(command)
            raise JobError(f'Error when executing command "{command_str}" (exit code {error_code}).')

    def get_executable_error(self, bin):
        return EXECUTABLE_ERROR.format(bin=bin)

    def get_decoding_error(self, bin, encoding, fallback_encoding=[]):
        encodings = [encoding] + fallback_encoding
        return DECODING_ERROR.format(encodings="\n".join(encodings), bin=bin)
