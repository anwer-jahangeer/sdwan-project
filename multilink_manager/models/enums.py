"""Enumerations used by the typed models."""

from __future__ import annotations

from enum import Enum


class InterfaceType(str, Enum):
    ETHERNET = "ethernet"
    WIFI = "wifi"
    OTHER = "other"
    UNKNOWN = "unknown"


class InterfaceStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class TargetType(str, Enum):
    GATEWAY = "gateway"
    ICMP = "icmp"
    HTTPS = "https"
    AGGREGATE = "aggregate"
