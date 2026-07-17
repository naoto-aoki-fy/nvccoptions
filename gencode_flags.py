#!/usr/bin/env python3

from __future__ import print_function

import subprocess
import sys


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


def output_versions(versions):
    unique_versions = sorted(set(versions))
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


def main():
    try:
        versions = query_sm_versions()
    except RuntimeError as exc:
        print(
            "error: {0}".format(exc),
            file=sys.stderr,
        )
        return 1

    output_versions(versions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
