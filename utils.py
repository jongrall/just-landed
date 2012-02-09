import time
import logging
from datetime import tzinfo, timedelta, datetime
import re

import models

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

###############################################################################
"""Flight Utilities"""
###############################################################################

# Flight number format is xx(a)n(n)(n)(n)(a)
FLIGHT_NUMBER_RE = re.compile('\A[A-Z0-9]{2}[A-Z]{0,1}[0-9]{1,4}[A-Z]{0,1}\Z')

# Static map urls
map_base_url = 'http://maps.googleapis.com/maps/api/staticmap'
dest_icon_url = 'http://www.getjustlanded.com/static/images/dest_icon.png'
origin_icon_url = 'http://www.getjustlanded.com/static/images/orig_icon.png'

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

def map_url(flight_info):
    if flight_info and isinstance(flight_info, dict):
        params = dict(
            size='600x400',
            maptype='terrain',
            markers=[
                'icon:%s%%26shadow:false|%f,%f' % (
                  origin_icon_url,
                  flight_info['origin']['latitude'],
                  flight_info['origin']['longitude'],
                ),
                'icon:%s%%26shadow:false|%f,%f' % (
                  dest_icon_url,
                  flight_info['destination']['latitude'],
                  flight_info['destination']['longitude'],
                ),
            ],
            sensor='false',
        )

        # Add the marker for the plane's location
        flight_latitude = 0.0
        flight_longitude = 0.0
        flight_icon_url = 'http://www.getjustlanded.com/static/images/flight0.png'

        if is_in_flight(flight_info):
            flight_latitude = flight_info['latitude']
            flight_longitude = flight_info['longitude']
            flight_icon_url = ('http://www.getjustlanded.com/static/images/flight%s.png'
                                % int(1.5 * round(flight_info['heading']/1.5, -1)))
        elif has_landed(flight_info):
            flight_latitude = flight_info['destination']['latitude']
            flight_longitude = flight_info['destination']['longitude']
            flight_icon_url = 'http://www.getjustlanded.com/static/images/flight180.png'
        else:
            flight_latitude = flight_info['origin']['latitude']
            flight_longitude = flight_info['origin']['longitude']

        params['markers'] = [
            'icon:%s%%26shadow:false%%7C%f,%f' % (
            flight_icon_url,
            flight_latitude,
            flight_longitude,)] + params['markers']

        # Draw the path if the plane is in flight
        if is_in_flight(flight_info):
            params['path'] = 'color:0x0000ff|weight:1|%s' % flight_info['waypoints']

        qry_parts = []

        for k in params.keys():
            v = params[k]
            if isinstance(v, list):
                for elt in v:
                    qry_parts.append('%s=%s' % (k, elt))
            else:
                qry_parts.append('%s=%s' % (k, v))

        qry = '&'.join(qry_parts)
        return '%s?%s' % (map_base_url, qry)


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

def is_in_flight(flight):
    return (flight['actualDepartureTime'] > 0 and
            flight['actualArrivalTime'] == 0)

def has_landed(flight):
    return flight['actualArrivalTime'] != 0