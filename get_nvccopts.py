#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Extract compiler and linker options for either the NVIDIA HPC "
            "SDK or HPE Cray Programming Environment."
        )
    )
    parser.add_argument(
        "-e", "--environment",
        choices=("nvhpc", "cray"),
        default="nvhpc",
        help=(
            "Compiler environment to inspect. "
            "'nvhpc' uses mpicxx with fake_nvc++ (default); "
            "'cray' uses 'CC --cray-print-opts=all'."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached options and regenerate them.",
    )
    return parser.parse_args()


def get_machine_id():
    etc_machineid = "/etc/machine-id"

    if os.path.exists(etc_machineid):
        with open(etc_machineid, "rt") as fp:
            return fp.read().strip()

    return socket.gethostname()


if hasattr(shlex, "join"):
    shlex_join = shlex.join
else:
    def shlex_join(split_command):
        return " ".join(
            shlex.quote(arg) for arg in split_command
        )


def run_command(argv, env=None):
    try:
        return subprocess.check_output(
            argv,
            env=env,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(
            "Failed to execute command {!r}: {}".format(
                argv[0],
                exc,
            )
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.output

        if exc.stderr is not None:
            stderr = exc.stderr

        if stderr:
            stderr_text = stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
        else:
            stderr_text = ""

        message = "Command failed: {}".format(
            shlex_join(argv)
        )

        if stderr_text:
            message += "\n{}".format(stderr_text)

        raise RuntimeError(message)


def normalize_options(options):
    """
    Convert compiler-driver options into a form suitable for nvcc.

    - Remove -pthread.
    - Convert:
          -Wl,option1,option2
      into:
          -Xlinker option1 -Xlinker option2
    """
    normalized = []

    for word in options:
        if word == "-pthread":
            continue

        if word.startswith("-Wl,"):
            linker_options = word.split(",")[1:]

            for linker_option in linker_options:
                if linker_option:
                    normalized.extend(
                        ["-Xlinker", linker_option]
                    )
        else:
            normalized.append(word)

    return normalized


def get_nvhpc_options(repo_dir):
    fake_nvcxx = os.path.join(
        repo_dir,
        "fake_nvc++",
    )
    dummy_cu = "dummy.cu"

    environ = dict(os.environ)
    environ["OMPI_CXX"] = fake_nvcxx

    mpicxx_output = run_command(
        ["mpicxx", dummy_cu],
        env=environ,
    )

    try:
        output_text = mpicxx_output.decode("utf-8")
        nvcc_argv = json.loads(output_text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Failed to parse the output from fake_nvc++ as JSON: "
            "{}".format(exc)
        )

    if not isinstance(nvcc_argv, list):
        raise RuntimeError(
            "The output from fake_nvc++ must be a JSON array."
        )

    if len(nvcc_argv) < 2:
        raise RuntimeError(
            "The output from fake_nvc++ contains too few arguments."
        )

    if nvcc_argv[0] != fake_nvcxx:
        raise RuntimeError(
            "Unexpected compiler in fake_nvc++ output: {!r}".format(
                nvcc_argv[0]
            )
        )

    if nvcc_argv[1] != dummy_cu:
        raise RuntimeError(
            "Unexpected source file in fake_nvc++ output: {!r}".format(
                nvcc_argv[1]
            )
        )

    return normalize_options(nvcc_argv[2:])


def get_cray_options():
    cray_output = run_command(
        ["CC", "--cray-print-opts=all"]
    )

    try:
        output_text = cray_output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "Failed to decode the output of "
            "'CC --cray-print-opts=all' as UTF-8: "
            "{}".format(exc)
        )

    try:
        cray_options = shlex.split(
            output_text,
            comments=False,
            posix=True,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Failed to parse the output of "
            "'CC --cray-print-opts=all': "
            "{}".format(exc)
        )

    return normalize_options(cray_options)


def generate_options(environment, repo_dir):
    if environment == "nvhpc":
        options = get_nvhpc_options(repo_dir)
    elif environment == "cray":
        options = get_cray_options()
    else:
        raise ValueError(
            "Unsupported environment: {!r}".format(
                environment
            )
        )

    return os.fsencode(
        shlex_join(options) + "\n"
    )


def main():
    args = parse_args()

    repo_dir = os.path.abspath(
        os.path.dirname(__file__)
    )
    machine_id = get_machine_id()

    options_filename = os.path.join(
        repo_dir,
        "nvccoptions_{}_{}.txt".format(
            machine_id,
            args.environment,
        ),
    )

    try:
        if (
            os.path.exists(options_filename)
            and not args.refresh
        ):
            with open(options_filename, "rb") as fp:
                options_joined = fp.read()
        else:
            options_joined = generate_options(
                args.environment,
                repo_dir,
            )

            with open(options_filename, "wb") as fp:
                fp.write(options_joined)

        sys.stdout.buffer.write(options_joined)
        return 0

    except (RuntimeError, OSError, ValueError) as exc:
        print(
            "{}: error: {}".format(
                os.path.basename(sys.argv[0]),
                exc,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
