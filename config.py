#!/usr/bin/python

"""config.py: This module contains all settings for the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os

config = {}

class Enum(set):
  """Solution for Enums

  Usage:
  Animals = Enum(["DOG", "CAT", "Horse"])
  print Animals.DOG
  """
  def __getattr__(self, name):
    if name in self:
      return name
    raise AttributeError

###############################################################################
"""App Configuration."""
###############################################################################

config['app'] = {}

# Figure out if we're on local, staging or production environments
if os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'):
  config['app']['mode'] = 'local'
else:
  config['app']['mode'] = 'production'

# The directory where templates are found
config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

# Buffer within which a flight is said to be "on time". Buffer is in seconds.
config['on_time_buffer'] = 600

# Hours after a flight lands when it becomes "old"
config['flight_old_hours'] = 3

# Fields to send for a flight
config['flight_fields'] = [
    'actualArrivalTime',
    'actualDepartureTime',
    'destination',
    'detailedStatus',
    'estimatedArrivalTime',
    'flightID',
    'flightNumber',
    'lastUpdated',
    'leaveForAirportTime',
    'origin',
    'scheduledDepartureTime',
    'scheduledFlightDuration',
    'status',
]

# Supported push notification preference names.
config['push_types'] = Enum([
    'FILED',
    'DIVERTED',
    'CANCELED',
    'DEPARTED',
    'ARRIVED',
    'CHANGED',
])

config['flight_states'] = Enum([
    'SCHEDULED',
    'ON_TIME',
    'DELAYED',
    'CANCELED',
    'DIVERTED',
    'LANDED',
    'EARLY'
])

def on_production():
  """Returns true if the app is running in production"""
  return config['app']['mode'] == 'production'

def on_local():
  """Returns true if the app is running on the local devserver."""
  return config['app']['mode'] == 'local'

if on_local():
    config['server_url'] = 'http://c-98-207-175-25.hsd1.ca.comcast.net'
else:
    config['server_url'] = 'http://just-landed.appspot.com/'

###############################################################################
"""Flight Data API Keys & Settings"""
###############################################################################

def fa_alert_url():
    return config['server_url'] + '/api/v1/handle_alert'

# FlightAware settings
config['flightaware'] = {
    # Credentials
    'username' : 'airportpickupapp',
    'keys' : {
        'development' : 'e9ff7563419763e3936a2d5412112abc12a54c14',
        'production' : '390ef2061c6f5bd814ef0ef3ce68efa19f3c12b2',
    },

    'remote_user_agent': 'FlightXML/2.0 (mc_chan_flightxml)',
    'trusted_remote_hosts' : [
        '216.52.171.64/26',
        '70.42.6.128/25',
        '72.251.200.64/26',
        '89.151.84.224/28',
    ],

    # Caching settings
    'flight_lookup_cache_time' : 10800,
    'flight_cache_time' : 600,

    # Alert endpoint
    'alert_endpoint' : fa_alert_url(),

    # Mapping of FlightAware API response keys to Just Landed API response keys
    'key_mapping' : {
        'actualarrivaltime' : 'actualArrivalTime',
        'actualdeparturetime' : 'actualDepartureTime',
        'aircrafttype' : 'aircraftType',
        'bag_claim' : 'bagClaim',
        'estimatedarrivaltime' : 'estimatedArrivalTime',
        'faFlightID' : 'flightID',
        'filed_airspeed_kts' : 'filedAirspeed',
        'filed_airspeed_mach' : 'filedAirspeedMach',
        'filed_altitude' : 'filedAltitude',
        'filed_departuretime' : 'scheduledDepartureTime',
        'filed_ete' : 'scheduledFlightDuration',
        'filed_time' : 'lastUpdated',
        'ident' : 'flightNumber',
        'location' : 'city',
        'terminal_dest' : 'destinationTerminal',
        'terminal_orig' : 'originTerminal',
        'timestamp' : 'lastUpdated',
    },

    # Fields that should be retained from an AirportInfo response
    'airport_info_fields' : [
        'name',
        'location',
        'longitude',
        'latitude',
    ],

    # Fields that should be retained from an AirlineFlightInfo response
    'airline_flight_info_fields' : [
        'terminal_orig',
        'terminal_dest',
        'bag_claim',
    ],

    # Fields that should be retained from a FlightInfoEx response
    'flight_info_fields' : [
        'actualarrivaltime',
        'actualdeparturetime',
        'destination',
        'destinationCity',
        'destinationName',
        'estimatedarrivaltime',
        'diverted',
        'faFlightID',
        'filed_departuretime',
        'filed_ete',
        'filed_time',
        'ident',
        'origin',
        'originCity',
        'originName'
    ],
}

###############################################################################
"""Driving Time Settings"""
###############################################################################

# Number of miles to the airport below which driving estimate isn't needed
config['close_to_airport'] = 1.0

# Number of miles to the airport above which driving estimate isn't needed
config['far_from_airport'] = 200.0

###############################################################################
"""Push Notification Settings & API Keys"""
###############################################################################

# Urban Airship development and production API keys and secrets for Just Landed
config['urbanairship'] = {
  'development': {
    'key': '9HBQrA0ISk2WzkJkWAst1g',
    'secret': 'Ok15UGaPRJqWfTUdmcn7sA',
  },

  'production': {
    'key': 'WZR0ix1mRCeTBmIaLUIi8g',
    'secret': 'Z6c6j5gCRpOseuOjcIpeGQ',
  },
}