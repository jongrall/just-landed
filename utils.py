"""utils.py: Utility methods used by the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import pickle
import time
from datetime import datetime, timedelta, tzinfo
import re
import math
import hashlib, hmac
import traceback
from zlib import adler32

from google.appengine.api import memcache, taskqueue, capabilities
from google.appengine.ext import webapp

from config import config, api_secret, on_production
from lib.twilio.rest import TwilioRestClient
from lib import ipaddr, pysolar
from data.airline_codes import airlines_iata_to_icao

EARTH_RADIUS = 6378135
METERS_IN_MILE = 1609.344

twilio_client = TwilioRestClient(config['twilio']['account_sid'],
                                 config['twilio']['auth_token'])

email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"'
    r')@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$', re.IGNORECASE)

###############################################################################
# Common Utilities
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

def dictinvert(somedict):
    """Inverts a dictionary, turning values into keys. Handles duplicate values
    by creating a list of values from repeated keys."""
    inv = {}
    for k, v in somedict.iteritems():
        keys = inv.setdefault(v, [])
        keys.append(k)
    return inv

def chunks(alist, chunk_size):
    """Splits a list into n-sized chunks."""
    for i in xrange(0, len(alist), chunk_size):
        yield alist[i:i+chunk_size]

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

def sanitize_int(s, default=None):
    if is_int(s):
        return int(s)
    else:
        return default

def sanitize_float(s, default=None):
    if is_float(s):
        return float(s)
    else:
        return default

def sanitize_bool(s, default=True):
    if is_int(s):
        return bool(int(s))
    else:
        return default

def sanitize_positive_int(s, default=None):
    if is_int(s):
        return abs(int(s))
    else:
        return default

###############################################################################
# Security Utilities
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

def fa_flight_ete_to_duration(filed_ete):
    flight_duration = filed_ete.split(':')
    if len(flight_duration) < 2: # Safeguard against bad data
        raise ValueError()
    return (int(flight_duration[0] or 0) * 3600) + (int(flight_duration[1] or 0) * 60)

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
        duration_secs = fa_flight_ete_to_duration(raw_fa_flight_data['filed_ete'])
        sched_arrival = datetime.utcfromtimestamp(departure_timestamp + duration_secs)
        return sched_arrival < hours_ago

    # Not arrived, not cancelled => not old
    else:
        return False

###############################################################################
# Flight Utilities
###############################################################################

# Flight number format is xx(a)n(n)(n)(n)(a), with at least 1 letter required in the airline code
FLIGHT_NUMBER_RE = re.compile("\A[A-Z][0-9][A-Z]{0,1}[0-9]{1,4}[A-Z]{0,1}\Z|"
                                "\A[0-9][A-Z]{1,2}[0-9]{1,4}[A-Z]{0,1}\Z|"
                                "\A[A-Z]{2,3}[0-9]{1,4}[A-Z]{0,1}\Z")
AIRLINE_CODE_RE = re.compile('\A[A-Z][0-9][A-Z]{0,1}|\A[0-9][A-Z]{1,2}|\A[A-Z]{2,3}')
IATA_CODE_RE = re.compile('\A[A-Z0-9]{3}\Z')
ICAO_CODE_RE = re.compile('\A[A-Z0-9]{4}\Z')
AIRLINE_IATA_CODE_RE = re.compile('\A[A-Z0-9]{2}\Z')
AIRLINE_ICAO_CODE_RE = re.compile('\A[A-Z0-9]{3}\Z')

def sanitize_flight_number(f_num):
    """Cleans up a flight number - strips leading zeros from flight number, extra
    spaces, uppercases everything, performs some IATA to ICAO code translation.

    """
    f_num = f_num.upper().replace(' ', '')
    chars = []
    strip = True
    for char in f_num:
        if strip and char.isdigit():
            if int(char) == 0:
                continue
            else:
                strip = False
        chars.append(char)
    return ''.join(chars)

def valid_flight_number(f_num):
    """Tests whether the argument is a valid flight number."""
    f_num_san = sanitize_flight_number(f_num)
    matching_nums = FLIGHT_NUMBER_RE.findall(f_num_san)
    if len(matching_nums):
        return matching_nums[0]
    else:
        return False

def is_valid_icao(icao_code):
    """Tests whether the argument could be a valid ICAO airport code."""
    return isinstance(icao_code, basestring) and ICAO_CODE_RE.match(icao_code)

def is_valid_iata(iata_code):
    """Tests whether the argument could be a valid IATA airport code."""
    return isinstance(iata_code, basestring) and IATA_CODE_RE.match(iata_code)

def is_valid_airline_icao(icao_code):
    """Tests whether the argument could be a valid ICAO airline code."""
    return isinstance(icao_code, basestring) and AIRLINE_ICAO_CODE_RE.match(icao_code)

def is_valid_airline_iata(iata_code):
    """Tests whether the argument could be a valid IATA airline code."""
    return isinstance(iata_code, basestring) and AIRLINE_IATA_CODE_RE.match(iata_code)

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
    event_code = alert_body.get('eventcode', None)
    alert_id = alert_body.get('alert_id', None)
    flight_id = alert_body.get('flight', {}).get('faFlightID', None)
    return (is_valid_fa_flight_id(flight_id) and
            isinstance(event_code, basestring) and
            alert_id is not None)

def proper_airport_name(name):
    """Replaces 'International' with 'Int'l.' in an airport name."""
    name = name.replace("Intl", "Int'l")
    return name.replace("International", "Int'l")

