#!/usr/bin/env python3

import argparse
import ast
import json
import re
import sys


PID_PREFIX_RE = re.compile(
    r"""
    ^
    (?:
        \[pid\ \s*(?P<bracket_pid>\d+)\]\s+
        |
        (?P<plain_pid>\d+)\s+
    )?
    (?P<body>.*)
    $
    """,
    re.VERBOSE,
)

SYSCALL_RE = re.compile(
    r"""
    ^
    (?P<name>execve|execveat)
    \(
        (?P<arguments>.*)
    \)
    \s+=\s+
    (?P<result>.*)
    $
    """,
    re.VERBOSE,
)

UNFINISHED_RE = re.compile(
    r"""
    ^
    (?P<name>execve|execveat)
    \(
        (?P<arguments>.*)
    \s+<unfinished\ \.\.\.>$
    """,
    re.VERBOSE,
)

RESUMED_RE = re.compile(
    r"""
    ^
    <\.\.\.\s+
    (?P<name>execve|execveat)
    \s+resumed>
    (?P<arguments>.*)
    \)
    \s+=\s+
    (?P<result>.*)
    $
    """,
    re.VERBOSE,
)

RETURN_RE = re.compile(
    r"""
    ^
    (?P<return_value>-?\d+|\?)
    (?:
        \s+
        (?P<errno>[A-Z][A-Z0-9_]+)
        \s+
        \((?P<error_message>.*)\)
    )?
    (?P<extra>.*)
    $
    """,
    re.VERBOSE,
)


