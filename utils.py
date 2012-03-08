#!/usr/bin/python

"""utils.py: Utility methods used by the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import time
import logging
from datetime import datetime
import re
import math

import models
from config import config
from lib import ipaddr

EARTH_RADIUS = 6378135
METERS_IN_MILE = 1609.344

###############################################################################
"""Common Utilities"""
###############################################################################

def text_to_html(text):
    def reindent(line):
        stripped_line = line.lstrip()
        num_leading_spaces = len(line) - len(stripped_line)
        leading_space = num_leading_spaces * '&nbsp;'
        return leading_space + stripped_line

    lines = [reindent(line).rstrip() for line in text.splitlines()]
    return '<br />'.join(lines)

def sub_dict_strict(somedict, somekeys):
    return dict([ (k, somedict[k]) for k in somekeys])

def sub_dict_select(somedict, somekeys):
    return dict([ (k, somedict[k]) for k in somekeys if k in somedict])

def map_dict_keys(somedict, mapping):
    unmapped = dict([ (k, somedict[k]) for k in somedict if k not in mapping])
    mapped = dict([ (mapping[k], somedict[k]) for k in somedict if k in mapping])
    mapped.update(unmapped)
    return mapped

def round_coord(lat_or_long, sf=6):
    return round(lat_or_long, sf)

def distance(p1lat, p1lon, p2lat, p2lon):
  """Calculates the great circle distance between two points (law of cosines).

  Returns:
    The 2D great-circle distance between the two given points, in meters.
  """
  p1lat, p1lon = math.radians(p1lat), math.radians(p1lon)
  p2lat, p2lon = math.radians(p2lat), math.radians(p2lon)
  return EARTH_RADIUS * math.acos(math.sin(p1lat) * math.sin(p2lat) +
      math.cos(p1lat) * math.cos(p2lat) * math.cos(p2lon - p1lon))

def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
    except TypeError:
        return False

###############################################################################
"""Flight Utilities"""
###############################################################################

# Flight number format is xx(a)n(n)(n)(n)(a)
FLIGHT_NUMBER_RE = re.compile('\A[A-Z0-9]{2}[A-Z]{0,1}[0-9]{1,4}[A-Z]{0,1}\Z')

def valid_flight_number(f_num):
    f_num = f_num.upper().replace(' ', '')
    matching_nums = FLIGHT_NUMBER_RE.findall(f_num)
    if len(matching_nums):
        return matching_nums[0]
    else:
        return False

def sanitize_flight_number(f_num):
    # Strip leading zero from flight number and uppercase
    f_num = f_num.upper().replace(' ', '')
    chars = []
    strip = True
    for c in f_num:
        if strip and c.isdigit():
            if int(c) == 0:
                continue
            else:
                strip = False
        chars.append(c)
    return ''.join(chars)

def is_valid_icao(icao_code):
    return isinstance(icao_code, basestring) and len(icao_code) == 4

def is_valid_iata(iata_code):
    return isinstance(iata_code, basestring) and len(iata_code) == 3

def icao_to_iata(icao_code):
    if is_valid_icao(icao_code):
        airport = models.Airport.get_by_id(icao_code.upper())
        return (airport and airport.iata_code) or None
    return None

def proper_airport_name(name):
    if name.lower().find('airport') == -1:
        return name + ' Airport'
    else:
        return name

def flight_num_from_fa_flight_id(flight_id):
    if flight_id:
        return flight_id.split('-')[0]

def is_trusted_flightaware_host(host_ip):
    host = ipaddr.ip_address(host_ip)
    for network in config['flightaware']['trusted_remote_hosts']:
        trusted_net = ipaddr.ip_network(network)
        if host in trusted_net:
            return True
    return False

###############################################################################
"""Date & Time Utilities"""
###############################################################################

def timestamp(date=None):
  """Returns the passed in date as an integer timestamp of seconds since the epoch."""
  if not date:
    return None
  assert isinstance(date, datetime), 'Expected a datetime object'
  return int(time.mktime(date.timetuple()))

def pretty_time_interval(num_secs, round_days=False):
    num_secs = abs(num_secs)
    days = int(math.floor(num_secs / 86400.0))
    hours = int(math.floor((num_secs - days * 86400.0) / 3600.0))
    minutes = int(math.floor((num_secs - days * 86400.0 - hours * 3600.0) / 60.0))
    pretty = []

    if days > 0:
        if days > 1:
            pretty.append('%d days' % days)
        else:
            pretty.append('1 day')

    if days > 0 and round_days:
        return ' '.join(pretty)

    if hours > 0:
        if hours > 1:
            pretty.append('%d hours' % hours)
        else:
            pretty.append('1 hour')
    if minutes > 0:
        if minutes > 1:
            pretty.append('%d minutes' % minutes)
        else:
            pretty.append('1 minute')
    if not pretty:
        if num_secs > 0:
            if num_secs > 1:
                return '%d seconds' % num_secs
            else:
                return '1 second'
        return 'now'
    else:
        return ' '.join(pretty)

def too_close_or_far(orig_lat, orig_lon, dest_lat, dest_lon):
    approx_dist = distance(orig_lat, orig_lon, dest_lat, dest_lon)
    approx_dist = approx_dist / METERS_IN_MILE # In miles

    if config['close_to_airport'] < approx_dist < config['far_from_airport']:
        return False
    else:
        return True