def translate_flight_number_to_icao(f_num):
    if valid_flight_number(f_num):
        f_num_san = sanitize_flight_number(f_num)
        matched_code = AIRLINE_CODE_RE.match(f_num_san)
        if matched_code:
            matching_code = matched_code.group(0)
            translated_code = airlines_iata_to_icao.get(matching_code)
            if translated_code:
                new_f_num = translated_code + f_num_san[len(matching_code):]
                if valid_flight_number(new_f_num):
                    return new_f_num
                else:
                    return None
    return None

def split_flight_number(f_num, prefer_icao=True):
    if valid_flight_number(f_num):
        f_num_san = sanitize_flight_number(f_num)
        matched_code = AIRLINE_CODE_RE.match(f_num_san)
        if matched_code:
            airline_code = matched_code.group(0)
            f_num_digits = f_num_san[len(airline_code):]
            # If we prefer ICAO codes, try to convert to ICAO
            if prefer_icao and is_valid_airline_iata(airline_code):
                icao_result = airlines_iata_to_icao.get(airline_code)
                if is_valid_airline_icao(icao_result):
                    airline_code = icao_result
            # Ensure the flight number is still valid
            if airline_code and valid_flight_number(airline_code + f_num_digits):
                return airline_code, f_num_digits
    return None, None

def flight_num_from_fa_flight_id(flight_id):
    """Extracts a flight number from a FlightAware flight id."""
    if is_valid_fa_flight_id(flight_id):
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
# Date & Time Utilities
###############################################################################

def timestamp(date=None):
    """Returns the passed in date as an integer timestamp of seconds since the epoch."""
    if not date:
        return None
    assert isinstance(date, datetime), 'Expected a datetime object'
    return int(time.mktime(date.timetuple()))

ZERO = timedelta(0)
HOUR = timedelta(hours=1)

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
        super(USTimeZone, self).__init__()
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

def leave_soon_time(flight, driving_time, leave_soon_interval):
    """Calculates the leave soon reminder time given the estimated arrival time
    of the flight, the driving time from their current location to the
    destination airport, and how long they want to be notified before the time to leave.
    """
    leave_now = timestamp(leave_now_time(flight, driving_time))
    return datetime.utcfromtimestamp(leave_now - leave_soon_interval)



###############################################################################
# Night / Day Utilities
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
# Email Utilities
###############################################################################

def valid_email(email):
    """Returns True if the email address is valid, False otherwise."""
    return bool(email and re.match(email_re, email.lower()))

###############################################################################
# SMS Utilities
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
    assert len(body) <= 160, 'SMS message too long %d/160 characters: %s' % (len(body), body)
    twilio_client.sms.messages.create(to=to,
                                      from_=from_phone,
                                      body=body)

def sms_alert_admin(message):
    """Send an SMS alert to the admins. Intended purpose: report 500 errors."""
    if on_production():
        tasks = []
        for phone in config['admin_phones']:
            tasks.append(taskqueue.Task(params={
                'to' : phone,
                'message' : message,
            }))
        if tasks:
            taskqueue.Queue('send-sms').add(tasks)

