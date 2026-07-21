#!/usr/bin/env python3

from __future__ import print_function

import argparse
import os
import shlex
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
    return parser.parse_args()


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
    return {
        "cflags": cflags,
        "ldflags": ldflags,
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
    return {
        "cflags": cflags,
        "ldflags": ldflags,
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
            "Generated options must be a dictionary."
        )

    required_keys = (
        "cflags",
        "ldflags",
    )

    for key in required_keys:
        if key not in options:
            raise RuntimeError(
                "Generated options are missing {!r}.".format(
                    key
                )
            )

        if not isinstance(options[key], str):
            raise RuntimeError(
                "Generated option {!r} must be a string.".format(
                    key
                )
            )

        if "\n" in options[key] or "\r" in options[key]:
            raise RuntimeError(
                "Generated option {!r} contains embedded newlines.".format(
                    key
                )
            )


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


def format_output(options):
    validate_options(options)

    output_text = (
        "CFLAGS = {}\n"
        "LDFLAGS = {}\n"
    ).format(
        escape_makefile_value(options["cflags"]),
        escape_makefile_value(options["ldflags"]),
    )

    return output_text.encode("utf-8")


def main():
    args = parse_args()

    try:
        options = generate_options(
            args.environment
        )
        output = format_output(options)
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
