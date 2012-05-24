#!/usr/bin/env python

"""utils.py: Utility methods used by the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import logging
import time
from datetime import datetime, timedelta, tzinfo
import re
import math
import hashlib, hmac
import traceback
from zlib import adler32
import re
import string

from google.appengine.api import memcache, capabilities

from config import config, api_secret, on_production
from lib.twilio.rest import TwilioRestClient
from lib import ipaddr, pysolar

EARTH_RADIUS = 6378135
METERS_IN_MILE = 1609.344

ADMIN_PHONES = ['16176425619']
twilio_client = TwilioRestClient(config['twilio']['account_sid'],
                                 config['twilio']['auth_token'])

email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"'
    r')@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$', re.IGNORECASE)

###############################################################################
"""Common Utilities"""
###############################################################################

def text_to_html(text):
    """Reindents text and produces simple HTML output."""
    def reindent(line):
        stripped_line = line.lstrip()
        num_leading_spaces = len(line) - len(stripped_line)
        leading_space = num_leading_spaces * '&nbsp;'
        return leading_space + stripped_line

    lines = [reindent(line).rstrip() for line in text.splitlines()]
    return '<br />'.join(lines)

def sub_dict_strict(somedict, somekeys):
    """Returns a new dictionary containing only the keys specified. If specified
    keys are not present in the dictionary, it will raise a KeyError (strict).

    """
    return dict([ (k, somedict[k]) for k in somekeys])

def sub_dict_select(somedict, somekeys):
    """Returns a new dictionary containing only the keys specified. Keys that are
    not present in the dictionary will not be present in the returned output.

    """
    return dict([ (k, somedict[k]) for k in somekeys if k in somedict])

def map_dict_keys(somedict, mapping):
    """Returns a new dictionary containing all the original keys and values but
    with some keys replaced as specified by the supplied mapping.

    """
    unmapped = dict([ (k, somedict[k]) for k in somedict if k not in mapping])
    mapped = dict([ (mapping[k], somedict[k]) for k in somedict if k in mapping])
    mapped.update(unmapped)
    return mapped

def sorted_dict_values(somedict):
    """Returns the values from a dictionary sorted by their keys."""
    keys = somedict.keys()
    keys.sort()
    return [somedict[k] for k in keys]

def sorted_dict_keys(somedict):
    """Returns a sorted list of the keys found in the supplied dictionary."""
    keys = somedict.keys()
    keys.sort()
    return keys

def sorted_request_params(somedict):
    """Returns an HTTP query string built from the keys and values supplied,
    sorted by the keys.

    """
    keys = sorted_dict_keys(somedict)
    values = sorted_dict_values(somedict)

    parts = []
    for k, v in zip(keys, values):
        parts.append('%s=%s' % (k, v))

    return '&'.join(parts)

def round_coord(lat_or_long, sf=6):
    """Rounds a coordinate, by default to six significant figures."""
    return round(lat_or_long, sf)

def distance(p1lat, p1lon, p2lat, p2lon):
  """Calculates the great circle distance between two points (law of cosines).
  Useful for approximating the straight-line distance between two coordinates
  on the earth's surface.

  Returns:
    The 2D great-circle distance between the two given points, in meters.

  """
  p1lat, p1lon = math.radians(p1lat), math.radians(p1lon)
  p2lat, p2lon = math.radians(p2lat), math.radians(p2lon)
  return EARTH_RADIUS * math.acos(math.sin(p1lat) * math.sin(p2lat) +
      math.cos(p1lat) * math.cos(p2lat) * math.cos(p2lon - p1lon))

def is_int(s):
    """Returns true if the supplied argument is an integer."""
    try:
        int(s)
        return True
    except ValueError:
        return False
    except TypeError:
        return False

def is_float(s):
    """Returns true if the supplied argument is a float."""
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

def is_valid_uuid(uuid, client='iOS'):
    """Tests whether a uuid is valid."""
    if client == 'iOS':
        return isinstance(uuid, basestring) and len(uuid) > 0

def api_query_signature(query_string, client='iOS'):
    """Calculates the expected API query signature from the query string and
    Just Landed client name.

    """
    assert isinstance(query_string, basestring)
    secret = api_secret(client=client)
    return hmac.new(secret, query_string, hashlib.sha1).hexdigest()

def api_request_signature(request, client='iOS'):
    """Calculates the api query signature to add to a request."""
    assert request
    path = request.path
    params = sorted_request_params(request.params)
    to_sign = ''
    if params:
        to_sign = path + '?' + params
    else:
        to_sign = path
    return api_query_signature(to_sign, client=client)

def authenticate_api_request(request, client='iOS'):
    """Authenticates an incoming request as coming from a trusted client by
    checking that it is properly signed.

    """
    assert request
    request_sig = request.headers.get('X-Just-Landed-Signature')
    if not request_sig:
        return False
    return api_request_signature(request, client=client) == request_sig

def is_trusted_flightaware_host(host_ip):
    """Tests whether an IP address belongs to FlightAware."""
    host = ipaddr.ip_address(host_ip)
    for network in config['flightaware']['trusted_remote_hosts']:
        trusted_net = ipaddr.ip_network(network)
        if host in trusted_net:
            return True
    return False

def is_old_fa_flight(raw_fa_flight_data):
    """Tests whether a FlightAware flight is old or not."""
    arrival_timestamp = raw_fa_flight_data['actualarrivaltime']
    departure_timestamp = raw_fa_flight_data['actualdeparturetime']
    hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])

    # Flight has arrived
    if arrival_timestamp and is_int(arrival_timestamp) and arrival_timestamp > 0:
        arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
        return arrival_time < hours_ago

    # Flight was cancelled, see if it is old cancellation
    elif departure_timestamp == -1:
        flight_duration = raw_fa_flight_data['filed_ete'].split(':')
        duration_secs = (int(flight_duration[0]) * 3600) + (int(flight_duration[1]) * 60)
        sched_arrival = datetime.utcfromtimestamp(departure_timestamp + duration_secs)
        return sched_arrival < hours_ago

    # Not arrived, not cancelled => not old
    else:
        return False

###############################################################################
"""Flight Utilities"""
###############################################################################

# Flight number format is xx(a)n(n)(n)(n)(a)
FLIGHT_NUMBER_RE = re.compile('\A[A-Z0-9]{2}[A-Z]{0,1}[0-9]{1,4}[A-Z]{0,1}\Z')

def valid_flight_number(f_num):
    """Tests whether the argument is a valid flight number."""
    f_num = f_num.upper().replace(' ', '')
    matching_nums = FLIGHT_NUMBER_RE.findall(f_num)
    if len(matching_nums):
        return matching_nums[0]
    else:
        return False

def sanitize_flight_number(f_num):
    """Cleans up a flight number - strips leading zeros from flight number, extra
    spaces, uppercases everything.

    """
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
    """Tests whether the argument could be a valid ICAO airport code."""
    return isinstance(icao_code, basestring) and len(icao_code) == 4

def is_valid_iata(iata_code):
    """Tests whether the argument could be a valid IATA airport code."""
    return isinstance(iata_code, basestring) and len(iata_code) == 3

def is_valid_flight_id(flight_id):
    """Forgiving test for non-empty flight id."""
    return isinstance(flight_id, basestring) and len(flight_id)

def is_valid_fa_flight_id(flight_id):
    """Tests whether a flight id is a valid FlightAware flight ID."""
    return is_valid_flight_id(flight_id) and len(flight_id.split('-')) > 1

def is_valid_fa_alert_body(alert_body):
    """Tests whether a FlightAware alert body is valid."""
    if not isinstance(alert_body, dict):
        return False
    event_code = alert_body.get('eventcode')
    flight_data = alert_body.get('flight')
    flight_id = flight_data.get('faFlightID')
    origin = flight_data.get('origin')
    destination = flight_data.get('destination')
    return (is_valid_fa_flight_id(flight_id) and isinstance(event_code, basestring)
        and len(event_code) > 0 and origin and destination)

def proper_airport_name(name):
    """Replaces 'International' with 'Int'l.' in an airport name."""
    name = name.replace("Intl", "Int'l")
    return name.replace("International", "Int'l")