def sms_report_exception(exception):
    """Alert admins to 500 errors via SMS at most once every 30 mins for
    identical exceptions.

    """
    traceback_as_string = traceback.format_exc()
    exception_memcache_key = 'exception_%s' % adler32(traceback_as_string)

    if not memcache.get(exception_memcache_key):
        memcache.set(exception_memcache_key, exception, config['exception_cache_time'])
        sms_alert_admin("[%s] Just Landed %s\n%s" %
                        (datetime.now(Pacific).strftime('%T'),
                        type(exception).__name__,
                        exception.message))

class SMSWorker(webapp.RequestHandler):
    """Deferred sending of SMS messages."""
    def post(self):
        # Disable retries
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        to = self.request.params.get('to')
        msg = self.request.params.get('message')
        if to and msg:
            send_sms(to, msg)

###############################################################################
# GAE Capabilities Utilities
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

def try_reporting_outage(affected_services):
    """Given a list of disabled App Engine services, tries to send an SMS alert
    to the admin advising them of which services are down.

    """
    assert affected_services

    # Without urlfetch we're hosed, and without memcache we'll potentially send a flood of sms
    if url_fetch_enabled() and memcache_enabled():
        outage = ['Just Landed App Outage\n',
                   ': DISABLED\n'.join(affected_services),
                   ': DISABLED']
        outage_message = ''.join(outage)
        outage_cache_key = 'outage_%s' % adler32(outage_message)

        # Only report exceptions we haven't recently seen
        if not memcache.get(outage_cache_key):
            memcache.set(outage_cache_key, outage_message, config['exception_cache_time'])
            sms_alert_admin(outage_message)

###############################################################################
# Outage Detection & Reporting
###############################################################################

def error_rate(error_dates, sample_endpoint=None):
    """Calculate the error rate within a list of errors represented by a list
    of dates.

    Keywords:
    'sample_endpoint' : Use this date as the endpoint of the sample window to determine
    error rate. If not specified, uses the last error date provided.

    """
    for d in error_dates:
        assert isinstance(d, datetime)
    error_dates = sorted(error_dates)
    startpoint = error_dates[0]
    endpoint = (isinstance(sample_endpoint, datetime) and sample_endpoint) or error_dates[-1]
    sample_duration = abs(endpoint - startpoint).total_seconds()
    return len(error_dates) / sample_duration


def is_error_rate_high(error_dates, sample_endpoint=None):
    """Returns true if the error rate, represented by a list of dates, is too high."""
    assert isinstance(error_dates, list)
    num_errors = len(error_dates)
    if (num_errors >= config['min_outage_errors'] and
        error_rate(error_dates, sample_endpoint=sample_endpoint) > config['high_error_rate']):
        return True
    else:
        return False

def service_error_cache_key(exception):
    return 'service_error_' + type(exception).__name__

def report_service_error(exception):
    if exception:
        taskqueue.Queue('report-outage').add(taskqueue.Task(params={
            'exception' : pickle.dumps(exception)
        }))

class ReportOutageWorker(webapp.RequestHandler):
    """Deferred reporting of outages."""
    def post(self):
        # Disable retries
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        exception = pickle.loads(str(self.request.params.get('exception')))
        error_cache_key = service_error_cache_key(exception)
        sms = False
        rate = 0.0
        now = datetime.utcnow()
        client = memcache.Client()
        retries = 0

        while retries < 20: # Retry loop for CAS
            report = client.gets(error_cache_key)
            if report is None:
                # 1st report of this service error
                report = {
                    'alert_sent' : False,
                    'outage_start_date' : None,
                    'error_dates' : [now]
                }
                client.set(error_cache_key, report) # Required for CAS to work
                break
            else:
                # Update existing report of recent errors for this service
                error_dates = report['error_dates']
                assert isinstance(error_dates, list)
                # Keep the last min_outage_errors
                error_dates.append(now)
                error_dates = sorted(error_dates)
                report['error_dates'] = error_dates[-config['min_outage_errors']:]

                # Figure out if we need to send an sms notification to admins
                sms = not report['alert_sent'] and is_error_rate_high(report['error_dates'])
                if sms:
                    rate = error_rate(report['error_dates'])
                    report['alert_sent'] = True # We will be sending the alert shortly
                    report['outage_start_date'] = now # Use now as the outage start date

                if client.cas(error_cache_key, report):
                    break # Write was successful
                else:
                    retries += 1

        if sms:
            sms_alert_admin("[%s] %s\nError rate: %.2f/min" %
                            (datetime.now(Pacific).strftime('%T'),
                            exception.message,
                            rate * 60.0))
