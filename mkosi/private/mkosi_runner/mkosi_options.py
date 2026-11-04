"""Finds mkosi options in mkosi arguments in every spelling that mkosi's command-line parser accepts.

The option spellings and the options that take paths are read from mkosi's own argument parser and settings table,
so that run_mkosi.py recognizes the same options as the mkosi version that it runs.
"""

import functools
from dataclasses import dataclass

# The mkosi argument parser destination of -C/--directory, which is a command-line option rather than a setting.
DIRECTORY = "directory"


@dataclass(frozen=True)
class Option:
    """An mkosi command-line option.

    Attributes:
        dest: mkosi's argument parser destination, shared by all spellings of the option.
        arguments: "none", "one" or "optional", the number of values that the option takes.
        path: None, "path" or "tree" ("source[:target]") when the values of the option are paths.
        path_list: Whether the value is a list of paths separated by commas or whitespace.
        constants: Values that mkosi accepts instead of a path.
    """

    dest: str
    arguments: str
    path: str | None = None
    path_list: bool = False
    constants: tuple[str, ...] = ()

    def declared_paths(self, value):
        """Returns the paths in value, without constants and without the in-image targets of trees."""
        return [self._source(item)[0] for item in self._items(value) if item not in self.constants]

    def map_paths(self, value, function):
        """Returns value with function applied to each of its paths; constants and tree targets stay unchanged."""
        items = [item if item in self.constants else self._map_item(item, function) for item in self._items(value)]
        return ",".join(items) if self.path_list else "".join(items)

    def _items(self, value):
        # mkosi splits list values on commas and whitespace, and an empty value resets the list.
        return value.replace(",", " ").split() if self.path_list else [value] if value else []

    def _source(self, item):
        if self.path == "tree":
            return item.partition(":")
        return (item, "", "")

    def _map_item(self, item, function):
        source, separator, target = self._source(item)
        return function(source) + separator + target


@dataclass(frozen=True)
class Occurrence:
    """An option in an argument list; its value is arguments[index] without prefix."""

    option: Option
    spelling: str
    index: int
    prefix: str
    value: str | None

    def replace(self, arguments, value):
        arguments[self.index] = self.prefix + value


@functools.cache
def _parser():
    import mkosi.config

    return mkosi.config.create_argument_parser(chdir=False)


@functools.cache
def option_table():
    """Returns mkosi's options by spelling, read from mkosi's argument parser and settings table."""
    import mkosi.config

    parser = _parser()
    classify = _PathClassifier(mkosi.config)
    table = {}
    # argparse exposes its option actions only through this attribute.
    for action in parser._actions:
        if not action.option_strings:
            continue
        option = Option(action.dest, _arguments(action.nargs), *classify(action.dest))
        for spelling in action.option_strings:
            table[spelling] = option
    if DIRECTORY not in {option.dest for option in table.values()}:
        raise SystemExit("mkosi has no -C/--directory option; this mkosi version is not supported")
    return table


def _arguments(nargs):
    if nargs == 0:
        return "none"
    if nargs == "?":
        return "optional"
    return "one"


class _PathClassifier:
    """Classifies settings whose values mkosi parses with its path or tree parsers.

    Closures created by the same mkosi parser factory share one code object, so a reference closure of each factory
    identifies the parser of every setting without depending on the names of mkosi's private functions.
    """

    def __init__(self, config):
        self._config = config
        self._path = config.config_make_path_parser().__code__
        self._tree = config.make_tree_parser().__code__
        self._list = config.config_make_list_parser().__code__

    def __call__(self, dest):
        if dest == DIRECTORY:
            return ("path", False, ())
        setting = self._config.SETTINGS_LOOKUP_BY_DEST.get(dest)
        if setting is None:
            return (None, False, ())
        parse = setting.parse
        path_list = getattr(parse, "__code__", None) is self._list
        if path_list:
            parse = _closure(parse)["parse"]
        kind, constants = self._element(parse)
        return (kind, path_list and kind is not None, constants)

    def _element(self, parse):
        if isinstance(parse, functools.partial) and parse.func is self._config.parse_path:
            return ("path", tuple(parse.keywords.get("constants", ())))
        code = getattr(parse, "__code__", None)
        if code is self._path:
            return ("path", tuple(_closure(parse)["constants"]))
        if code is self._tree:
            return ("tree", ())
        return (None, ())


def _closure(function):
    return dict(
        zip(function.__code__.co_freevars, (cell.cell_contents for cell in function.__closure__ or ()), strict=True)
    )


def option(spelling):
    """Returns the mkosi option with the given spelling."""
    table = option_table()
    if spelling not in table:
        raise SystemExit("mkosi has no {} option; this mkosi version is not supported".format(spelling))
    return table[spelling]


def occurrences(arguments, table=None):
    """Returns the Occurrences of known mkosi options in arguments, as mkosi's argument parser reads them.

    An option's value may be the next argument or attached to the option as --option=value, -Ovalue or -O=value, also
    after single-letter flags such as -fO value. Parsing stops at --, after which mkosi reads no options.
    """
    table = option_table() if table is None else table
    found = []
    index = 0
    while index < len(arguments) and arguments[index] != "--":
        index = _scan(table, arguments, index, found)
    return found


def _scan(table, arguments, index, found):
    parsed = _parse_option(table, arguments[index])
    if parsed is None:
        return index + 1
    spelling, prefix, explicit = parsed
    while table[spelling].arguments == "none" and explicit:
        # argparse reads the rest of a single-dash flag as further single-letter options.
        if prefix.endswith("=") or "-" + explicit[0] not in table:
            return index + 1
        spelling = "-" + explicit[0]
        prefix += explicit[0]
        explicit = explicit[1:]
        if explicit.startswith("="):
            # -fC= gives -C an empty value, like --directory=.
            prefix += "="
            explicit = explicit[1:]
        elif not explicit:
            explicit = None
    current = table[spelling]
    if current.arguments == "none" or explicit is not None:
        found.append(Occurrence(current, spelling, index, prefix, explicit))
        return index + 1
    following = index + 1
    if following < len(arguments) and arguments[following] != "--" and not _is_option(table, arguments[following]):
        found.append(Occurrence(current, spelling, following, "", arguments[following]))
        return following + 1
    found.append(Occurrence(current, spelling, index, prefix, None))
    return index + 1


def _parse_option(table, argument):
    """Returns (spelling, prefix of an attached value, attached value or None) for a known option, or None."""
    if argument in table:
        return (argument, argument, None)
    if not argument.startswith("-") or len(argument) == 1:
        return None
    name, separator, value = argument.partition("=")
    if separator and name in table:
        return (name, name + "=", value)
    if argument[1] != "-" and argument[:2] in table:
        return (argument[:2], argument[:2], argument[2:])
    return None


def _is_option(table, argument):
    """Returns whether mkosi's argument parser reads argument as an option rather than as a value."""
    if not argument.startswith("-") or len(argument) == 1:
        return False
    if _parse_option(table, argument) is not None:
        return True
    return not _is_negative_number(argument) and " " not in argument


def _is_negative_number(argument):
    """Returns whether mkosi's argument parser reads argument as a negative number, which is a value."""
    # argparse exposes its negative number rule only through these attributes.
    parser = _parser()
    negative = parser._negative_number_matcher.match(argument)
    return bool(negative) and not parser._has_negative_number_optionals