def flight_num_from_fa_flight_id(flight_id):
    """Extracts a flight number from a FlightAware flight id."""
    if flight_id:
        return flight_id.split('-')[0]

def too_close_or_far(orig_lat, orig_lon, dest_lat, dest_lon):
    """Returns True if the supplied coordinates are very close or very far
    from each other. Used to decide whether or not to get driving directions
    to the airport. Too close means the user is probably at the airport. Too far
    means they would probably not drive to the destination airport from their
    location.

    """
    approx_dist = distance(orig_lat, orig_lon, dest_lat, dest_lon)
    approx_dist = approx_dist / METERS_IN_MILE # In miles

    if config['close_to_airport'] < approx_dist < config['far_from_airport']:
        return False
    else:
        return True

def at_airport(user_lat, user_lon, airport_lat, airport_lon):
    """Returns true if the user is at the airport."""
    approx_dist = distance(user_lat, user_lon, airport_lat, airport_lon)
    approx_dist = approx_dist / METERS_IN_MILE # In miles

    if approx_dist <= config['close_to_airport']:
        return True
    else:
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
    """Returns a human readable string describing the amount of time represented
    by the input number of seconds.

    Fields:
    - `round_days` : If True, anything interval more than a day is simply
    returned as a whole number of days (no hours, minutes etc.)

    """
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

