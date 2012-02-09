import time
import logging
from datetime import tzinfo, timedelta, datetime
import re

import models

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
    f_num = f_num.upper()
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

def map_dict_keys(somedict, mapping):
    unmapped = dict([ (k, somedict[k]) for k in somedict if k not in mapping])
    mapped = dict([ (mapping[k], somedict[k]) for k in somedict if k in mapping])
    mapped.update(unmapped)
    return mapped

###############################################################################
"""Flight Utilities"""
###############################################################################

def icao_to_iata(icao_code):
    if icao_code and len(icao_code) == 4:
        airport = models.Airport.get_by_id(icao_code.upper())
        return (airport and airport.iata_code) or None
    return None

###############################################################################
"""Date & Time Utilities"""
###############################################################################

def timestamp(date=None):
  """Returns the passed in date as an integer timestamp of seconds since the epoch."""

  if not date:
    return None

  assert isinstance(date, datetime), 'Expected a datetime object'
  return int(time.mktime(date.timetuple()))

def is_old_flight(flight):
    arrival_timestamp = flight['actualArrivalTime']
    arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
    est_arrival_time = datetime.utcfromtimestamp(flight['estimatedArrivalTime'])
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    return ((arrival_timestamp > 0 and arrival_time < hour_ago) or
            est_arrival_time < hour_ago)