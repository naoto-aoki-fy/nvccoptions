#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
import io
import json
import os
import sys


TARGET_EXECUTABLE = "nvc++"

# Environment variable names that must never be written to config.mk.
EXCLUDED_ENV_VARS = frozenset([
    "PWD",
    "SHLVL",
    "_",
    "HFI_NO_BACKTRACE",
    "IPATH_NO_BACKTRACE",
])

# Environment variable name prefixes that must never be written.
EXCLUDED_ENV_VAR_PREFIXES = (
    "BASH_FUNC_",
)

# Source-file suffixes used to identify compile commands.
COMPILE_SOURCE_SUFFIXES = (
    ".c",
    ".cpp",
    ".cu",
)

# Object-file suffixes used to identify link commands.
LINK_OBJECT_SUFFIXES = (
    ".o",
)

# Compiler arguments that must not be written to CFLAGS or LDFLAGS.
EXCLUDED_COMPILER_ARGUMENTS = frozenset([
    "-cuda",
    "-acc",
])

# Compiler options whose values must also be removed.
#
# Supported forms:
#
#   -tp=value
#   -tp value
#   -gpu=value
#   -gpu value
EXCLUDED_COMPILER_VALUE_OPTIONS = frozenset([
    "-tp",
    "-gpu",
])


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Extract nvc++ compile and link invocations from strace JSON "
            "files and generate a Makefile config.mk file."
        )
    )

    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="STRACE_JSON",
        help=(
            "One or more JSON or JSONL input files. "
            "Use '-' to read one input from standard input."
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help="Output config.mk file; write to standard output if omitted",
    )

    return parser.parse_args()


def open_input(filename):
    if filename == "-":
        return sys.stdin, False

    stream = io.open(
        filename,
        mode="r",
        encoding="utf-8",
    )

    return stream, True


def open_output(filename):
    if filename is None or filename == "-":
        return sys.stdout, False

    stream = io.open(
        filename,
        mode="w",
        encoding="utf-8",
        newline="\n",
    )

    return stream, True


def iter_json_values(stream):
    """
    Read JSON values from the input stream.

    Supported input formats:

      1. A single JSON object
      2. A JSON array
      3. Multiple concatenated JSON values
      4. JSON Lines
    """
    text = stream.read()

    if not text.strip():
        return

    decoder = json.JSONDecoder()
    position = 0
    length = len(text)

    while position < length:
        while position < length and text[position].isspace():
            position += 1

        if position >= length:
            break

        try:
            value, end = decoder.raw_decode(text, position)

        except ValueError as exc:
            error_position = getattr(exc, "pos", position)
            error_message = getattr(exc, "msg", str(exc))

            line = text.count("\n", 0, error_position) + 1
            last_newline = text.rfind("\n", 0, error_position)
            column = error_position - last_newline

            raise ValueError(
                "Invalid JSON: {0} at line {1}, column {2}".format(
                    error_message,
                    line,
                    column,
                )
            )

        yield value
        position = end


def iter_records(value):
    """
    Expand a top-level JSON array and yield JSON objects.
    """
    if isinstance(value, dict):
        yield value
        return

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def executable_basename(value):
    if not isinstance(value, str):
        return ""

    # Also accept Windows-style path separators.
    normalized = value.replace("\\", "/")

    return normalized.rsplit("/", 1)[-1]


def is_target_record(record):
    """
    Implement the equivalent of:

      select(
        (.path // "" | split("/") | last) == "nvc++"
        or
        (.argv[0] // "" | split("/") | last) == "nvc++"
      )
    """
    if executable_basename(record.get("path")) == TARGET_EXECUTABLE:
        return True

    argv = record.get("argv")

    if isinstance(argv, list) and argv:
        return executable_basename(argv[0]) == TARGET_EXECUTABLE

    return False


def value_to_string(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, bool):
        if value:
            return "true"

        return "false"

    return str(value)


def normalize_argv(value):
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        result.append(value_to_string(item))

    return result