def leave_now_time(flight, driving_time):
    """Calculates the time that a user should leave given the estimated
    arrival time of the flight, and the driving time from their current location
    to the destination airport.
    """
    # Different touchdown to terminal arrival for international flights
    is_international = flight.origin.country != flight.destination.country
    touchdown_to_terminal = ((is_international and config['touchdown_to_terminal_intl']) or
                            config['touchdown_to_terminal'])

    return datetime.utcfromtimestamp(
        touchdown_to_terminal + flight.estimated_arrival_time - driving_time)

def leave_soon_time(flight, driving_time):
    """Calculates the leave soon reminder time given the estimated arrival time
    of the flight, and the driving time from their current location to the
    destination airport.
    """
    leave_soon_interval = config['leave_soon_seconds_before']
    leave_now = timestamp(leave_now_time(flight, driving_time))
    return datetime.utcfromtimestamp(leave_now - leave_soon_interval)

###############################################################################
"""Night / Day Utilities"""
###############################################################################

def sun_altitude_degrees(latitude, longitude, when=None, altitude_in_feet=0):
    """Calculates the angle of the sun relative to the horizon given location,
    time, and altitude.

    """
    if not when:
        when = datetime.utcnow()
    assert isinstance(when, datetime)
    elevation_meters = altitude_in_feet * 0.3048
    pressure_millibars = 101325 * math.pow((1 - 2.25577e-5 * elevation_meters), 5.25588) / 100.0
    return pysolar.GetAltitude(latitude, longitude, when,
                                elevation=elevation_meters,
                                temperature_celsius=25,
                                pressure_millibars=pressure_millibars)

def is_dark(latitude, longitude, when=None, altitude_in_feet=0):
    """Returns true if it is dark at the given location, time and
    elevation (in meters). Dark is defined as the sun being below the horizon.

    """
    return sun_altitude_degrees(latitude,
                                longitude,
                                when=when,
                                altitude_in_feet=altitude_in_feet) < 0.0

def is_twilight(latitude, longitude, when=None, altitude_in_feet=0):
    """Returns true if it is twilight at the given location, time and
    elevation (in meters). Twilight is defined as the sun being below the horizon
    but by no more than 6 degrees (civilian twilight).
    """
    sun_altitude = sun_altitude_degrees(latitude,
                                longitude,
                                when=when,
                                altitude_in_feet=altitude_in_feet)
    return -6.0 <= sun_altitude <= 0.0

