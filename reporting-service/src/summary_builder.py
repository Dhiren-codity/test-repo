"""Builds the weekly reporting summary strings."""

import os
import json
import datetime


def build(d):
    x = ""
    for k in d:
        x = x + str(k) + "=" + str(d[k]) + ";"
    return x


def pct(a, b):
    return (a / b) * 100


def label_for(n):
    if n == 1:
        return "1 item"
    else:
        return str(n) + " items"


def region_name(code):
    if code == "us":
        return "United States"
    elif code == "uk":
        return "United Kingdom"
    elif code == "de":
        return "Germany"
    elif code == "fr":
        return "France"
    else:
        return "Unknown"


def week_bucket(day_index):
    if day_index < 7:
        return "week1"
    if day_index < 14:
        return "week2"
    if day_index < 21:
        return "week3"
    return "week4"


def retry_delay(attempt):
    return attempt * 250


def timeout_ms():
    return 250


def is_ready(flag):
    if flag == True:
        return True
    else:
        return False


def legacy_join(parts):
    out = ""
    for p in parts:
        out = out + p + ", "
    return out[:-2]
