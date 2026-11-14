import re

# The JSON types a documented field may arrive as (field types are part of the response shape). ``None`` (JSON
# null) is accepted for every field that is not required. ``bool`` is never an ``INT`` or a ``NUMBER``.
STRING = (str,)
BOOLEAN = (bool,)
# A flag: the API documents some as JSON booleans and shows others as "true"/"false" strings.
FLAG = (bool, str)
INT = (int,)
NUMBER = (int, float)
ARRAY = (list,)
# A bulk "message": a string, or an array of strings.
TEXT_OR_ARRAY = (str, list)

_INTEGER_STRING = re.compile(r"-?[0-9]+")


def items_as_received(data, name, item_class):
    """The object items of an array field: a list (``[]`` when the field is absent), or None when the API sent null."""
    value = data.get(name, [])
    return None if value is None else [item_class(item) for item in value]


class ZBFieldTypeError(ValueError):
    """A field of the response has the wrong JSON type. The text names the field, never its value."""


def _type_ok(value, kinds) -> bool:
    if isinstance(value, bool):
        return bool in kinds
    return isinstance(value, kinds)


class ZBResponse(object):
    # Field name -> the JSON types it may arrive as. Every annotated field read from the API is listed here (a
    # test checks it); fields the SDK fills itself are in _SDK_FIELDS.
    _FIELD_TYPES = {}
    # Fields that must be present and not null.
    _REQUIRED = ()
    # Array fields whose items are objects of a response class: name -> class.
    _ITEMS = {}
    _SDK_FIELDS = ()

    def __init__(self, data=None):
        self.__dict__ = data if data is not None else {}

    def _fields(self) -> dict:
        """Every documented field (None when the API did not send it), then any extra key as received."""
        fields = {}
        for cls in reversed(type(self).__mro__):
            for name in getattr(cls, "__annotations__", {}):
                if not name.startswith("_"):
                    fields[name] = getattr(type(self), name, None)
        fields.update(self.__dict__)
        return fields

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._fields()!r})"

    def __str__(self) -> str:
        return str(self.__class__.__name__) + "=" + str(self._fields())

    @classmethod
    def _required_fields(cls, data):
        return cls._REQUIRED

    @classmethod
    def _check_values(cls, data):
        """Checks beyond the JSON type (e.g. a string that must hold an integer)."""

    @classmethod
    def check_shape(cls, data, path=""):
        """Raise ZBFieldTypeError when ``data`` (a JSON object) is not the documented shape of this response."""
        if not isinstance(data, dict):
            raise ZBFieldTypeError(f"{path or 'the response'} is not a JSON object")
        for name in cls._required_fields(data):
            if data.get(name) is None:
                raise ZBFieldTypeError(f"{path}{name} is missing")
        for name, kinds in cls._FIELD_TYPES.items():
            value = data.get(name)
            if value is None:
                continue
            if not _type_ok(value, kinds):
                raise ZBFieldTypeError(f"{path}{name} has the wrong type")
            if kinds is TEXT_OR_ARRAY and isinstance(value, list) and not all(isinstance(v, str) for v in value):
                raise ZBFieldTypeError(f"{path}{name} has the wrong type")
            item_class = cls._ITEMS.get(name)
            if item_class is not None:
                for index, item in enumerate(value):
                    item_class.check_shape(item, f"{path}{name}[{index}].")
        cls._check_values(data)


class ZBFileResponse(ZBResponse):
    success: bool = False

    message: str = None

    _FIELD_TYPES = {"success": FLAG, "message": TEXT_OR_ARRAY}

    @classmethod
    def _check_values(cls, data):
        success = data.get("success")
        if isinstance(success, str) and success.strip().lower() not in ("true", "false", "1", "0"):
            raise ZBFieldTypeError("success has the wrong type")

    def __init__(self, data):
        super().__init__(data)
        if isinstance(self.message, list):
            self.message = "\n".join(self.message)
        if isinstance(self.success, str):
            text = self.success.strip().lower()
            if text in ("true", "1"):
                self.success = True
            elif text in ("false", "0"):
                self.success = False