def split_top_level(text):
    """
    カンマ区切りの引数を分割する。

    文字列、配列、波括弧、丸括弧内のカンマは無視する。
    """
    parts = []
    start = 0
    square_depth = 0
    curly_depth = 0
    paren_depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char == "{":
            curly_depth += 1
        elif char == "}":
            curly_depth = max(0, curly_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif (
            char == ","
            and square_depth == 0
            and curly_depth == 0
            and paren_depth == 0
        ):
            parts.append(text[start:index].strip())
            start = index + 1

    parts.append(text[start:].strip())
    return parts


def decode_c_string(value):
    value = value.strip()

    if value == "NULL":
        return None

    if not value.startswith('"'):
        return value

    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return decode_c_string_fallback(value)


def decode_c_string_fallback(value):
    """
    ast.literal_evalで処理できないstrace文字列向けの簡易デコーダー。
    """
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    elif value.startswith('"'):
        value = value[1:]

    result = bytearray()
    index = 0

    simple_escapes = {
        "a": 0x07,
        "b": 0x08,
        "t": 0x09,
        "n": 0x0A,
        "v": 0x0B,
        "f": 0x0C,
        "r": 0x0D,
        '"': 0x22,
        "'": 0x27,
        "\\": 0x5C,
    }

    while index < len(value):
        char = value[index]

        if char != "\\":
            result.extend(
                char.encode("utf-8", errors="surrogateescape")
            )
            index += 1
            continue

        index += 1

        if index >= len(value):
            result.append(ord("\\"))
            break

        escape = value[index]

        if escape in simple_escapes:
            result.append(simple_escapes[escape])
            index += 1
            continue

        if escape == "x":
            match = re.match(
                r"[0-9a-fA-F]{1,2}",
                value[index + 1:]
            )

            if match:
                result.append(int(match.group(0), 16))
                index += 1 + len(match.group(0))
                continue

        if escape in "01234567":
            match = re.match(r"[0-7]{1,3}", value[index:])

            if match:
                result.append(int(match.group(0), 8))
                index += len(match.group(0))
                continue

        result.extend(
            escape.encode("utf-8", errors="surrogateescape")
        )
        index += 1

    return result.decode("utf-8", errors="surrogateescape")


def parse_string_array(value):
    value = value.strip()

    if value == "NULL":
        return None

    if not value.startswith("["):
        return None

    if value.endswith("..."):
        value = value[:-3].rstrip()

    if not value.endswith("]"):
        return None

    inner = value[1:-1].strip()

    if not inner:
        return []

    result = []

    for item in split_top_level(inner):
        item = item.strip()

        if item in ("...", "NULL"):
            continue

        decoded = decode_c_string(item)

        if decoded is not None:
            result.append(decoded)

    return result


def env_list_to_dict(entries):
    if entries is None:
        return None

    result = {}

    for entry in entries:
        if "=" not in entry:
            # KEY=VALUE形式ではない項目がある場合は、
            # 情報を失わないようリストのまま返す。
            return entries

        key, value = entry.split("=", 1)
        result[key] = value

    return result


def parse_integer_or_symbol(value):
    value = value.strip()

    if value == "NULL":
        return None

    try:
        return int(value, 0)
    except ValueError:
        return value


def parse_flags(value):
    value = value.strip()

    if value == "0":
        return []

    try:
        return int(value, 0)
    except ValueError:
        pass

    if "|" in value:
        return [
            part.strip()
            for part in value.split("|")
        ]

    return value


def parse_result(result):
    match = RETURN_RE.match(result.strip())

    if not match:
        return result.strip(), None, None

    raw_return_value = match.group("return_value")

    if raw_return_value == "?":
        return_value = "?"
    else:
        return_value = int(raw_return_value)

    return (
        return_value,
        match.group("errno"),
        match.group("error_message"),
    )


def parse_exec_event(
    pid,
    syscall,
    arguments,
    result,
    raw_line,
    include_env=True
):
    parts = split_top_level(arguments)

    path = None
    argv = None
    env = None
    dirfd = None
    flags = None

    if syscall == "execve":
        if len(parts) >= 1:
            path = decode_c_string(parts[0])

        if len(parts) >= 2:
            argv = parse_string_array(parts[1])

        if include_env and len(parts) >= 3:
            env = env_list_to_dict(
                parse_string_array(parts[2])
            )

    elif syscall == "execveat":
        if len(parts) >= 1:
            dirfd = parse_integer_or_symbol(parts[0])

        if len(parts) >= 2:
            path = decode_c_string(parts[1])

        if len(parts) >= 3:
            argv = parse_string_array(parts[2])

        if include_env and len(parts) >= 4:
            env = env_list_to_dict(
                parse_string_array(parts[3])
            )

        if len(parts) >= 5:
            flags = parse_flags(parts[4])

    return_value, errno, error_message = parse_result(result)

    return {
        "pid": pid,
        "syscall": syscall,
        "path": path,
        "argv": argv,
        "env": env,
        "dirfd": dirfd,
        "flags": flags,
        "return_value": return_value,
        "errno": errno,
        "error_message": error_message,
        "raw_arguments": arguments,
        "raw_result": result,
        "raw_line": raw_line,
    }


def extract_pid_and_body(line):
    match = PID_PREFIX_RE.match(line)

    if not match:
        return None, line

    pid_text = (
        match.group("bracket_pid")
        or match.group("plain_pid")
    )

    if pid_text is None:
        pid = None
    else:
        pid = int(pid_text)

    return pid, match.group("body")


def convert_stream(
    source,
    destination,
    output_array=False,
    include_env=True,
    include_unparsed=False
):
    unfinished = {}
    events = []

    def emit(value):
        if output_array:
            events.append(value)
        else:
            print(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":")
                ),
                file=destination
            )

    for raw_line in source:
        line = raw_line.rstrip("\n")
        pid, body = extract_pid_and_body(line)

        match = SYSCALL_RE.match(body)

        if match:
            event = parse_exec_event(
                pid=pid,
                syscall=match.group("name"),
                arguments=match.group("arguments"),
                result=match.group("result"),
                raw_line=line,
                include_env=include_env
            )
            emit(event)
            continue

        match = UNFINISHED_RE.match(body)

        if match:
            key = (pid, match.group("name"))
            unfinished[key] = match.group("arguments")
            continue

        match = RESUMED_RE.match(body)

        if match:
            syscall = match.group("name")
            key = (pid, syscall)

            first_half = unfinished.pop(key, "")
            second_half = match.group("arguments")
            arguments = first_half + second_half

            event = parse_exec_event(
                pid=pid,
                syscall=syscall,
                arguments=arguments,
                result=match.group("result"),
                raw_line=line,
                include_env=include_env
            )
            emit(event)
            continue

        if (
            include_unparsed
            and (
                "execve(" in body
                or "execveat(" in body
            )
        ):
            emit({
                "pid": pid,
                "parse_error": True,
                "raw_line": line,
            })

    if include_unparsed:
        for key, arguments in unfinished.items():
            pid, syscall = key

            emit({
                "pid": pid,
                "syscall": syscall,
                "parse_error": True,
                "reason": "unfinished syscall was not resumed",
                "raw_arguments": arguments,
            })

    if output_array:
        json.dump(
            events,
            destination,
            ensure_ascii=False,
            indent=2
        )
        destination.write("\n")


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "straceのexecve/execveat出力をJSONに変換する"
        )
    )

    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help=(
            "strace出力ファイル。"
            "省略または-の場合は標準入力"
        )
    )

    parser.add_argument(
        "--array",
        action="store_true",
        help=(
            "JSON Linesではなく、"
            "単一のJSON配列として出力する"
        )
    )

    parser.add_argument(
        "--no-env",
        action="store_true",
        help="環境変数をJSONに含めない"
    )

    parser.add_argument(
        "--include-unparsed",
        action="store_true",
        help=(
            "解析できなかったexecve系の行も出力する"
        )
    )

    return parser


def main():
    args = build_argument_parser().parse_args()

    include_env = not args.no_env

    if args.input == "-":
        convert_stream(
            source=sys.stdin,
            destination=sys.stdout,
            output_array=args.array,
            include_env=include_env,
            include_unparsed=args.include_unparsed
        )
        return 0

    try:
        with open(
            args.input,
            "r",
            encoding="utf-8",
            errors="surrogateescape"
        ) as source:
            convert_stream(
                source=source,
                destination=sys.stdout,
                output_array=args.array,
                include_env=include_env,
                include_unparsed=args.include_unparsed
            )
    except OSError as error:
        print(
            "error: {}".format(error),
            file=sys.stderr
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
