"""Read JSON without silently changing unsupported numeric declarations."""
from decimal import Decimal, InvalidOperation
import json
import math


class UnsupportedNumericPrecision(ValueError):
    pass


def checked_float(token):
    try:
        value = float(token)
        supported = math.isfinite(value) and Decimal(token) == Decimal(str(value))
    except (InvalidOperation, ValueError, OverflowError):
        supported = False
    if not supported:
        raise UnsupportedNumericPrecision('unsupported_numeric_precision: ' + token)
    return value


def _non_json_number(token):
    raise UnsupportedNumericPrecision('unsupported_numeric_precision: non-JSON ' + token)


def loads(raw):
    return json.loads(raw, parse_float=checked_float, parse_constant=_non_json_number)


def load(stream):
    return loads(stream.read())
