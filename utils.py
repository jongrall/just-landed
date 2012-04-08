#!/usr/bin/python

"""utils.py: Utility methods used by the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import time
import logging
from datetime import datetime, timedelta, tzinfo
import re
import math
import hashlib, hmac
import traceback
from zlib import adler32

from google.appengine.api import memcache

from lib.twilio.rest import TwilioRestClient

from config import config, api_secret, on_production
from lib import ipaddr

EARTH_RADIUS = 6378135
METERS_IN_MILE = 1609.344

ADMIN_PHONES = ['16176425619']
twilio_client = TwilioRestClient(config['twilio']['account_sid'],
                                 config['twilio']['auth_token'])

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

def sorted_dict_values(somedict):
    keys = somedict.keys()
    keys.sort()
    return [somedict[k] for k in keys]

def sorted_dict_keys(somedict):
    keys = somedict.keys()
    keys.sort()
    return keys

def sorted_request_params(somedict):
    keys = sorted_dict_keys(somedict)
    values = sorted_dict_values(somedict)

    parts = []
    for k, v in zip(keys, values):
        parts.append('%s=%s' % (k, v))

    return '&'.join(parts)

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

def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
    except TypeError:
        return False

def is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
    except TypeError:
        return False

###############################################################################
"""Security Utilities"""
###############################################################################

def api_query_signature(query_string, client='iOS'):
    assert isinstance(query_string, basestring)
    secret = api_secret(client=client)
    return hmac.new(secret, query_string, hashlib.sha1).hexdigest()

def api_request_signature(request, client='iOS'):
    assert request
    # Build string to sign
    path = request.path
    params = sorted_request_params(request.params)
    to_sign = ''
    if params:
        to_sign = path + '?' + params
    else:
        to_sign = path
    return api_query_signature(to_sign, client)

def authenticate_api_request(request, client='iOS'):
    assert request
    request_sig = request.headers.get('X-Just-Landed-Signature')

    if not request_sig:
        return False
    return api_request_signature(request, client=client) == request_sig

def is_trusted_flightaware_host(host_ip):
    host = ipaddr.ip_address(host_ip)
    for network in config['flightaware']['trusted_remote_hosts']:
        trusted_net = ipaddr.ip_network(network)
        if host in trusted_net:
            return True
    return False

def is_old_fa_flight(raw_fa_flight_data):
    arrival_timestamp = raw_fa_flight_data['actualarrivaltime']
    departure_timestamp = raw_fa_flight_data['actualdeparturetime']
    hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])

    if arrival_timestamp and is_int(arrival_timestamp) and arrival_timestamp > 0:
        arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
        return arrival_time < hours_ago
    elif departure_timestamp == -1: # Flight was cancelled, see if it is old cancellation
        flight_duration = raw_fa_flight_data['filed_ete'].split(':')
        duration_secs = (int(flight_duration[0]) * 3600) + (int(flight_duration[1]) * 60)
        sched_arrival = datetime.utcfromtimestamp(departure_timestamp + duration_secs)
        return sched_arrival < hours_ago
    else:
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

def proper_airport_name(name):
    if name.lower().find('airport') == -1:
        return name + ' Airport'
    else:
        return name

def flight_num_from_fa_flight_id(flight_id):
    if flight_id:
        return flight_id.split('-')[0]

def too_close_or_far(orig_lat, orig_lon, dest_lat, dest_lon):
    approx_dist = distance(orig_lat, orig_lon, dest_lat, dest_lon)
    approx_dist = approx_dist / METERS_IN_MILE # In miles

    if config['close_to_airport'] < approx_dist < config['far_from_airport']:
        return False
    else:
        return True

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

ZERO = timedelta(0)
HOUR = timedelta(hours=1)

class UTC(tzinfo):
    """UTC"""

    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO

utc = UTC()

# A complete implementation of current DST rules for major US time zones.
def first_sunday_on_or_after(dt):
    days_to_go = 6 - dt.weekday()
    if days_to_go:
        dt += timedelta(days_to_go)
    return dt

# In the US, DST starts at 2am (standard time) on the first Sunday in April.
DSTSTART = datetime(1, 4, 1, 2)
# and ends at 2am (DST time; 1am standard time) on the last Sunday of Oct.
# which is the first Sunday on or after Oct 25.
DSTEND = datetime(1, 10, 25, 1)


class USTimeZone(tzinfo):

    def __init__(self, hours, reprname, stdname, dstname):
        self.stdoffset = timedelta(hours=hours)
        self.reprname = reprname
        self.stdname = stdname
        self.dstname = dstname

    def __repr__(self):
        return self.reprname

    def tzname(self, dt):
        if self.dst(dt):
            return self.dstname
        else:
            return self.stdname

    def utcoffset(self, dt):
        return self.stdoffset + self.dst(dt)

    def dst(self, dt):
        if dt is None or dt.tzinfo is None:
            # An exception may be sensible here, in one or both cases.
            # It depends on how you want to treat them.  The default
            # fromutc() implementation (called by the default astimezone()
            # implementation) passes a datetime with dt.tzinfo is self.
            return ZERO
        assert dt.tzinfo is self

        # Find first Sunday in April & the last in October.
        start = first_sunday_on_or_after(DSTSTART.replace(year=dt.year))
        end = first_sunday_on_or_after(DSTEND.replace(year=dt.year))

        # Can't compare naive to aware objects, so strip the timezone from
        # dt first.
        if start <= dt.replace(tzinfo=None) < end:
            return HOUR
        else:
            return ZERO

Eastern  = USTimeZone(-5, "Eastern",  "EST", "EDT")
Central  = USTimeZone(-6, "Central",  "CST", "CDT")
Mountain = USTimeZone(-7, "Mountain", "MST", "MDT")
Pacific  = USTimeZone(-8, "Pacific",  "PST", "PDT")

def leave_now_time(est_arrival_time, driving_time):
    # -60 fudge factor for cron delay
    touchdown_to_terminal = config['touchdown_to_terminal']
    return datetime.utcfromtimestamp(
        touchdown_to_terminal + est_arrival_time - driving_time - 60)

def leave_soon_time(est_arrival_time, driving_time):
    leave_soon_interval = config['leave_soon_seconds_before']
    leave_now = timestamp(leave_now_time(est_arrival_time, driving_time))
    return datetime.utcfromtimestamp(leave_now - leave_soon_interval)

###############################################################################
"""SMS Utilities"""
###############################################################################

def send_sms(to, body, from_phone=config['twilio']['just_landed_phone']):
    assert to, 'No to phone number'
    assert from_phone, 'No from phone number'
    assert len(body) <= 160, 'SMS messages must be at most 160 characters'
    twilio_client.sms.messages.create(to=to,
                                      from_=from_phone,
                                      body=body)

def sms_alert_admin(message):
    """Send an SMS alert to the admins - intended purpose: report 500 errors."""
    for phone in ADMIN_PHONES:
        send_sms(to=phone, body=message)

def sms_report_exception(exception):
    """Alert admins to 500 errors via SMS at most once every 30 mins for
    identical exceptions."""
    traceback_as_string = traceback.format_exc()
    exception_memcache_key = 'exception_%s' % adler32(traceback_as_string)

    if on_production() and not memcache.get(exception_memcache_key):
        memcache.set(exception_memcache_key, exception, time=config['exception_cache_time'])
        sms_alert_admin("[%s] Just Landed %s: %s" %
                        (datetime.now(Pacific).strftime('%T'),
                        type(exception).__name__,
                        exception.message))

def report_outage(disabled_services):
    assert disabled_services
    outage = ['Just Landed App Outage\n',
               ': DISABLED\n'.join(disabled_services),
               ': DISABLED']
    outage_message = ''.join(outage)
    outage_cache_key = 'outage_%s' % adler32(outage_message)

    if not memcache.get(outage_cache_key):
        memcache.set(outage_cache_key, outage_message, time=config['exception_cache_time'])
        sms_alert_admin(outage_message)