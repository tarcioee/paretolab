"""Messages that a user interface can translate.

A :class:`Note` is a plain English string (so the CLI, logs and tests use it like any string) that also carries a
code and its arguments. Wherever a message is written to a JSON file read by the web interface, :func:`info` turns
it into ``{"code", "args", "text"}``; the interface translates known codes and shows ``text`` otherwise.
"""


class Note(str):
    code: str
    args: dict
    prefix: str | None

    def __new__(cls, code: str, template: str, prefix: str | None = None, **args):
        text = template.format(**args)
        note = super().__new__(cls, f"{prefix}: {text}" if prefix else text)
        note.code, note.args, note.prefix = code, args, prefix
        return note

    def under(self, prefix: str) -> "Note":
        """The same message shown under a prefix (an indicator or instance name), e.g. ``"hv: ..."``."""
        copy = str.__new__(Note, f"{prefix}: {self}")
        copy.code, copy.args = self.code, self.args
        copy.prefix = f"{prefix}: {self.prefix}" if self.prefix else prefix
        return copy


def note(code: str, template: str, **args) -> Note:
    return Note(code, template, **args)


def plain(value):
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def info(message) -> dict:
    """``{"code", "args", "prefix", "text"}`` of a message; code is None for a plain string."""
    if isinstance(message, Note):
        return {"code": message.code, "args": plain(message.args), "prefix": message.prefix, "text": str(message)}
    return {"code": None, "args": {}, "prefix": None, "text": str(message)}


def under(prefix: str, message) -> str:
    return message.under(prefix) if isinstance(message, Note) else f"{prefix}: {message}"
