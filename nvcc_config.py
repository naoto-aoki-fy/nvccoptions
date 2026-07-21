#!/usr/bin/env python3

from __future__ import print_function

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile


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
        choices=("wrapper", "strace"),
        default="wrapper",
        help=(
            "Extraction mode. 'wrapper' queries compiler-wrapper print "
            "options (default). 'strace' runs mpicxx under "
            "unshare -Ur and strace to capture the nvc++ argv and "
            "environment described by strace-spec.md."
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

    The returned text remains otherwise unchanged so CFLAGS_VENDOR and LDFLAGS_VENDOR
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


def strip_output_option(options_text, output_kind):
    """
    Remove compiler-generated output-file options from vendor flags.

    Compile flags should not carry the probe object's ``-o *.o`` pair, while
    linker flags should not carry any probe output ``-o *`` pair.  The caller
    passes shell-style option text from a compiler wrapper, so parse it with
    shlex and return normalized shell-quoted text.
    """
    args = shlex.split(options_text)
    filtered = []
    index = 0

    while index < len(args):
        arg = args[index]

        if arg == "-o" and index + 1 < len(args):
            output_path = args[index + 1]
            if output_kind == "link" or output_path.endswith(".o"):
                index += 2
                continue

        if arg.startswith("-o") and len(arg) > 2:
            output_path = arg[2:]
            if output_kind == "link" or output_path.endswith(".o"):
                index += 1
                continue

        filtered.append(arg)
        index += 1

    return shlex_join(filtered)



STRACE_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
VALID_ENV_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
EXCLUDED_ENV_NAMES = set([
    "HOME",
    "HOSTNAME",
    "PWD",
    "SHLVL",
    "_",
    "HFI_NO_BACKTRACE",
    "IPATH_NO_BACKTRACE",
])
EXCLUDED_ENV_PREFIXES = (
    "BASH_FUNC_",
    "_LMFILES_",
    "PJM_",
)


def decode_strace_string(token):
    if not STRACE_STRING_RE.match(token):
        raise RuntimeError(
            "Invalid strace string token: {!r}".format(token)
        )

    return bytes(
        token[1:-1],
        "utf-8",
    ).decode(
        "unicode_escape",
    )


def find_matching_bracket(text, start):
    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index

    raise RuntimeError("Unterminated array in strace output.")


def parse_strace_array(text, start):
    end = find_matching_bracket(text, start)
    array_text = text[start + 1:end]
    values = []

    for match in STRACE_STRING_RE.finditer(array_text):
        values.append(
            decode_strace_string(match.group(0))
        )

    return values, end + 1


def strip_strace_prefix(line):
    if line.startswith("[pid "):
        close = line.find("]")
        if close != -1:
            return line[close + 1:].lstrip()

    return line


def normalize_strace_records(stderr_text):
    records = []
    unfinished = {}

    for raw_line in stderr_text.splitlines():
        line = strip_strace_prefix(raw_line)
        if "execve" not in line:
            continue

        if "<unfinished ...>" in line:
            key = line.split("(", 1)[0].strip()
            unfinished[key] = line.replace(" <unfinished ...>", "")
            continue

        if line.startswith("<...") and " resumed>" in line:
            name = line[4:line.find(" resumed>")].strip()
            prefix = unfinished.pop(name, "")
            suffix = line.split("resumed>", 1)[1].lstrip()
            records.append(prefix + suffix)
            continue

        records.append(line)

    return records


def parse_exec_record(record):
    syscall = record.split("(", 1)[0].strip()
    if syscall not in ("execve", "execveat"):
        return None

    if " = 0" not in record and ") = 0" not in record:
        return None

    try:
        first_quote = record.index('"')
    except ValueError:
        raise RuntimeError(
            "Could not parse executable path from strace record: {}".format(
                record
            )
        )

    path_match = STRACE_STRING_RE.match(record, first_quote)
    if not path_match:
        raise RuntimeError(
            "Could not parse executable path from strace record: {}".format(
                record
            )
        )

    path = decode_strace_string(path_match.group(0))
    args_start = record.find("[", path_match.end())
    if args_start == -1:
        raise RuntimeError(
            "Could not parse argument array from strace record: {}".format(
                record
            )
        )

    argv, next_index = parse_strace_array(record, args_start)
    env_start = record.find("[", next_index)
    if env_start == -1:
        raise RuntimeError(
            "Could not parse environment array from strace record: {}".format(
                record
            )
        )

    env, unused_index = parse_strace_array(record, env_start)
    return {
        "path": path,
        "argv": argv,
        "env": env,
    }


def parse_strace_exec_records(stderr_text):
    parsed = []

    for record in normalize_strace_records(stderr_text):
        parsed_record = parse_exec_record(record)
        if parsed_record is not None:
            parsed.append(parsed_record)

    if not parsed:
        raise RuntimeError("No execve or execveat records were parsed from strace output.")

    return parsed


def is_nvcxx_record(record):
    names = []
    if record["path"]:
        names.append(os.path.basename(record["path"]))
    if record["argv"]:
        names.append(os.path.basename(record["argv"][0]))

    return "nvc++" in names


def classify_nvcxx_args(args):
    is_compile = False
    is_link = False

    for arg in args:
        if arg == "-c" or arg.endswith((".c", ".cpp", ".cu")):
            is_compile = True
        if arg.endswith(".o"):
            is_link = True

    if is_compile:
        return "compile"
    if is_link:
        return "link"
    return None


def filter_nvcxx_args(args, operation):
    filtered = []
    skip_next = False
    source_suffixes = (".c", ".cpp", ".cu")

    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue

        if arg in ("-cuda", "-acc"):
            continue
        if arg in ("-tp", "-gpu"):
            skip_next = True
            continue
        if arg.startswith("-tp=") or arg.startswith("-gpu="):
            continue
        if arg == "-o" and index + 1 < len(args):
            output_path = args[index + 1]
            if operation == "link" or output_path.endswith(".o"):
                skip_next = True
                continue
        if arg.startswith("-o") and len(arg) > 2:
            output_path = arg[2:]
            if operation == "link" or output_path.endswith(".o"):
                continue
        if operation == "compile" and (arg == "-c" or arg.endswith(source_suffixes)):
            continue
        if operation == "link" and arg.endswith(".o"):
            continue

        filtered.append(arg)

    return filtered


def should_include_env(entry, baseline_env):
    if "=" not in entry:
        return False

    name, value = entry.split("=", 1)
    if not VALID_ENV_NAME_RE.match(name):
        return False
    if name in EXCLUDED_ENV_NAMES:
        return False

    for prefix in EXCLUDED_ENV_PREFIXES:
        if name.startswith(prefix):
            return False

    return baseline_env.get(name) != value


def extract_env(entries, baseline_env):
    result = {}

    for entry in entries:
        if should_include_env(entry, baseline_env):
            name, value = entry.split("=", 1)
            result[name] = value

    return result


def run_strace_command(argv):
    command = [
        "unshare",
        "-Ur",
        "strace",
        "-f",
        "-v",
        "-s",
        "1073741823",
        "-e",
        "trace=execve,execveat",
    ] + argv

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(
            "Failed to execute strace inspection command {!r}: {}".format(
                command[0],
                exc,
            )
        )

    stdout_data, stderr_data = process.communicate()
    stderr_text = stderr_data.decode("utf-8", "replace")

    if process.returncode != 0:
        message = "Inspection command failed with status {}: {}".format(
            process.returncode,
            shlex_join(command),
        )
        if stderr_text.strip():
            message += "\n{}".format(stderr_text.strip())
        raise RuntimeError(message)

    return stderr_text


def inspect_nvhpc_with_strace():
    compile_args = []
    link_args = []
    env_options = {}
    seen_compile = False
    seen_link = False

    with tempfile.TemporaryDirectory(prefix="nvccoptions-") as workdir:
        source_path = os.path.join(workdir, "probe.cu")
        object_path = os.path.join(workdir, "probe.o")
        binary_path = os.path.join(workdir, "probe")

        with open(source_path, "w") as source_file:
            source_file.write("int main() { return 0; }\n")

        commands = [
            ["mpicxx", "-c", source_path, "-o", object_path],
            ["mpicxx", object_path, "-o", binary_path],
        ]

        for command in commands:
            stderr_text = run_strace_command(command)
            records = parse_strace_exec_records(stderr_text)

            for record in records:
                if not is_nvcxx_record(record):
                    continue

                operation = classify_nvcxx_args(record["argv"][1:])
                if operation is None:
                    continue

                filtered_args = filter_nvcxx_args(record["argv"][1:], operation)
                if operation == "compile":
                    compile_args.extend(filtered_args)
                    seen_compile = True
                elif operation == "link":
                    link_args.extend(filtered_args)
                    seen_link = True

                env_options.update(
                    extract_env(record["env"], os.environ)
                )

    if not seen_compile:
        print(
            "warning: no nvc++ compilation command was detected.",
            file=sys.stderr,
        )
    if not seen_link:
        print(
            "warning: no nvc++ linking command was detected.",
            file=sys.stderr,
        )

    return {
        "cflags": shlex_join(compile_args),
        "ldflags": shlex_join(link_args),
        "env": env_options,
    }

def get_nvhpc_options():
    compile_command = [
        "mpicxx",
        "-showme:compile",
    ]
    link_command = [
        "mpicxx",
        "-showme:link",
    ]

    cflags = strip_output_option(
        get_command_output(compile_command),
        "compile",
    )
    ldflags = strip_output_option(
        get_command_output(link_command),
        "link",
    )
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

    cflags = strip_output_option(
        get_command_output(compile_command),
        "compile",
    )
    ldflags = strip_output_option(
        get_command_output(link_command),
        "link",
    )
    return {
        "cflags": cflags,
        "ldflags": ldflags,
    }


def generate_options(environment, mode):
    if mode == "strace":
        if environment != "nvhpc":
            raise RuntimeError("The strace mode is currently supported only for the NVIDIA HPC SDK environment.")
        return inspect_nvhpc_with_strace()

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

    env = options.get("env", {})
    if not isinstance(env, dict):
        raise RuntimeError("Generated environment options must be a dictionary.")

    for key, value in env.items():
        if not isinstance(key, str) or not VALID_ENV_NAME_RE.match(key):
            raise RuntimeError("Generated environment variable has an invalid name: {!r}".format(key))
        if not isinstance(value, str):
            raise RuntimeError("Generated environment variable {!r} must be a string.".format(key))
        if "\n" in value or "\r" in value:
            raise RuntimeError("Generated environment variable {!r} contains embedded newlines.".format(key))


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


def format_env_exports(env_options):
    lines = []

    for name in sorted(env_options):
        lines.append(
            "export {} = {}".format(
                name,
                escape_makefile_value(env_options[name]),
            )
        )

    return "\n".join(lines)


def format_output(options):
    validate_options(options)

    output_lines = [
        "CFLAGS_VENDOR = {}".format(
            escape_makefile_value(options["cflags"]),
        ),
        "LDFLAGS_VENDOR = {}".format(
            escape_makefile_value(options["ldflags"]),
        ),
    ]

    env_exports = format_env_exports(options.get("env", {}))
    if env_exports:
        output_lines.append(env_exports)

    output_text = "\n".join(output_lines) + "\n"

    return output_text.encode("utf-8")


def main():
    args = parse_args()

    try:
        options = generate_options(
            args.environment,
            args.mode,
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
