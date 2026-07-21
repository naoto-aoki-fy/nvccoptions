#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
import io
import json
import os
import subprocess
import sys
import time


TARGET_EXECUTABLE = "nvc++"


def executable_basename(value):
    if not isinstance(value, str):
        return ""

    return value.replace("\\", "/").rsplit("/", 1)[-1]


def process_belongs_to_current_user(process, current_uid, current_user):
    try:
        uids = process.uids()
    except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
        uids = None

    if uids is not None and getattr(uids, "real", None) == current_uid:
        return True

    try:
        return process.username() == current_user
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def is_target_process(process):
    try:
        name = process.name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        name = ""

    if executable_basename(name) == TARGET_EXECUTABLE:
        return True

    try:
        exe = process.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        exe = ""

    if executable_basename(exe) == TARGET_EXECUTABLE:
        return True

    try:
        cmdline = process.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        cmdline = []

    if cmdline and executable_basename(cmdline[0]) == TARGET_EXECUTABLE:
        return True

    return False


def safe_process_environment(process):
    try:
        return process.environ()
    except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
        return None


def safe_process_path(process, cmdline):
    try:
        exe = process.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        exe = ""

    if exe:
        return exe

    if cmdline:
        return cmdline[0]

    try:
        return process.name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None


def process_record(process):
    try:
        cmdline = process.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        cmdline = []

    return {
        "pid": process.pid,
        "syscall": "psutil",
        "path": safe_process_path(process, cmdline),
        "argv": cmdline,
        "env": safe_process_environment(process),
        "return_value": 0,
    }


def write_record(destination, record):
    print(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        file=destination,
    )
    destination.flush()


def snapshot_user_target_processes(destination, seen_pids):
    current_uid = os.getuid()
    current_user = None

    try:
        current_user = psutil.Process().username()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass

    found = 0

    for process in psutil.process_iter():
        if process.pid in seen_pids:
            continue

        if not process_belongs_to_current_user(
            process,
            current_uid,
            current_user,
        ):
            continue

        if not is_target_process(process):
            continue

        try:
            record = process_record(process)
        except psutil.NoSuchProcess:
            continue

        seen_pids.add(process.pid)
        found += 1
        write_record(destination, record)

    return found


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Run a command and use psutil to collect visible nvc++ "
            "process argv and environment records for the executing user."
        )
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help="Output JSON Lines file; write to standard output if omitted",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.01,
        help="Polling interval in seconds (default: 0.01)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to execute, optionally preceded by --",
    )
    return parser


def normalize_command(command):
    if command and command[0] == "--":
        command = command[1:]
    return command


def open_output(filename):
    if filename is None or filename == "-":
        return sys.stdout, False

    return io.open(filename, "w", encoding="utf-8", newline="\n"), True


def main():
    global psutil

    try:
        import psutil
    except ImportError:
        print(
            "error: psutil is required for psutil trace mode",
            file=sys.stderr,
        )
        return 1

    args = build_argument_parser().parse_args()
    command = normalize_command(args.command)

    if not command:
        print("error: command is required", file=sys.stderr)
        return 1

    output = None
    close_output = False
    seen_pids = set()

    try:
        output, close_output = open_output(args.output)
        process = subprocess.Popen(command)

        while process.poll() is None:
            snapshot_user_target_processes(output, seen_pids)
            time.sleep(max(args.interval, 0.001))

        snapshot_user_target_processes(output, seen_pids)
        return process.returncode

    except OSError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 1

    finally:
        if close_output and output is not None:
            output.close()


if __name__ == "__main__":
    sys.exit(main())
