#!/usr/bin/env python3

from __future__ import print_function

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
        "-e",
        "--environment",
        choices=("nvhpc", "cray"),
        default="nvhpc",
        help=(
            "Compiler environment to inspect. "
            "'nvhpc' uses 'mpicxx -showme:compile' and "
            "'mpicxx -showme:link' (default); "
            "'cray' uses 'CC --cray-print-opts=cflags' and "
            "'CC --cray-print-opts=libs'."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("make", "raw"),
        default="make",
        help=(
            "Output format. "
            "'make' emits CFLAGS, LDFLAGS, and NVCC_LDFLAGS "
            "Makefile assignments (default); "
            "'raw' emits the three corresponding values, one per line."
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


def decode_utf8(data, description):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "Failed to decode {} as UTF-8: {}".format(
                description,
                exc,
            )
        )


def run_command(argv, env=None):
    """
    Execute a command and return its standard output as bytes.

    Popen.communicate() is used instead of relying on newer
    CalledProcessError attributes, for compatibility with Python 3.3.
    """
    try:
        process = subprocess.Popen(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(
            "Failed to execute command {!r}: {}".format(
                argv[0],
                exc,
            )
        )

    stdout_data, stderr_data = process.communicate()

    if process.returncode != 0:
        stderr_text = ""

        if stderr_data:
            stderr_text = stderr_data.decode(
                "utf-8",
                "replace",
            ).strip()

        message = "Command failed with status {}: {}".format(
            process.returncode,
            shlex_join(argv),
        )

        if stderr_text:
            message += "\n{}".format(stderr_text)

        raise RuntimeError(message)

    return stdout_data


def strip_command_line_ending(output):
    """
    Remove the command's terminating line ending while rejecting embedded
    newlines.

    The returned text remains otherwise unchanged so CFLAGS and LDFLAGS
    preserve the raw command output.
    """
    output = output.rstrip("\r\n")

    if "\n" in output or "\r" in output:
        raise RuntimeError(
            "Compiler option output contains embedded newlines."
        )

    return output


def get_command_output(argv):
    output = run_command(argv)
    output_text = decode_utf8(
        output,
        "the output of {!r}".format(
            shlex_join(argv)
        ),
    )

    return strip_command_line_ending(output_text)


def normalize_options(options):
    """
    Convert compiler-driver linker options into a form suitable for nvcc.

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


def normalize_linker_output(linker_output, command):
    try:
        linker_options = shlex.split(
            linker_output,
            comments=False,
            posix=True,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Failed to parse the output of {!r}: {}".format(
                command,
                exc,
            )
        )

    return shlex_join(
        normalize_options(linker_options)
    )


def get_nvhpc_options():
    compile_command = [
        "mpicxx",
        "-showme:compile",
    ]
    link_command = [
        "mpicxx",
        "-showme:link",
    ]

    cflags = get_command_output(compile_command)
    ldflags = get_command_output(link_command)
    nvcc_ldflags = normalize_linker_output(
        ldflags,
        shlex_join(link_command),
    )

    return {
        "cflags": cflags,
        "ldflags": ldflags,
        "nvcc_ldflags": nvcc_ldflags,
    }


def get_cray_options():
    compile_command = [
        "CC",
        "--cray-print-opts=cflags",
    ]
    link_command = [
        "CC",
        "--cray-print-opts=libs",
    ]

    cflags = get_command_output(compile_command)
    ldflags = get_command_output(link_command)
    nvcc_ldflags = normalize_linker_output(
        ldflags,
        shlex_join(link_command),
    )

    return {
        "cflags": cflags,
        "ldflags": ldflags,
        "nvcc_ldflags": nvcc_ldflags,
    }


def generate_options(environment):
    if environment == "nvhpc":
        return get_nvhpc_options()

    if environment == "cray":
        return get_cray_options()

    raise ValueError(
        "Unsupported environment: {!r}".format(
            environment
        )
    )


def validate_options(options):
    if not isinstance(options, dict):
        raise RuntimeError(
            "Cached options must be a JSON object."
        )

    required_keys = (
        "cflags",
        "ldflags",
        "nvcc_ldflags",
    )

    for key in required_keys:
        if key not in options:
            raise RuntimeError(
                "Cached options are missing {!r}.".format(
                    key
                )
            )

        if not isinstance(options[key], str):
            raise RuntimeError(
                "Cached option {!r} must be a string.".format(
                    key
                )
            )

        if "\n" in options[key] or "\r" in options[key]:
            raise RuntimeError(
                "Cached option {!r} contains embedded newlines.".format(
                    key
                )
            )


def load_options(filename):
    try:
        with open(filename, "rb") as fp:
            encoded_options = fp.read()

        options_text = decode_utf8(
            encoded_options,
            "cached options",
        )
        options = json.loads(options_text)
    except ValueError as exc:
        raise RuntimeError(
            "Failed to parse cached options as JSON: {}".format(
                exc
            )
        )

    validate_options(options)
    return options


def save_options(filename, options):
    validate_options(options)

    options_text = json.dumps(
        options,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    options_text += "\n"

    with open(filename, "wb") as fp:
        fp.write(options_text.encode("utf-8"))


def escape_makefile_value(value):
    """
    Escape text for use on the right-hand side of a Makefile variable
    assignment.

    Make interprets '$' as the start of a variable reference, so a literal
    dollar sign must be written as '$$'.

    Make also interprets an unescaped '#' as the start of a comment, even
    when it appears inside shell quotes, so it must be escaped as '\\#'.
    """
    if "\n" in value or "\r" in value:
        raise ValueError(
            "Makefile output cannot contain embedded newlines."
        )

    return value.replace("$", "$$").replace("#", "\\#")


def format_output(options, mode):
    validate_options(options)

    if mode == "raw":
        output_text = "{}\n{}\n{}\n".format(
            options["cflags"],
            options["ldflags"],
            options["nvcc_ldflags"],
        )
    else:
        output_text = (
            "CFLAGS = {}\n"
            "LDFLAGS = {}\n"
            "NVCC_LDFLAGS = {}\n"
        ).format(
            escape_makefile_value(options["cflags"]),
            escape_makefile_value(options["ldflags"]),
            escape_makefile_value(options["nvcc_ldflags"]),
        )

    return output_text.encode("utf-8")


def main():
    args = parse_args()

    repo_dir = os.path.abspath(
        os.path.dirname(__file__)
    )
    machine_id = get_machine_id()

    options_filename = os.path.join(
        repo_dir,
        "compiler_options_{}_{}.json".format(
            machine_id,
            args.environment,
        ),
    )

    try:
        if (
            os.path.exists(options_filename)
            and not args.refresh
        ):
            options = load_options(options_filename)
        else:
            options = generate_options(
                args.environment
            )
            save_options(
                options_filename,
                options,
            )

        output = format_output(
            options,
            args.mode,
        )
        sys.stdout.buffer.write(output)
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