def normalize_env(value):
    """
    Convert env to a dictionary.

    Supported formats:

      {
        "CC": "nvc++",
        "PATH": "/usr/bin"
      }

    and:

      [
        "CC=nvc++",
        "PATH=/usr/bin"
      ]
    """
    result = {}

    if isinstance(value, dict):
        for raw_name, raw_value in value.items():
            name = value_to_string(raw_name)
            env_value = value_to_string(raw_value)

            result[name] = env_value

        return result

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                continue

            name, separator, env_value = item.partition("=")

            if not separator:
                continue

            result[name] = env_value

    return result


def is_excluded_environment_variable(name):
    """
    Return True when an environment variable must not be written.
    """
    if name in EXCLUDED_ENV_VARS:
        return True

    for prefix in EXCLUDED_ENV_VAR_PREFIXES:
        if name.startswith(prefix):
            return True

    return False


def is_valid_make_variable_name(name):
    """
    Check whether a name can safely be used as a Make variable name.

    Allowed characters:

      First character: A-Z, a-z, _
      Remaining characters: A-Z, a-z, 0-9, _
    """
    if not name:
        return False

    first = name[0]

    if not (
        ("a" <= first <= "z")
        or ("A" <= first <= "Z")
        or first == "_"
    ):
        return False

    for character in name:
        if not (
            ("a" <= character <= "z")
            or ("A" <= character <= "Z")
            or ("0" <= character <= "9")
            or character == "_"
        ):
            return False

    return True


