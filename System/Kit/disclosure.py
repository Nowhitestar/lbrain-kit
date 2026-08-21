"""Shared secret and runtime-state disclosure checks for Kit write paths."""

from __future__ import annotations

import ast
import html
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlsplit


CONCRETE_SECRET_PATTERN = re.compile(
    r"(?i)(?:\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}\b"
    r"|\bAIza[A-Za-z0-9_-]{20,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    r"|\bauthorization\s*:\s*basic\s+[A-Za-z0-9+/=]{12,})"
)
URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")

SHELL_REFERENCE_TEXT = (
    r"\$[A-Za-z_][A-Za-z0-9_]*"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*(?::\?[A-Za-z_][A-Za-z0-9_ ]*)?\}"
    r"|\$\([A-Za-z_][A-Za-z0-9_.-]*\)"
)
FIELD = re.compile(
    r"(?i)(?<![A-Za-z0-9_$])(?:"
    r"(?P<quote>[\"'])(?P<quoted_name>[A-Za-z_$][A-Za-z0-9_$.-]*)(?P=quote)|"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$.-]*\??))"
)
CREDENTIAL_SUFFIXES = {
    "apikey", "accesstoken", "refreshtoken", "sessiontoken", "clientsecret",
    "secret", "password", "privatekey",
}
RUNTIME_SUFFIXES = {"cursor", "pagetoken", "continuationtoken"}
SENSITIVE_MUTATORS = ("set", "update", "configure", "with")

FENCED_CODE = re.compile(
    r"(?ms)^ {0,3}(?P<fence>(?P<marker>`|~)(?P=marker){2,})(?P<info>[^\n]*)\n"
    r"(?P<body>.*?)^ {0,3}(?P=fence)(?P=marker)*[ \t]*(?:\n|$)"
)
SHELL_REFERENCE = re.compile(
    rf"(?:(?P<shell_quote>[\"'])(?:{SHELL_REFERENCE_TEXT})(?P=shell_quote)|"
    rf"(?:{SHELL_REFERENCE_TEXT}))"
)
IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
MEMBER_IDENTIFIER = rf"#?{IDENTIFIER}"
MEMBER_REFERENCE = rf"{IDENTIFIER}(?:\??\.{MEMBER_IDENTIFIER})*"
QUOTED_KEY = r'(?:"[A-Za-z0-9_.-]+"|\'[A-Za-z0-9_.-]+\')'
LOOKUP_REFERENCE = re.compile(
    rf"{MEMBER_REFERENCE}\.(?:get|getenv)\({QUOTED_KEY}\)"
)
INDEX_REFERENCE = re.compile(
    rf"{MEMBER_REFERENCE}(?:\[(?:{IDENTIFIER}|[0-9]+|{QUOTED_KEY})\])+"
    rf"(?:\??\.{IDENTIFIER})*"
)
SHELL_LANGUAGES = {"bash", "console", "sh", "shell", "shell-session", "terminal", "zsh"}
PYTHON_LANGUAGES = {"py", "python"}
CODE_LANGUAGES = SHELL_LANGUAGES | {
    "javascript", "js", "jsx", "py", "python", "ts", "tsx", "typescript"
}


def without_fenced_code(value: str) -> str:
    return FENCED_CODE.sub("", value)


def contains_concrete_secret(*values: str) -> bool:
    return any(CONCRETE_SECRET_PATTERN.search(value) for value in values)


def is_line_comment(text: str, index: int, shell: bool, python: bool) -> bool:
    if shell:
        return text[index:index + 1] == "#" and (
            index == 0 or text[index - 1].isspace() or text[index - 1] in ";|&()"
        )
    if python:
        return text[index:index + 1] == "#"
    return text.startswith("//", index)


