#!/usr/bin/env python3

from __future__ import print_function

import argparse
import io
import os
import socket
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Get NVIDIA GPU SM versions from compute capabilities."
    )
    parser.add_argument(
        "--mode",
        choices=("make", "raw"),
        default="make",
        help=(
            "Output format. "
            "'make' prints NVCC_GENCODE_FLAGS, "
            "while 'raw' prints one SM version per line. "
            "Default: make."
        ),
    )
    return parser.parse_args()


def read_text_file(path):
    with io.open(path, mode="r", encoding="utf-8") as file_object:
        return file_object.read()


def write_text_file(path, content):
    with io.open(path, mode="w", encoding="utf-8") as file_object:
        file_object.write(content)


def get_machine_id():
    machine_id_path = "/etc/machine-id"

    try:
        if os.path.isfile(machine_id_path):
            machine_id = read_text_file(machine_id_path).strip()
            if machine_id:
                return machine_id
    except IOError:
        pass

    return socket.gethostname()


def query_sm_versions():
    command = [
        "nvidia-smi",
        "--query-gpu=compute_cap",
        "--format=csv,noheader",
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        if exc.errno == 2:
            raise RuntimeError("nvidia-smi was not found.")

        raise RuntimeError(
            "Failed to execute nvidia-smi: {0}".format(exc)
        )

    stdout_data, stderr_data = process.communicate()

    stdout_text = stdout_data.decode("utf-8", "replace")
    stderr_text = stderr_data.decode("utf-8", "replace").strip()

    if process.returncode != 0:
        if stderr_text:
            raise RuntimeError(
                "nvidia-smi failed: {0}".format(stderr_text)
            )

        raise RuntimeError("nvidia-smi failed.")

    sm_versions = []

    for line in stdout_text.splitlines():
        compute_capability = line.strip()

        if not compute_capability:
            continue

        parts = compute_capability.split(".", 1)

        if len(parts) != 2:
            raise RuntimeError(
                "Invalid compute capability: {0!r}".format(
                    compute_capability
                )
            )

        try:
            major = int(parts[0])
            minor = int(parts[1])
        except ValueError:
            raise RuntimeError(
                "Invalid compute capability: {0!r}".format(
                    compute_capability
                )
            )

        sm_versions.append(major * 10 + minor)

    if not sm_versions:
        raise RuntimeError(
            "No GPU compute capabilities were returned."
        )

    return sm_versions


def read_cached_versions(cache_path):
    if not os.path.isfile(cache_path):
        return None

    try:
        content = read_text_file(cache_path)
        versions = []

        for line in content.splitlines():
            line = line.strip()

            if line:
                versions.append(int(line))

        if versions:
            return versions
    except (IOError, ValueError):
        pass

    return None


def write_cached_versions(cache_path, versions):
    content = "".join(
        "{0}\n".format(version) for version in versions
    )
    temporary_path = cache_path + ".tmp"

    try:
        write_text_file(temporary_path, content)

        if os.path.exists(cache_path):
            os.remove(cache_path)

        os.rename(temporary_path, cache_path)
    except OSError as exc:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass

        raise RuntimeError(
            "Failed to write cache file {0}: {1}".format(
                cache_path,
                exc,
            )
        )


def output_versions(versions, mode):
    unique_versions = sorted(set(versions))

    if mode == "make":
        flags = []

        for version in unique_versions:
            flags.append(
                "-gencode=arch=compute_{0},code=sm_{0}".format(
                    version
                )
            )

        print(
            "NVCC_GENCODE_FLAGS = {0}".format(
                " ".join(flags)
            )
        )
    else:
        for version in unique_versions:
            print(version)


def main():
    args = parse_args()

    try:
        script_path = os.path.abspath(__file__)
    except NameError:
        script_path = os.path.abspath(sys.argv[0])

    script_directory = os.path.dirname(script_path)
    machine_id = get_machine_id()
    cache_filename = "smver_{0}.txt".format(machine_id)
    cache_path = os.path.join(
        script_directory,
        cache_filename,
    )

    versions = read_cached_versions(cache_path)

    if versions is None:
        try:
            versions = query_sm_versions()
            write_cached_versions(cache_path, versions)
        except RuntimeError as exc:
            print(
                "error: {0}".format(exc),
                file=sys.stderr,
            )
            return 1

    output_versions(versions, args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