def escape_make_value(value):
    """
    Escape a value for the right-hand side of a Make ':=' assignment.

    - Backslashes are doubled.
    - Dollar signs are doubled to prevent Make expansion.
    - Hash characters are escaped to prevent comments.
    - Newlines are converted to Make continuation lines.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("$", "$$")
    value = value.replace("#", "\\#")

    normalized = value.replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n")

    return normalized.replace("\n", "\\\n")


def shell_quote(value):
    """
    Quote one shell argument.

    This provides the required functionality without depending on
    shlex.quote(), which is not available in Python 3.3.
    """
    if not value:
        return "''"

    safe_characters = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "_@%+=:,./-"
    )

    for character in value:
        if character not in safe_characters:
            return "'" + value.replace("'", "'\"'\"'") + "'"

    return value


def make_quote(value):
    """
    Format one command-line argument for a Make variable.
    """
    quoted = shell_quote(value)

    quoted = quoted.replace("$", "$$")
    quoted = quoted.replace("#", "\\#")

    return quoted


def format_arguments(arguments):
    result = []

    for argument in arguments:
        result.append(make_quote(argument))

    return " ".join(result)


def filter_excluded_compiler_arguments(arguments):
    """
    Remove nvc++-specific options that must not be written to CFLAGS,
    LDFLAGS, or NVCC_LDFLAGS.

    Removed forms:

      - -cuda
      - -acc
      - -tp=value
      - -tp value
      - -gpu=value
      - -gpu value

    When -tp or -gpu appears without an inline value, the immediately
    following argument is treated as its value and removed.
    """
    result = []
    skip_next = False

    for argument in arguments:
        if skip_next:
            skip_next = False
            continue

        if argument in EXCLUDED_COMPILER_ARGUMENTS:
            continue

        if argument in EXCLUDED_COMPILER_VALUE_OPTIONS:
            skip_next = True
            continue

        excluded = False

        for option in EXCLUDED_COMPILER_VALUE_OPTIONS:
            if argument.startswith(option + "="):
                excluded = True
                break

        if excluded:
            continue

        result.append(argument)

    return result


def normalize_nvcc_linker_arguments(arguments):
    """
    Convert compiler-driver linker arguments into a form suitable for nvcc.

    Transformations:

      - Remove -pthread.
      - Convert:
            -Wl,option1,option2
        into:
            -Xlinker option1 -Xlinker option2

    The input and return values are lists of command-line arguments.
    """
    normalized = []

    for argument in arguments:
        if argument == "-pthread":
            continue

        if argument.startswith("-Wl,"):
            linker_options = argument.split(",")[1:]

            for linker_option in linker_options:
                if linker_option:
                    normalized.extend([
                        "-Xlinker",
                        linker_option,
                    ])
        else:
            normalized.append(argument)

    return normalized


def is_same_as_current_environment(name, value):
    """
    Return True when the current Python process has the same environment
    variable with the same value.

    A missing variable and an existing variable with an empty value are
    treated differently.
    """
    if name not in os.environ:
        return False

    return os.environ[name] == value


def merge_environment(destination, source):
    """
    Merge environment variables from source into destination.

    Variables are omitted when:

      - Their name is listed in EXCLUDED_ENV_VARS.
      - Their name starts with an excluded prefix.
      - Their name is not a valid Make variable name.
      - The current Python process already has the same value.

    When a variable appears multiple times, the last value is used.
    """
    for name, env_value in source.items():
        if is_excluded_environment_variable(name):
            continue

        if not is_valid_make_variable_name(name):
            print(
                (
                    "Warning: ignoring invalid Make variable name: "
                    "{0!r}"
                ).format(name),
                file=sys.stderr,
            )
            continue

        if is_same_as_current_environment(name, env_value):
            continue

        destination[name] = env_value


def argument_has_suffix(argument, suffixes):
    """
    Return True when an argument ends with one of the given suffixes.

    Matching is case-sensitive.
    """
    for suffix in suffixes:
        if argument.endswith(suffix):
            return True

    return False


def classify_invocation(argv):
    """
    Classify an nvc++ invocation.

    It is classified as a compile command when argv contains:

      - -c
      - *.c
      - *.cpp
      - *.cu

    It is classified as a link command when argv contains:

      - *.o

    Compile classification takes precedence when both compile and link
    indicators are present.
    """
    has_compile_indicator = False
    has_link_indicator = False

    for argument in argv:
        if argument == "-c":
            has_compile_indicator = True

        if argument_has_suffix(argument, COMPILE_SOURCE_SUFFIXES):
            has_compile_indicator = True

        if argument_has_suffix(argument, LINK_OBJECT_SUFFIXES):
            has_link_indicator = True

    if has_compile_indicator:
        return "compile"

    if has_link_indicator:
        return "link"

    return None


def filter_compile_arguments(arguments):
    """
    Remove compile input items and excluded nvc++ options from the
    original compiler argv.

    Removed arguments:

      - -c
      - *.c
      - *.cpp
      - *.cu
      - -cuda
      - -acc
      - -tp=*
      - -tp *
      - -gpu=*
      - -gpu *
    """
    result = []

    for argument in arguments:
        if argument == "-c":
            continue

        if argument_has_suffix(argument, COMPILE_SOURCE_SUFFIXES):
            continue

        result.append(argument)

    return filter_excluded_compiler_arguments(result)


def filter_link_arguments(arguments):
    """
    Remove object-file inputs and excluded nvc++ options from the
    original linker argv.

    Removed arguments:

      - *.o
      - -cuda
      - -acc
      - -tp=*
      - -tp *
      - -gpu=*
      - -gpu *
    """
    result = []

    for argument in arguments:
        if argument_has_suffix(argument, LINK_OBJECT_SUFFIXES):
            continue

        result.append(argument)

    return filter_excluded_compiler_arguments(result)


def collect_stream(
    stream,
    compile_invocations,
    link_invocations,
    environment
):
    """
    Extract nvc++ records from one input stream.

    Matching invocations are classified automatically as compile or link
    commands based on their argv contents.

    Return:

      compile_count:
          Number of compile invocations found.

      link_count:
          Number of link invocations found.

      unclassified_count:
          Number of nvc++ invocations that could not be classified.
    """
    compile_count = 0
    link_count = 0
    unclassified_count = 0

    for value in iter_json_values(stream):
        for record in iter_records(value):
            if not is_target_record(record):
                continue

            argv = normalize_argv(record.get("argv"))

            if not argv:
                unclassified_count += 1
            else:
                invocation_type = classify_invocation(argv)

                # Remove argv[0], which is the nvc++ executable.
                arguments = argv[1:]

                if invocation_type == "compile":
                    compile_invocations.append(
                        filter_compile_arguments(arguments)
                    )
                    compile_count += 1

                elif invocation_type == "link":
                    link_invocations.append(
                        filter_link_arguments(arguments)
                    )
                    link_count += 1

                else:
                    unclassified_count += 1

            env = normalize_env(record.get("env"))
            merge_environment(environment, env)

    return compile_count, link_count, unclassified_count


def flatten_invocations(invocations):
    """
    Concatenate arguments from all matching invocations in input order.
    """
    result = []

    for invocation in invocations:
        result.extend(invocation)

    return result


def write_make_variable(stream, name, arguments):
    formatted = format_arguments(arguments)

    if formatted:
        print(
            "{0} := {1}".format(name, formatted),
            file=stream,
        )
    else:
        print(
            "{0} :=".format(name),
            file=stream,
        )


def write_config(
    stream,
    link_invocations,
    compile_invocations,
    environment,
    link_count,
    compile_count,
    unclassified_count
):
    print("# Generated by nvcxx_config.py.", file=stream)
    print("# Do not edit this file manually.", file=stream)

    print(
        "# Link records matched: {0}".format(link_count),
        file=stream,
    )

    print(
        "# Compile records matched: {0}".format(compile_count),
        file=stream,
    )

    print(
        "# Unclassified nvc++ records: {0}".format(
            unclassified_count
        ),
        file=stream,
    )

    print("", file=stream)

    link_arguments = flatten_invocations(link_invocations)
    compile_arguments = flatten_invocations(compile_invocations)

    nvcc_link_arguments = normalize_nvcc_linker_arguments(
        link_arguments
    )

    write_make_variable(
        stream,
        "LDFLAGS",
        link_arguments,
    )

    write_make_variable(
        stream,
        "NVCC_LDFLAGS",
        nvcc_link_arguments,
    )

    write_make_variable(
        stream,
        "CFLAGS",
        compile_arguments,
    )

    if environment:
        print("", file=stream)

        for name in sorted(environment):
            value = escape_make_value(environment[name])

            print(
                "export {0} := {1}".format(name, value),
                file=stream,
            )


def main():
    args = parse_args()

    output_stream = None
    close_output = False

    compile_invocations = []
    link_invocations = []
    environment = {}

    compile_count = 0
    link_count = 0
    unclassified_count = 0

    standard_input_count = 0

    for filename in args.inputs:
        if filename == "-":
            standard_input_count += 1

    if standard_input_count > 1:
        print(
            "Error: standard input may only be specified once",
            file=sys.stderr,
        )
        return 1

    try:
        for filename in args.inputs:
            input_stream = None
            close_input = False

            try:
                input_stream, close_input = open_input(filename)

                (
                    file_compile_count,
                    file_link_count,
                    file_unclassified_count
                ) = collect_stream(
                    input_stream,
                    compile_invocations,
                    link_invocations,
                    environment,
                )

                compile_count += file_compile_count
                link_count += file_link_count
                unclassified_count += file_unclassified_count

            finally:
                if close_input and input_stream is not None:
                    input_stream.close()

        output_stream, close_output = open_output(
            args.output
        )

        write_config(
            output_stream,
            link_invocations,
            compile_invocations,
            environment,
            link_count,
            compile_count,
            unclassified_count,
        )

        if link_count == 0:
            print(
                (
                    "Warning: no link invocation of {0} was found"
                ).format(TARGET_EXECUTABLE),
                file=sys.stderr,
            )

        if compile_count == 0:
            print(
                (
                    "Warning: no compile invocation of {0} was found"
                ).format(TARGET_EXECUTABLE),
                file=sys.stderr,
            )

        if unclassified_count != 0:
            print(
                (
                    "Warning: {0} {1} invocation(s) could not be "
                    "classified"
                ).format(
                    unclassified_count,
                    TARGET_EXECUTABLE,
                ),
                file=sys.stderr,
            )

        return 0

    except BrokenPipeError:
        return 0

    except (IOError, OSError, ValueError) as exc:
        print(
            "Error: {0}".format(exc),
            file=sys.stderr,
        )
        return 1

    finally:
        if close_output and output_stream is not None:
            output_stream.close()


if __name__ == "__main__":
    sys.exit(main())