def structure_stack(
    text: str,
    end: int,
    shell: bool = False,
    python: bool = False,
) -> list[str]:
    stack: list[str] = []
    quote = ""
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{"}
    index = 0
    while index < end:
        if quote:
            if quote in {'"""', "'''"}:
                if text.startswith(quote, index):
                    index += len(quote)
                    quote = ""
                    continue
            elif escaped:
                escaped = False
            elif text[index] == "\\":
                escaped = True
            elif text[index] == quote:
                quote = ""
            elif quote != "`" and text[index] in "\r\n":
                quote = ""
            index += 1
            continue
        if text.startswith(('"""', "'''"), index):
            quote = text[index:index + 3]
            index += 3
            continue
        character = text[index]
        if is_line_comment(text, index, shell, python):
            newline = text.find("\n", index)
            index = end if newline < 0 else newline + 1
            continue
        if character in "\"'`":
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in pairs and stack and stack[-1] == pairs[character]:
            stack.pop()
        index += 1
    return stack


def assignment_value(
    text: str,
    start: int,
    shell: bool = False,
    python: bool = False,
) -> str | None:
    stack = structure_stack(text, start, shell, python)
    initial_stack = list(stack)
    base_depth = len(stack)
    quote = ""
    escaped = False
    equals: int | None = None
    colon: int | None = None
    operator_depth: int | None = None
    comma_before_operator = False
    pairs = {")": "(", "]": "[", "}": "{"}
    index = start
    end = len(text)
    while index < len(text):
        if quote:
            if quote in {'"""', "'''"}:
                if text.startswith(quote, index):
                    index += len(quote)
                    quote = ""
                    continue
            elif escaped:
                escaped = False
            elif text[index] == "\\":
                escaped = True
            elif text[index] == quote:
                quote = ""
            elif quote != "`" and text[index] in "\r\n":
                quote = ""
            index += 1
            continue
        if text.startswith(('"""', "'''"), index):
            quote = text[index:index + 3]
            index += 3
            continue
        character = text[index]
        if is_line_comment(text, index, shell, python):
            operator = equals if equals is not None else colon
            if operator is not None and not text[operator + 1:index].strip():
                newline = text.find("\n", index)
                if newline >= 0:
                    index = newline + 1
                    continue
            if operator is None:
                newline = text.find("\n", index)
                following = newline + 1
                while newline >= 0 and following < len(text) and text[following].isspace():
                    following += 1
                if (
                    newline >= 0
                    and text[following:following + 1] == "="
                    and text[following + 1:following + 2] not in {"=", ">"}
                ):
                    index = newline + 1
                    continue
            end = index
            break
        if character in "\"'`":
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character == "<" and colon is not None and equals is None:
            stack.append(character)
        elif character == ">" and stack and stack[-1] == "<":
            stack.pop()
        elif character in pairs:
            if stack and stack[-1] == pairs[character]:
                stack.pop()
                if operator_depth is not None and len(stack) < operator_depth:
                    end = index
                    break
            elif operator_depth is not None:
                end = index
                break
            else:
                return None
        elif len(stack) <= (operator_depth if operator_depth is not None else base_depth):
            operator = equals if equals is not None else colon
            if shell and operator is not None and character.isspace():
                if text[operator + 1:index].strip():
                    end = index
                    break
            if character in "\r\n":
                if operator is None and initial_stack:
                    if len(stack) >= base_depth:
                        index += 1
                        continue
                    following = index + 1
                    while following < len(text) and text[following].isspace():
                        following += 1
                    if text[following:following + 1] == "=":
                        index += 1
                        continue
                    return None
                if operator is not None and not text[operator + 1:index].strip():
                    index += 1
                    continue
                if operator is not None:
                    current = text[operator + 1:index].rstrip()
                    following = index + 1
                    while following < len(text) and text[following].isspace():
                        following += 1
                    if current.endswith(("?", ":", "=>", "||", "&&", "??", ",", "\\")) or text[
                        following:following + 1
                    ] in {"?", ":"}:
                        index += 1
                        continue
                end = index
                break
            if character == ";":
                end = index
                break
            if character == ",":
                if operator_depth is not None and operator_depth > 0:
                    end = index
                    break
                if equals is None and initial_stack and initial_stack[-1] in "([":
                    comma_before_operator = True
                index += 1
                continue
            if (
                character == "="
                and (
                    text[index - 1:index] not in {"=", "!", "<", ">"}
                    or text[index - 2:index] in {"<<", ">>"}
                )
                and text[index + 1:index + 2] not in {"=", ">"}
                and equals is None
                and not (comma_before_operator and stack == initial_stack)
            ):
                equals = index
                operator_depth = len(stack)
            elif (
                character == ":"
                and text[index + 1:index + 2] != "="
                and colon is None
                and not (initial_stack and len(stack) < base_depth)
            ):
                statement_start = max(
                    text.rfind(";", 0, start),
                    text.rfind("{", 0, start),
                    text.rfind("}", 0, start),
                    text.rfind("\n", 0, start),
                    text.rfind("\r", 0, start),
                ) + 1
                if "?" in text[statement_start:start] and text[start - 1:start] != "?":
                    index += 1
                    continue
                colon = index
                operator_depth = len(stack)
        index += 1
    operator = equals if equals is not None else colon
    if operator is None:
        return None
    value = text[operator + 1:end].strip()
    return value or None


def string_ranges(
    text: str,
    shell: bool = False,
    python: bool = False,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    quote = ""
    start = 0
    escaped = False
    index = 0
    while index < len(text):
        if quote:
            if quote in {'"""', "'''"} and text.startswith(quote, index):
                index += len(quote)
                ranges.append((start, index))
                quote = ""
                continue
            if quote not in {'"""', "'''"}:
                if escaped:
                    escaped = False
                elif text[index] == "\\":
                    escaped = True
                elif text[index] == quote:
                    index += 1
                    ranges.append((start, index))
                    quote = ""
                    continue
                elif quote != "`" and text[index] in "\r\n":
                    ranges.append((start, index))
                    quote = ""
                    continue
            index += 1
            continue
        if text.startswith(('"""', "'''"), index):
            start = index
            quote = text[index:index + 3]
            index += 3
            continue
        if text[index] in "\"'`":
            start = index
            quote = text[index]
        elif is_line_comment(text, index, shell, python):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        index += 1
    if quote:
        ranges.append((start, len(text)))
    return ranges


def string_contents(text: str, shell: bool = False, python: bool = False) -> list[str]:
    contents: list[str] = []
    for start, end in string_ranges(text, shell, python):
        delimiter = text[start:start + 3] if text.startswith(('"""', "'''"), start) else text[start]
        close = len(delimiter) if text[max(start, end - len(delimiter)):end] == delimiter else 0
        contents.append(text[start + len(delimiter):end - close if close else end])
    return contents


def nested_string_contents(
    text: str,
    shell: bool = False,
    python: bool = False,
    max_depth: int = 8,
) -> tuple[list[str], bool]:
    contents: list[str] = []
    pending = [text]
    seen = {text}
    for _ in range(max_depth):
        next_pending: list[str] = []
        for value in pending:
            for content in string_contents(value, shell, python):
                contents.append(content)
                if content not in seen:
                    seen.add(content)
                    next_pending.append(content)
        if not next_pending:
            return contents, False
        pending = next_pending
    return contents, True


def python_docstrings(text: str) -> set[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return {
        node.body[0].value.value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }


def without_line_comments(
    value: str,
    shell: bool = False,
    python: bool = False,
) -> str:
    output: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character in "\"'`":
            quote = character
            output.append(character)
            index += 1
            continue
        if is_line_comment(value, index, shell, python):
            newline = value.find("\n", index)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        output.append(character)
        index += 1
    return "".join(output)


def compact_reference(value: str, python: bool = False) -> str:
    output: list[str] = []
    quote = ""
    escaped = False
    cleaned = without_line_comments(value, python=python)
    for index, character in enumerate(cleaned):
        if quote:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
            output.append(character)
        elif character.isspace():
            previous = next((item for item in reversed(output) if not item.isspace()), "")
            following = next((item for item in cleaned[index + 1:] if not item.isspace()), "")
            if previous and following and re.match(r"[A-Za-z0-9_$]", previous) and re.match(
                r"[A-Za-z0-9_$]", following
            ):
                output.append(" ")
        else:
            output.append(character)
    compact = "".join(output).rstrip(",;")
    while compact.startswith("(") and compact.endswith(")"):
        depth = 0
        closes_at_end = False
        for index, character in enumerate(compact):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(compact) - 1
                    break
        if not closes_at_end:
            break
        compact = compact[1:-1]
    return compact


def call_arguments(
    text: str,
    open_index: int,
    shell: bool = False,
    python: bool = False,
) -> tuple[str, int] | None:
    stack = ["("]
    quote = ""
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{"}
    index = open_index + 1
    while index < len(text):
        if quote:
            if quote in {'"""', "'''"} and text.startswith(quote, index):
                index += len(quote)
                quote = ""
                continue
            if quote not in {'"""', "'''"}:
                if escaped:
                    escaped = False
                elif text[index] == "\\":
                    escaped = True
                elif text[index] == quote:
                    quote = ""
                elif quote != "`" and text[index] in "\r\n":
                    quote = ""
            index += 1
            continue
        if text.startswith(('"""', "'''"), index):
            quote = text[index:index + 3]
            index += 3
            continue
        if is_line_comment(text, index, shell, python):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        character = text[index]
        if character in "\"'`":
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack[-1] != pairs[character]:
                return None
            stack.pop()
            if not stack:
                return text[open_index + 1:index].strip(), index
        index += 1
    return None


def generic_prefix_end(text: str, start: int = 0) -> int | None:
    if text[start:start + 1] != "<":
        return None
    depth = 0
    quote = ""
    escaped = False
    index = start
    while index < len(text):
        if quote:
            if escaped:
                escaped = False
            elif text[index] == "\\":
                escaped = True
            elif text[index] == quote:
                quote = ""
            index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
            continue
        if text[index] in "\"'`":
            quote = text[index]
        elif text[index] == "<":
            depth += 1
        elif text[index] == ">" and text[index - 1:index] != "=":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def skip_code_trivia(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                return len(text)
            index = end + 2
        elif text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
        else:
            break
    return index


def call_open_index(text: str, match: re.Match[str]) -> tuple[int, str] | None:
    name = match.group("quoted_name") or match.group("name")
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    statement_start = max(
        text.rfind(";", 0, match.start()),
        text.rfind("{", 0, match.start()),
        text.rfind("}", 0, match.start()),
    ) + 1
    prefix = re.sub(r"/\*.*?\*/|//[^\r\n]*", " ", text[statement_start:match.start()], flags=re.S)
    mutators = "|".join(SENSITIVE_MUTATORS)
    accessor = re.search(rf"\b(?P<mutator>{mutators})\s+(?:#|\[\s*)?$", prefix, re.S | re.I)
    preceding = re.search(
        rf"(?:\.(?P<dot>{mutators})|\[\s*[\"'](?P<bracket>{mutators})[\"']\s*\])(?:\?\.)?\s*$",
        prefix,
        re.I,
    )
    if accessor is not None or preceding is not None:
        preceding_mutator = (
            accessor.group("mutator")
            if accessor is not None
            else preceding.group("dot") or preceding.group("bracket")
        )
        normalized = preceding_mutator.casefold() + normalized
    index = match.end()
    index = skip_code_trivia(text, index)
    implicit_member = name.endswith(".")
    if match.group("quoted_name") is not None:
        if text[index:index + 1] == "]":
            index += 1
            index = skip_code_trivia(text, index)
        elif accessor is None:
            return None
    while True:
        marker = re.match(r"(?:\?\.|\.)", text[index:])
        if marker is not None:
            index = skip_code_trivia(text, index + marker.end())
        bracket_member = None
        if text[index:index + 1] == "[":
            bracket_start = skip_code_trivia(text, index + 1)
            bracket_member = re.match(rf"([\"'])(?P<name>{IDENTIFIER})\1", text[bracket_start:])
            if bracket_member is not None:
                bracket_end = skip_code_trivia(text, bracket_start + bracket_member.end())
                if text[bracket_end:bracket_end + 1] == "]":
                    normalized += re.sub(
                        r"[^a-z0-9]", "", bracket_member.group("name").casefold()
                    )
                    index = skip_code_trivia(text, bracket_end + 1)
                    implicit_member = False
                    continue
        member = (
            re.match(rf"(?P<name>{MEMBER_IDENTIFIER})", text[index:])
            if marker is not None or implicit_member
            else None
        )
        if member is not None:
            normalized += re.sub(r"[^a-z0-9]", "", member.group("name").casefold())
            index += member.end()
            index = skip_code_trivia(text, index)
            implicit_member = False
            continue
        break
    if text[index:index + 1] == "<":
        generic_end = generic_prefix_end(text, index)
        if generic_end is None:
            return None
        index = generic_end
        index = skip_code_trivia(text, index)
    if text.startswith("?.(", index):
        return index + 2, normalized
    if text.startswith(".(", index) and name.endswith("?"):
        return index + 1, normalized
    if text[index:index + 1] == "(":
        return index, normalized
    return None


def sensitive_call(normalized: str, suffixes: set[str]) -> bool:
    normalized = re.sub(r"(?:call|apply|bind)$", "", normalized)
    for suffix in suffixes:
        if normalized.endswith(suffix):
            prefix = normalized[:-len(suffix)]
            if any(
                prefix.startswith(mutator) or prefix.endswith(mutator)
                for mutator in SENSITIVE_MUTATORS
            ):
                return True
        if any(normalized.endswith(suffix + mutator) for mutator in SENSITIVE_MUTATORS):
            return True
    return False


def call_declaration(
    text: str,
    name_start: int,
    arguments: str,
    close_index: int,
) -> bool:
    line_start = max(text.rfind("\n", 0, name_start), text.rfind("\r", 0, name_start)) + 1
    prefix = text[line_start:name_start]
    if re.search(r"(?:\bdef|\bfunction)\s+$", prefix):
        return True
    statement_start = max(
        text.rfind(";", 0, name_start),
        text.rfind("{", 0, name_start),
        text.rfind("}", 0, name_start),
    ) + 1
    if "?" in text[statement_start:name_start]:
        return False
    following = text[close_index + 1:].lstrip()
    if following.startswith("{"):
        return True
    return re.match(
        r":\s*[A-Za-z_$][A-Za-z0-9_$<>,.?\[\] |&]*\s*(?:\{|;)", following
    ) is not None


def outer_wrapped(value: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    if len(value) < 2 or value[-1] != pairs.get(value[0]):
        return False
    stack: list[str] = []
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'`":
            quote = character
        elif character in pairs:
            stack.append(character)
        elif character in pairs.values():
            if not stack or pairs[stack.pop()] != character:
                return False
            if not stack and index != len(value) - 1:
                return False
    return not stack and not quote


def declaration_defaults(arguments: str) -> list[str]:
    defaults: list[str] = []
    parameters = split_top_level(arguments, ",", angles=True) or [arguments]
    for parameter in parameters:
        assignment = top_level_assignment(parameter)
        if assignment is not None:
            defaults.extend(declaration_defaults(assignment[0]))
            defaults.append(assignment[1])
            continue
        stripped = parameter.strip()
        if outer_wrapped(stripped):
            defaults.extend(declaration_defaults(stripped[1:-1]))
            continue
        annotation = split_top_level(stripped, ":")
        if annotation is not None:
            items = annotation[:1] if outer_wrapped(annotation[0].strip()) else annotation
            for item in items:
                defaults.extend(declaration_defaults(item))
    return defaults


def assignments(
    text: str,
    suffixes: set[str],
    shell: bool = False,
    python: bool = False,
    positions: bool = False,
) -> list[str] | list[tuple[str, int]]:
    values: list[str] | list[tuple[str, int]] = []

    def add(value: str) -> None:
        values.append((value, match.start()) if positions else value)
    ranges = string_ranges(text, shell, python)
    range_index = 0
    for match in FIELD.finditer(text):
        previous = match.start() - 1
        while previous >= 0 and text[previous].isspace():
            previous -= 1
        follows_assignment = (
            previous >= 0
            and text[previous] == "="
            and text[previous - 1:previous] not in {"=", "!", "<", ">"}
        )
        if (
            text[max(0, match.start() - 2):match.start()] == "${"
            or shell and (match.group("name") or "").startswith("$")
        ):
            continue
        while range_index < len(ranges) and ranges[range_index][1] <= match.start():
            range_index += 1
        if (
            match.group("name") is not None
            and range_index < len(ranges)
            and ranges[range_index][0] <= match.start() < ranges[range_index][1]
        ):
            continue
        name = match.group("quoted_name") or match.group("name")
        normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
        matched_suffix = next((suffix for suffix in suffixes if normalized.endswith(suffix)), None)
        call = call_open_index(text, match)
        if call is not None:
            if sensitive_call(call[1], suffixes):
                parsed = call_arguments(text, call[0], shell, python)
                if parsed is not None:
                    if call_declaration(text, match.start(), parsed[0], parsed[1]):
                        for value in declaration_defaults(parsed[0]):
                            add(value)
                    else:
                        add(f"{call[1]}({parsed[0]})")
            continue
        if follows_assignment:
            following_assignment = skip_code_trivia(text, match.end())
            if re.match(
                r"(?::=|(?:\*\*|<<|>>>|>>|\|\||&&|\?\?|[+\-*/%&|^])?=)",
                text[following_assignment:],
            ) is None:
                continue
        following = match.end()
        while following < len(text) and text[following] in " \t":
            following += 1
        if match.group("quoted_name") is not None and text[following:following + 1] not in {":", "]"}:
            continue
        if matched_suffix is None:
            continue
        if (
            match.group("name") is not None
            and text[following:following + 1] in ",)]}"
            and previous >= 0
            and text[previous] == ":"
        ):
            continue
        value = assignment_value(text, match.end(), shell, python)
        if value is not None:
            add(f"{normalized}({value})" if sensitive_call(normalized, suffixes) else value)
    return values


def split_top_level(value: str, delimiter: str, angles: bool = False) -> list[str] | None:
    parts: list[str] = []
    stack: list[str] = []
    quote = ""
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{", **({">": "<"} if angles else {})}
    start = 0
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if angles and value.startswith("/*", index):
            end = value.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if angles and value.startswith("//", index):
            end = value.find("\n", index + 2)
            index = len(value) if end < 0 else end + 1
            continue
        if character in "\"'`":
            quote = character
        elif character in "([{" or (
            angles and (delimiter != "=>" or not parts) and character == "<"
        ):
            stack.append(character)
        elif character in pairs and not (character == ">" and value[index - 1:index] == "="):
            if not stack or stack[-1] != pairs[character]:
                return None
            stack.pop()
        elif not stack and value.startswith(delimiter, index):
            parts.append(value[start:index].strip())
            index += len(delimiter)
            start = index
            continue
        index += 1
    if quote or stack or not parts:
        return None
    parts.append(value[start:].strip())
    return parts


def top_level_assignment(value: str) -> tuple[str, str] | None:
    stack: list[str] = []
    quote = ""
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'`":
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack[-1] != pairs[character]:
                return None
            stack.pop()
        elif (
            character == "="
            and not stack
            and value[index - 1:index] not in {"!", "<", ">", "=", ":"}
            and value[index + 1:index + 2] not in {"=", ">"}
        ):
            return value[:index].strip(), value[index + 1:].strip()
    return None


def top_level_ternary(value: str) -> tuple[str, str, str] | None:
    stack: list[str] = []
    quote = ""
    escaped = False
    question: int | None = None
    conditional_depth = 0
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'`":
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack[-1] != pairs[character]:
                return None
            stack.pop()
        elif (
            not stack
            and character == "?"
            and value[index - 1:index] not in {".", "?"}
            and value[index + 1:index + 2] not in {".", "?"}
        ):
            if question is None:
                question = index
            conditional_depth += 1
        elif not stack and character == ":" and question is not None:
            conditional_depth -= 1
            if conditional_depth == 0:
                return (
                    value[:question].strip(),
                    value[question + 1:index].strip(),
                    value[index + 1:].strip(),
                )
    return None


def has_suspicious_literal(value: str, suffixes: set[str]) -> bool:
    for content in string_contents(value):
        normalized = re.sub(r"[^a-z0-9]", "", content.casefold())
        if normalized in suffixes or (
            ("_" in content or "." in content)
            and any(normalized.endswith(suffix) for suffix in suffixes)
        ):
            continue
        return True
    return False


def has_explicit_literal(value: str) -> bool:
    return bool(string_contents(value)) or re.search(
        r"(?<![A-Za-z0-9_])\d{8,}(?![A-Za-z0-9_])", value
    ) is not None


def brace_scope(value: str, end: int) -> tuple[int, ...]:
    stack: list[int] = []
    quote = ""
    escaped = False
    index = 0
    while index < end:
        if quote:
            if escaped:
                escaped = False
            elif value[index] == "\\":
                escaped = True
            elif value[index] == quote:
                quote = ""
            index += 1
            continue
        if value.startswith("/*", index):
            close = value.find("*/", index + 2)
            index = end if close < 0 else close + 2
            continue
        if value.startswith("//", index):
            close = value.find("\n", index + 2)
            index = end if close < 0 else close + 1
            continue
        if value[index] in "\"'`":
            quote = value[index]
        elif value[index] == "{":
            stack.append(index)
        elif value[index] == "}" and stack:
            stack.pop()
        index += 1
    return tuple(stack)


def literal_bindings(value: str, suffixes: set[str]) -> dict[str, list[int]]:
    bindings: dict[str, list[int]] = {}
    cleaned = re.sub(
        r"/\*.*?\*/|//[^\r\n]*",
        lambda match: " " * len(match.group()),
        value,
        flags=re.S,
    )
    for match in re.finditer(
        rf"\b(?P<name>{IDENTIFIER})(?:\s*:\s*[^=;\r\n]+)?\s*=(?!=|>)\s*(?P<rhs>[^;\r\n]+)",
        cleaned,
    ):
        if match.group("name") in {"else", "except", "finally", "if", "return", "try", "while"}:
            continue
        rhs = match.group("rhs").strip()
        if rhs.endswith("):"):
            rhs = rhs[:-2].rstrip()
        if has_explicit_literal(rhs) and not code_reference(
            rhs, suffixes, nested=True
        ):
            bindings.setdefault(match.group("name"), []).append(match.start("name"))
    return bindings


def references_binding(
    value: str,
    position: int,
    bindings: dict[str, list[int]],
    source: str,
) -> bool:
    scope = brace_scope(source, position)

    def referenced(name: str) -> bool:
        return any(
            re.match(r"\s*=", value[match.end():]) is None
            for match in re.finditer(
                rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])",
                value,
            )
        )

    return any(
        referenced(name)
        and any(
            (binding_scope := brace_scope(source, binding)) == scope[:len(binding_scope)]
            for binding in positions
        )
        for name, positions in bindings.items()
    )


def block_reference(body: str, suffixes: set[str], python: bool = False) -> bool:
    if any(
        has_suspicious_literal(match.group("condition"), suffixes)
        for match in re.finditer(r"\bif\s*\((?P<condition>.*?)\)", body, re.S)
    ):
        return False
    bindings = literal_bindings(body, suffixes)
    if any(
        references_binding(value, position, bindings, body)
        or not code_reference(value, suffixes, python)
        for value, position in assignments(body, suffixes, python=python, positions=True)
    ):
        return False
    return all(
        not references_binding(match.group("value"), match.start(), bindings, body)
        and code_reference(match.group("value"), suffixes, python, nested=True)
        for match in re.finditer(
            r"\breturn\s+(?P<value>.*?)(?=;|\r?\n|})",
            body,
            re.S,
        )
    )


def static_lookup_key(value: str) -> bool:
    match = re.fullmatch(r"([\"'])(?P<key>[A-Za-z_][A-Za-z0-9_.]*)\1", value)
    return match is not None and len(match.group("key")) <= 32


def code_reference(
    value: str,
    suffixes: set[str],
    python: bool = False,
    nested: bool = False,
) -> bool:
    cleaned = without_line_comments(value, python=python).strip().rstrip(",;")
    if cleaned in {"None", "null", "undefined", "''", '""', "``", "()", "[]", "{}"}:
        return True
    if cleaned == "0" and suffixes == RUNTIME_SUFFIXES:
        return True
    arrow = split_top_level(cleaned, "=>", angles=True)
    if arrow is not None and len(arrow) == 2:
        parameters = re.sub(r"^async(?=\s|\(|<)\s*", "", arrow[0].strip())
        if parameters.startswith("<"):
            generic_end = generic_prefix_end(parameters)
            if generic_end is None:
                return False
            parameters = parameters[generic_end:].lstrip()
        if parameters.startswith("(") and parameters.endswith(")"):
            parameters = parameters[1:-1]
        defaults = declaration_defaults(parameters)
        body = arrow[1].strip()
        if body.startswith("{") and body.endswith("}"):
            body_ok = block_reference(body[1:-1], suffixes, python)
        else:
            body_ok = code_reference(body, suffixes, python, nested=True)
        return all(code_reference(item, suffixes, python) for item in defaults) and body_ok
    assignment = top_level_assignment(cleaned)
    if assignment is not None:
        return code_reference(assignment[1], suffixes, python, nested=True)
    conditional_return = re.fullmatch(
        r"if\s*\((?P<condition>.+)\)\s*return\s+(?P<value>.+)",
        cleaned,
        re.S,
    )
    if conditional_return is not None:
        return code_reference(
            conditional_return.group("condition"), suffixes, python, nested=True
        ) and code_reference(conditional_return.group("value"), suffixes, python, nested=True)
    js_ternary = top_level_ternary(cleaned)
    if js_ternary is not None:
        return (
            code_reference(js_ternary[0], suffixes, python, nested=True)
            and code_reference(js_ternary[1], suffixes, python, nested)
            and code_reference(js_ternary[2], suffixes, python, nested)
        )
    ternary = split_top_level(cleaned, " if ")
    if ternary is not None and len(ternary) == 2:
        alternatives = split_top_level(ternary[1], " else ")
        if alternatives is not None and len(alternatives) == 2:
            return (
                code_reference(ternary[0], suffixes, python, nested)
                and code_reference(alternatives[0], suffixes, python, nested=True)
                and code_reference(alternatives[1], suffixes, python, nested)
            )
    for operator in (" or ", "||", "??"):
        parts = split_top_level(cleaned, operator)
        if parts is not None:
            return all(code_reference(part, suffixes, python, nested) for part in parts)
    for operator in ("===", "!==", "==", "!=", "<=", ">=", "<", ">"):
        parts = split_top_level(cleaned, operator)
        if parts is not None:
            return all(code_reference(part, suffixes, python, nested=True) for part in parts)
    method_call = re.fullmatch(
        r"(?P<base>.+)\.(?:isdigit|isalnum|lower|casefold|strip)\(\)",
        cleaned,
        re.S,
    )
    if method_call is not None:
        return code_reference(method_call.group("base"), suffixes, python, nested=True)
    raw_call = re.fullmatch(
        rf"(?P<callee>{MEMBER_REFERENCE})(?:\?\.)?\((?P<args>.*)\)",
        cleaned,
        re.S,
    )
    if raw_call is not None:
        arguments = raw_call.group("args")
        if not arguments:
            return True
        call_parts = split_top_level(arguments, ",", angles=True) or [arguments]
        callee = re.sub(r"[^a-z0-9]", "", raw_call.group("callee").casefold())
        if callee.endswith(("dig", "pick")):
            return bool(call_parts) and code_reference(
                call_parts[0], suffixes, python, nested=True
            ) and all(
                static_lookup_key(part)
                or code_reference(part, suffixes, python, nested=True)
                for part in call_parts[1:]
            )
        if callee.endswith(("get", "getenv")) and re.fullmatch(QUOTED_KEY, call_parts[0]):
            call_parts = call_parts[1:]
        return all(
            code_reference(part, suffixes, python, nested=True)
            for part in call_parts
        )
    value = compact_reference(cleaned, python)
    js_ternary = top_level_ternary(value)
    if js_ternary is not None:
        return (
            code_reference(js_ternary[0], suffixes, python, nested=True)
            and code_reference(js_ternary[1], suffixes, python, nested)
            and code_reference(js_ternary[2], suffixes, python, nested)
        )
    if value.startswith("(") and value.endswith(")"):
        inner = value[1:-1]
        if split_top_level(inner, ",") is None:
            return code_reference(inner, suffixes, python, nested)
    if value.startswith("[") and value.endswith("]"):
        parts = split_top_level(value[1:-1], ",")
        if parts is None:
            return code_reference(value[1:-1], suffixes, python, nested=True)
        return all(code_reference(part, suffixes, python, nested=True) for part in parts)
    parts = split_top_level(value, ",")
    if parts is not None:
        return all(code_reference(part, suffixes, python, nested=True) for part in parts)
    if LOOKUP_REFERENCE.fullmatch(value) or INDEX_REFERENCE.fullmatch(value):
        return True
    keyword = re.fullmatch(rf"{IDENTIFIER}=(?P<value>.+)", value)
    if keyword is not None:
        return code_reference(keyword.group("value"), suffixes, python, nested)
    if re.fullmatch(MEMBER_REFERENCE, value):
        normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
        return nested or value == "value" or (
            len(value) <= 12 and not any(character.isdigit() for character in value)
        ) or "." in value or any(
            re.search(rf"{suffix}(?:v\d{{1,3}})?$", normalized) for suffix in suffixes
        )
    call = re.fullmatch(
        rf"(?P<callee>{MEMBER_REFERENCE})(?:\?\.)?\((?P<args>.*)\)", value
    )
    if call is None:
        return False
    arguments = call.group("args")
    if not arguments:
        return True
    call_parts = split_top_level(arguments, ",", angles=True) or [arguments]
    callee = re.sub(r"[^a-z0-9]", "", call.group("callee").casefold())
    if callee.endswith(("dig", "pick")):
        return bool(call_parts) and code_reference(
            call_parts[0], suffixes, python, nested=True
        ) and all(
            static_lookup_key(part)
            or code_reference(part, suffixes, python, nested=True)
            for part in call_parts[1:]
        )
    if callee.endswith(("get", "getenv")) and re.fullmatch(QUOTED_KEY, call_parts[0]):
        return all(
            code_reference(part, suffixes, python, nested=True) for part in call_parts[1:]
        )
    return all(
        code_reference(part, suffixes, python, nested=True)
        for part in call_parts
    )


def fence_language(info: str) -> str:
    token = info.strip().split(maxsplit=1)[0].casefold() if info.strip() else ""
    if token.startswith("{.") and token.endswith("}"):
        return token[2:-1]
    return token.removeprefix(".")


def contains_sensitive_url(text: str) -> bool:
    def sensitive_key(key: str) -> bool:
        normalized = key.casefold()
        return (
            normalized.startswith(("x-amz-", "x-goog-"))
            or normalized in {
                "sig", "policy", "key-pair-id", "auth", "auth_key", "code", "jwt",
                "hmac", "hdnea", "hdnts",
            }
            or re.search(r"(?:^|[_-])(?:token|signature|credential|secret)$", normalized)
            is not None
        )

    for raw_url in URL_PATTERN.findall(text):
        try:
            parsed = urlsplit(html.unescape(raw_url))
            parameters = parse_qsl(parsed.query, keep_blank_values=True)
            fragment = parsed.fragment
            if "?" in fragment:
                fragment = fragment.partition("?")[2]
            fragment_parameters = parse_qsl(fragment, keep_blank_values=True) if "=" in fragment else []
        except ValueError:
            continue
        if any((parsed.username, parsed.password)):
            return True
        if any(sensitive_key(key) for key, _ in [*parameters, *fragment_parameters]):
            return True
    return False


def contains_secret(*values: str) -> bool:
    for text in values:
        if CONCRETE_SECRET_PATTERN.search(text) or contains_sensitive_url(text):
            return True
        if assignments(text, CREDENTIAL_SUFFIXES):
            return True
    return False


def contains_runtime_state(*values: str) -> bool:
    def placeholder(item: str) -> bool:
        stripped = item.strip()
        return SHELL_REFERENCE.fullmatch(stripped) is not None or stripped in {
            "", "0", "''", '\"\"', "``", "...", "[...]",
        }

    def runtime_values(value: str) -> list[str]:
        found: list[str] = []
        def visible_text(text: str) -> str:
            clean = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
            clean = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", clean)).strip()
            return re.sub(r"\s*:\s*", ": ", clean)

        def prose_heading(position: int, item: str) -> bool:
            line_start = value.rfind("\n", 0, position) + 1
            line_end = value.find("\n", position)
            line_end = len(value) if line_end < 0 else line_end
            line = value[line_start:line_end]
            markdown = re.match(r"[ \t]{0,3}#{1,6}[ \t]+", line)
            context = line[markdown.end(): position - line_start] if markdown else ""
            tags = list(re.finditer(r"</?(h[1-6]|title)\b[^>]*>", value[:position], re.IGNORECASE))
            closing = re.search(rf"</{tags[-1].group(1)}\s*>", value[position:], re.IGNORECASE) if tags else None
            html = bool(
                tags
                and not tags[-1].group(0).startswith("</")
                and closing
            )
            inline_reference = False
            if not markdown and not html:
                context = visible_text(line[: position - line_start])
                section_headings = list(
                    re.finditer(
                        r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(?P<title>[^\n]+)$",
                        value[:line_start],
                    )
                )
                reference_section = bool(
                    section_headings
                    and visible_text(section_headings[-1].group("title"))
                    .rstrip(": ")
                    .casefold()
                    in {"reference", "references", "referenced", "see also", "further reading"}
                )
                citation = re.fullmatch(
                    r"[ \t]*(?:[-*+]|\u2022)\s+"
                    r"(?P<title>[^|<>\r\n]+?)\s+\\?\|\s+"
                    r"(?P<byline>[^|<>\r\n]+?)\s*:\s*"
                    r"\[(?P<url>https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?"
                    r"(?:/[a-z0-9._~!$&'()*+,;=:@/-]*)?)\]"
                    r"\((?P=url)\)\s*",
                    line,
                )
                inline_reference = False
                if reference_section and citation:
                    offset = position - line_start
                    byline = visible_text(citation.group("byline"))
                    parsed_url = urlsplit(citation.group("url"))
                    hostname = parsed_url.hostname or ""
                    opaque_url_component = any(
                        (
                            re.fullmatch(r"[a-z0-9]{14,}", component)
                            and re.search(r"\d", component)
                        )
                        or re.fullmatch(
                            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                            component,
                        )
                        for component in [*hostname.split("."), *parsed_url.path.split("/")]
                    )
                    unsafe_marker = re.compile(
                        r"(?:^|[./_-])(?:opaque|runtime|checkpoint|token|secret|credential)"
                        r"(?:$|[./_-])",
                        re.IGNORECASE,
                    )
                    inline_reference = bool(
                        citation.start("title") <= offset < citation.end("title")
                        and "." in hostname
                        and not any(label.startswith("xn--") for label in hostname.split("."))
                        and not any(
                            not label or label.startswith("-") or label.endswith("-")
                            for label in hostname.split(".")
                        )
                        and not opaque_url_component
                        and not unsafe_marker.search(byline)
                        and not unsafe_marker.search(citation.group("url"))
                        and not (
                            re.fullmatch(r"\S+", byline)
                            and (
                                len(byline) >= 14
                                or (re.search(r"\d", byline) and len(byline) >= 8)
                            )
                        )
                        and not assignments(byline, CREDENTIAL_SUFFIXES | RUNTIME_SUFFIXES)
                    )
                if not inline_reference:
                    return False
            if markdown:
                field = FIELD.match(value, position)
                separator = field and re.match(r"(?:[ \t]|</?[^>]+>)*:", value[field.end():])
                if field and separator:
                    start = field.end() + separator.end()
                    item = value[start:line_end]
            if html:
                context = value[tags[-1].end():position]
                field = FIELD.match(value, position)
                separator = field and re.match(r"(?:[ \t]|</?[^>]+>)*:", value[field.end():])
                if field and separator and closing:
                    start = field.end() + separator.end()
                    item = value[start: position + closing.start()]
            rendered = visible_text(item)
            checked = re.split(r"\s*\\?\|\s*", rendered, maxsplit=1)[0].strip() if inline_reference else rendered
            runtime_phrase = re.search(
                r"\b(?:runtime\s+state|stored\s+(?:state|value|cursor|token)|pagination|"
                r"resume\s+(?:from|using)|start\s+after|"
                r"continue\s+(?:from|at|with)|fetch\s+using|request\s+for|token\s+value|"
                r"(?:current|active|checkpoint|saved|continuation)\s+"
                r"(?:state|value|cursor|token)|last\s+checkpoint|"
                r"after\s+item|next\s+(?:page|request)|page\s*(?::|=)?\s*\d+|shard)\b",
                f"{visible_text(context)} {rendered}" if inline_reference else checked,
                re.IGNORECASE,
            )
            opaque_token = bool(
                re.fullmatch(r"\S+", checked)
                and (
                    inline_reference
                    or len(checked) >= 14
                    or (re.search(r"\d", checked) and len(checked) >= 8)
                )
            )
            return (
                bool(visible_text(context) or rendered)
                and not runtime_phrase
                and not opaque_token
            )

        for item, position in assignments(value, RUNTIME_SUFFIXES, positions=True):
            match = FIELD.match(value, position)
            colon = match and re.match(r"(?:[ \t]|</?[^>]+>)*:", value[match.end():])
            if (
                match
                and (match.group("name") or match.group("quoted_name") or "").casefold() == "cursor"
                and colon
                and prose_heading(position, item)
            ):
                continue
            found.append(item)
        return found

    return any(
        any(
            not placeholder(item)
            for item in runtime_values(value)
        )
        for value in values
    )


def contains_code_secret(
    *values: str,
    shell: bool = False,
    python: bool = False,
) -> bool:
    for text in values:
        if CONCRETE_SECRET_PATTERN.search(text) or contains_sensitive_url(text):
            return True
        embedded, truncated = nested_string_contents(text, shell, python)
        if truncated:
            return True
        if any(
            assignments(content, CREDENTIAL_SUFFIXES, shell, python)
            for content in embedded
        ):
            return True
        bindings = literal_bindings(text, CREDENTIAL_SUFFIXES)
        for value, position in assignments(
            text, CREDENTIAL_SUFFIXES, shell, python, positions=True
        ):
            if references_binding(value, position, bindings, text):
                return True
            if shell and not SHELL_REFERENCE.fullmatch(without_line_comments(value, shell=True).strip()):
                return True
            if not shell and not code_reference(value, CREDENTIAL_SUFFIXES, python):
                return True
    return False


def contains_code_runtime_state(
    *values: str,
    shell: bool = False,
    python: bool = False,
) -> bool:
    for text in values:
        embedded, truncated = nested_string_contents(text, shell, python)
        if truncated:
            return True
        docstrings = python_docstrings(text) if python else set()
        if any(
            any(
                item.strip()
                not in {
                    "",
                    "0",
                    "''",
                    '\"\"',
                    "``",
                    "...",
                    "[...]",
                    "分页游标",
                    "下一页位置",
                    "用于继续分页的标记",
                }
                for item in assignments(content, RUNTIME_SUFFIXES)
            ) if content in docstrings else contains_runtime_state(content)
            for content in embedded
        ):
            return True
        bindings = literal_bindings(text, RUNTIME_SUFFIXES)
        for value, position in assignments(
            text, RUNTIME_SUFFIXES, shell, python, positions=True
        ):
            if references_binding(value, position, bindings, text):
                return True
            if shell and not SHELL_REFERENCE.fullmatch(without_line_comments(value, shell=True).strip()):
                return True
            if not shell and not code_reference(value, RUNTIME_SUFFIXES, python):
                return True
    return False


def contains_document_secret(*values: str) -> bool:
    for value in values:
        document = without_fenced_code(value)
        embedded, truncated = nested_string_contents(document)
        if truncated:
            return True
        if contains_secret(document) or any(
            contains_secret(content) for content in embedded
        ):
            return True
        for match in FENCED_CODE.finditer(value):
            language = fence_language(match.group("info"))
            if language not in CODE_LANGUAGES:
                if contains_secret(match.group("body")):
                    return True
            elif contains_code_secret(
                match.group("body"),
                shell=language in SHELL_LANGUAGES,
                python=language in PYTHON_LANGUAGES,
            ):
                return True
    return False


def contains_document_runtime_state(*values: str) -> bool:
    for value in values:
        document = without_fenced_code(value)
        rendered = re.sub(r"<!--.*?-->", "", document, flags=re.DOTALL)
        rendered = re.sub(
            r"</?(?:article|aside|blockquote|body|br|div|footer|header|li|main|nav|p|section|table|td|th|tr)\b[^>]*>",
            "\n",
            rendered,
            flags=re.IGNORECASE,
        )
        rendered = re.sub(r"<(?!/?(?:h[1-6]|title)\b)[^>]*>", "", rendered, flags=re.IGNORECASE)
        embedded, truncated = nested_string_contents(document)
        if truncated:
            return True
        if contains_runtime_state(document, rendered) or any(
            contains_runtime_state(content) for content in embedded
        ):
            return True
        for match in FENCED_CODE.finditer(value):
            language = fence_language(match.group("info"))
            if language not in CODE_LANGUAGES:
                if contains_runtime_state(match.group("body")):
                    return True
            elif contains_code_runtime_state(
                match.group("body"),
                shell=language in SHELL_LANGUAGES,
                python=language in PYTHON_LANGUAGES,
            ):
                return True
    return False


def contains_key(value: Any, names: set[str]) -> bool:
    if isinstance(value, Mapping):
        normalized_names = {re.sub(r"[^a-z0-9]", "", name.casefold()) for name in names}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if (
                normalized in normalized_names
                or normalized.endswith("cursor")
                or normalized in {"pagetoken", "continuationtoken", "refreshtoken", "sessiontoken"}
            ):
                return True
            if contains_key(item, names):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_key(item, names) for item in value)
    return False
