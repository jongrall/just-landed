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

# Flight datasources
config['data_sources'] = Enum([
    'FlightAware',
])

# Fields to send for a flight
config['flight_fields'] = [
    'actualArrivalTime',
    'actualDepartureTime',
    'aircraftType',
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
    'LEAVE_SOON',
    'LEAVE_NOW',
])

config['reminder_types'] = Enum([
   config['push_types'].LEAVE_SOON,
   config['push_types'].LEAVE_NOW,
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

# Number of seconds that we should set a 'leave soon' reminder before they should leave for the airport
config['leave_soon_seconds_before'] = 300

# Reminder freshness requirement (don't send reminders that are older than than this)
config['max_reminder_age'] = 120

def on_production():
  """Returns true if the app is running in production"""
  return config['app']['mode'] == 'production'

def on_local():
  """Returns true if the app is running on the local devserver."""
  return config['app']['mode'] == 'local'

if on_local():
    config['server_url'] = 'http://c-98-207-175-25.hsd1.ca.comcast.net'
    config['api_credentials'] = {
        'iOS' : {
            'username' : 'iOS-Development',
            'secret' : 'd90816f7e6ea93001a2aa62cd8dd8f0e830a93d1',
        },
        'Server' : {
            'username' : 'JustLanded-Development',
            'secret' : '8f131377dba9f8c0fe7a9ae9a865842acd153fb0',
        },
    }
else:
    config['server_url'] = 'https://just-landed.appspot.com/'
    config['api_credentials'] = {
        'iOS' : {
            'username' : 'iOS-Production',
            'secret' : '4399d9ce77acf522799543f13c926c0a41e2ea3f',
        },
        'Server' : {
            'username' : 'JustLanded-Production',
            'secret' : '270a0d95cc6c6a6d48b6e69117e053226fe7f5b5',
        },
    }

def api_secret(client='iOS'):
    """Returns the api secret for a given Just Landed client."""
    return config['api_credentials'][client]['secret']

###############################################################################
"""Flight Data API Keys & Settings"""
###############################################################################

def fa_alert_url():
    no_ssl_url = config['server_url'].replace('https', 'http') # SSL not yet supported
    return no_ssl_url + '/api/v1/handle_alert'

# FlightAware settings
config['flightaware'] = {
    # Credentials
    'development' : {
        'username' : 'airportpickupapp',
        'key' : 'e9ff7563419763e3936a2d5412112abc12a54c14',
    },

    'production' : {
        'username' : 'justlanded',
        'key' : '45f9a85894cf77112df78289ba594013393108d8',
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
        'aircrafttype',
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

# Amount of time to cache driving time for when using real-time traffic
config['traffic_cache_time'] = 3600

# Bing Maps Credentials
config['bing_maps'] = {
    'key' : 'AjUZ_rECu8dsAMwFNtVRXALPksPaXALYysv-pZ8FSFCWpyhcBkJRb82LEWgECEgZ',
}

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