def is_dark_now(latitude, longitude, altitude_in_feet=30000):
    """Returns True if it is currently dark at the given location and altitude."""
    return is_dark(latitude, longitude, altitude_in_feet=altitude_in_feet)

###############################################################################
"""Email Utilities"""
###############################################################################

def valid_email(email):
  """Returns True if the email address is valid, False otherwise."""
  if email and re.match(email_re, string.lower(email)):
    return True
  return False

###############################################################################
"""SMS Utilities"""
###############################################################################

def send_sms(to, body, from_phone=config['twilio']['just_landed_phone']):
    """Sends an sms message.

    Arguments:
    - `to` : The phone number to send to.
    - `body` : The body of the text message.
    - `from_phone` : The phone number to send from. Defaults to Just Landed #.

    """
    assert to, 'No to phone number'
    assert from_phone, 'No from phone number'
    assert len(body) <= 160, 'SMS messages must be at most 160 characters'
    twilio_client.sms.messages.create(to=to,
                                      from_=from_phone,
                                      body=body)

def sms_alert_admin(message):
    """Send an SMS alert to the admins. Intended purpose: report 500 errors."""
    for phone in ADMIN_PHONES:
        send_sms(to=phone, body=message)

def sms_report_exception(exception):
    """Alert admins to 500 errors via SMS at most once every 30 mins for
    identical exceptions.

    """
    traceback_as_string = traceback.format_exc()
    exception_memcache_key = 'exception_%s' % adler32(traceback_as_string)

    if on_production() and not memcache.get(exception_memcache_key):
        memcache.set(exception_memcache_key, exception, config['exception_cache_time'])
        sms_alert_admin("[%s] Just Landed %s\n%s" %
                        (datetime.now(Pacific).strftime('%T'),
                        type(exception).__name__,
                        exception.message))

###############################################################################
"""GAE Capabilities Utilities"""
###############################################################################

def url_fetch_enabled():
    return capabilities.CapabilitySet('urlfetch').is_enabled()

def datastore_reads_enabled():
    return capabilities.CapabilitySet('datastore_v3').is_enabled()

def datastore_writes_enabled():
    return capabilities.CapabilitySet('datastore_v3', capabilities=['write']).is_enabled()

def mail_enabled():
    return capabilities.CapabilitySet('mail').is_enabled()

def memcache_enabled():
    return capabilities.CapabilitySet('memcache').is_enabled()

def taskqueue_enabled():
    return capabilities.CapabilitySet('taskqueue').is_enabled()

def disabled_services():
    system_status = {
        'URLFETCH' : url_fetch_enabled(),
        'DATASTORE READS' : datastore_reads_enabled(),
        'DATASTORE WRITES' : datastore_writes_enabled(),
        'MAIL' : mail_enabled(),
        'MEMCACHE' : memcache_enabled(),
        'TASKQUEUE' : taskqueue_enabled(),
    }
    return [k for k in system_status.keys() if not system_status[k]]

def try_reporting_outage(disabled_services):
    """Given a list of disabled App Engine services, tries to send an SMS alert
    to the admin advising them of which services are down.

    """
    assert disabled_services

    # Without urlfetch we're hosed, and without memcache we'll potentially send a flood of sms
    if url_fetch_enabled() and memcache_enabled():
        outage = ['Just Landed App Outage\n',
                   ': DISABLED\n'.join(disabled_services),
                   ': DISABLED']
        outage_message = ''.join(outage)
        outage_cache_key = 'outage_%s' % adler32(outage_message)

        # Only report exceptions we haven't recently seen
        if not memcache.get(outage_cache_key):
            memcache.set(outage_cache_key, outage_message, config['exception_cache_time'])
            sms_alert_admin(outage_message)