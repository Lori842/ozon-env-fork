# Copyright INRIM (https://www.inrim.eu)
# See LICENSE file for full licensing details.


import decimal
import re
import datetime
from datetime import timedelta
from typing import Any, Dict, Pattern, cast

import bson
import bson.binary
import bson.decimal128
import bson.int64
import bson.regex
from pydantic.datetime_parse import parse_datetime
from pydantic.main import BaseModel
from pydantic.validators import (
    bytes_validator,
    decimal_validator,
    int_validator,
    pattern_validator,
)
from bson.objectid import ObjectId as BsonObjectId
from bson.codec_options import TypeRegistry
from bson.codec_options import CodecOptions
from bson.codec_options import TypeCodec
from decimal import *
import json


class PyObjectId(BsonObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, (BsonObjectId, cls)):
            return v
        if isinstance(v, str) and BsonObjectId.is_valid(v):
            return BsonObjectId(v)
        raise TypeError("invalid ObjectId specified")

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class Int64(bson.int64.Int64):
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema: Dict) -> None:
        field_schema.update(examples=[2147483649], type="number")

    @classmethod
    def validate(cls, v: Any) -> bson.int64.Int64:
        if isinstance(v, bson.int64.Int64):
            return v
        a = int_validator(v)
        return bson.int64.Int64(a)


class Decimal128(bson.decimal128.Decimal128):
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema: Dict) -> None:
        field_schema.update(examples=[214.7483649], example=214.7483649,
                            type="number")

    @classmethod
    def validate(cls, v: Any) -> bson.decimal128.Decimal128:
        # if isinstance(v, bson.decimal128.Decimal128):
        #     return v
        a = decimal_validator(v)
        return float(a)


class Binary(bson.binary.Binary):
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema: Dict) -> None:
        field_schema.update(type="string", format="binary")

    @classmethod
    def validate(cls, v: Any) -> bson.binary.Binary:
        if isinstance(v, bson.binary.Binary):
            return v
        a = bytes_validator(v)
        return bson.binary.Binary(a)


class Regex(bson.regex.Regex):
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema: Dict) -> None:
        field_schema.update(
            examples=[r"^Foo"], example=r"^Foo", type="string", format="binary"
        )

    @classmethod
    def validate(cls, v: Any) -> bson.regex.Regex:
        if isinstance(v, bson.regex.Regex):
            return v
        a = pattern_validator(v)
        return bson.regex.Regex(a.pattern)


class _Pattern:
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> Pattern:
        if isinstance(v, Pattern):
            return v
        elif isinstance(v, bson.regex.Regex):
            return re.compile(v.pattern, flags=v.flags)

        a = pattern_validator(v)
        return a


class DateTime(datetime.datetime):
    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            d = v
        else:
            d = parse_datetime(v)
        # MongoDB does not store timezone info
        # https://docs.python.org/3/library/datetime.html#determining-if-an-object-is-aware-or-naive
        if d.tzinfo is not None and d.tzinfo.utcoffset(d) is not None:
            raise ValueError(
                "datetime objects must be naive (no timezone info)")
        # Truncate microseconds to milliseconds to comply with Mongo behavior
        microsecs = d.microsecond - d.microsecond % 1000
        return d.replace(microsecond=microsecs)

    @classmethod
    def __modify_schema__(cls, field_schema: Dict) -> None:
        field_schema.update(example=datetime.utcnow().isoformat())


class _decimalDecimal(decimal.Decimal):
    """This specific BSON substitution field helps to handle the support of standard
    python Decimal objects
    https://api.mongodb.com/python/current/faq.html?highlight=decimal#how-can-i-store-decimal-decimal-instances
    """

    @classmethod
    def __get_validators__(cls):  # type: ignore
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> decimal.Decimal:
        if isinstance(v, decimal.Decimal):
            return v
        elif isinstance(v, bson.decimal128.Decimal128):
            return cast(decimal.Decimal, v.to_decimal())

        a = decimal_validator(v)
        return a

    @classmethod
    def __bson__(cls, v: Any) -> bson.decimal128.Decimal128:
        return bson.decimal128.Decimal128(v)


# Codec
class Decimal128Codec(TypeCodec):
    python_type = decimal.Decimal  # the Python type acted upon by this type codec
    bson_type = Decimal128  # the BSON type acted upon by this type codec

    def transform_python(self, value):
        """Function that transforms a custom type value into a type
        that BSON can encode."""
        return Decimal128(value)

    def transform_bson(self, value):
        """Function that transforms a vanilla BSON type value into our
        custom type."""
        return float(value.to_decimal())


class JsonEncoder(json.JSONEncoder):
    """JSON serializer for objects not serializable by default json code"""

    def default(self, o):
        if isinstance(o, bson.decimal128.Decimal128):
            return float(o.to_decimal())
        if isinstance(o, bson.objectid.ObjectId):
            return str(o)
        if isinstance(o, (datetime.datetime, datetime.date, datetime.time)):
            return o.isoformat()
        elif isinstance(o, timedelta):
            return (datetime.datetime.min + o).time().isoformat()
        return super().default(o)


decimal_codec = Decimal128Codec()

type_registry = TypeRegistry([])
codec_options = CodecOptions(type_registry=type_registry)

BSON_TYPES_ENCODERS = {
    bson.ObjectId: str,
    bson.decimal128.Decimal128: lambda x: float(x.to_decimal()),
    # Convert to regular decimal
    bson.regex.Regex: lambda x: x.pattern,
    # TODO: document no serialization of flags
    # DateTime: str
}

_BSON_SUBSTITUTED_FIELDS = {
    bson.ObjectId: PyObjectId,
    bson.int64.Int64: Int64,
    bson.decimal128.Decimal128: Decimal128,
    bson.binary.Binary: Binary,
    bson.regex.Regex: Regex,
    Pattern: _Pattern,
    decimal.Decimal: _decimalDecimal,
    datetime.datetime: DateTime,
}
