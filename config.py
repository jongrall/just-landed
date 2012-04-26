#!/usr/bin/python

"""config.py: This module contains all settings for the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import os

# Figure out if we're on local, staging or production environments
from google.appengine.api import app_identity
app_id = app_identity.get_application_id()

###############################################################################
"""Enum Helper Class."""
###############################################################################

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

config = {}

config['app'] = {}

# Figure out if we're on local, staging or production environments
if os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'):
  config['app']['mode'] = 'local'

elif app_id == 'just-landed':
  config['app']['mode'] = 'production'

elif app_id == 'just-landed-staging':
  config['app']['mode'] = 'staging'

def on_production():
  """Returns true if the app is running in production."""
  return config['app']['mode'] == 'production'

def on_staging():
  """Returns true if the app is running on staging."""
  return config['app']['mode'] == 'staging'

def on_development():
  """Returns true if the app is running on the development server."""
  return config['app']['mode'] == 'local'

# Template directory
config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

###############################################################################
"""Flight Tracking Settings."""
###############################################################################

# Buffer within which a flight is said to be "on time". Buffer is in seconds.
config['on_time_buffer'] = 600

# Hours after a flight lands when it becomes "old"
config['flight_old_hours'] = 2

# Time to allow from tires down landing to baggage claim
config['touchdown_to_terminal'] = 600

# Supported flight data sources
config['data_sources'] = Enum([
    'FlightAware',
])

# Fields to send for a Flight in the JSON response
config['flight_fields'] = [
    'actualArrivalTime',
    'actualDepartureTime',
    'aircraftType',
    'destination',
    'detailedStatus',
    'estimatedArrivalTime',
    'flightID',
    'flightNumber',
    'isNight',
    'lastUpdated',
    'leaveForAirportTime',
    'origin',
    'scheduledDepartureTime',
    'scheduledFlightDuration',
    'status',
]

# Fields to send for an Airport in the JSON response
config['airport_fields'] = [
    'bagClaim',
    'city',
    'gate',
    'iataCode',
    'icaoCode',
    'latitude',
    'longitude',
    'terminal',
]

# Supported push notification types
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

# Supported reminder types
config['reminder_types'] = Enum([
   config['push_types'].LEAVE_SOON,
   config['push_types'].LEAVE_NOW,
])

# Possible flight statuses/states
config['flight_states'] = Enum([
    'SCHEDULED',
    'ON_TIME',
    'DELAYED',
    'CANCELED',
    'DIVERTED',
    'LANDED',
    'EARLY',
])

# Cache expiration time for exceptions for so that they don't trigger flood of reports
config['exception_cache_time'] = 3600

# Number of seconds that we should set a 'leave soon' reminder before they should leave for the airport
config['leave_soon_seconds_before'] = 300

# Reminder freshness requirement (don't send reminders that are older than than this)
config['max_reminder_age'] = 120

# Push token freshness requirement (don't register tokens that we've registered as recently as this)
config['max_push_token_age'] = 14400

# Server urls and api credentials that are used to sign requests
if on_development():
    #config['server_url'] = 'http://c-98-207-175-25.hsd1.ca.comcast.net'
    config['server_url'] = 'http://pool-173-63-21-213.nwrknj.fios.verizon.net:8082'
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

elif on_staging():
    config['server_url'] = 'https://just-landed-staging.appspot.com/'
    config['api_credentials'] = {
        'iOS' : {
            'username' : 'iOS-Staging',
            'secret' : '55ca8681039e129bb985991014f61774de31fe1e',
        },
        'Server' : {
            'username' : 'JustLanded-Staging',
            'secret' : 'ecbfb931b4bde2404285923e80a3b3a72d04531a',
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
    """Returns the endpoint url to use for alerts posted by FlightAware."""
    no_ssl_url = config['server_url'].replace('https', 'http') # SSL not yet supported
    return no_ssl_url + '/api/v1/handle_alert'

# FlightAware settings
config['flightaware'] = {
    # Credentials
    'development' : {
        'username' : 'airportpickupapp',
        'key' : 'e1d15375192f9fb75a5c15752e76807226f18e71',
    },

    'staging' : {
        'username' : 'justlandedstaging',
        'key' : 'd414fc0fdd2a2de14705bdca777263b1af4803bd',
    },

    'production' : {
        'username' : 'justlanded',
        'key' : 'e1c5aec44a409bb94742fbba5548946721c7d855',
    },

    # Expected user agent and remote hosts to use to authenticate alert callbacks
    'remote_user_agent': 'FlightXML/2.0 (mc_chan_flightxml)',
    'trusted_remote_hosts' : [
        '216.52.171.64/26',
        '70.42.6.128/25',
        '72.251.200.64/26',
        '89.151.84.224/28',
    ],

    # Cache expiration for flight data from /search
    'flight_lookup_cache_time' : 1800,

    # Cache expiration for fight data from /search that will be used by /track
    'flight_from_lookup_cache_time' : 120,

    # Cache expiration time for flight data from /track
    'flight_cache_time' : 1800,

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
        'gate_dest' : 'destinationGate',
        'ident' : 'flightNumber',
        'location' : 'city',
        'terminal_dest' : 'destinationTerminal',
        'terminal_orig' : 'originTerminal',
        'timestamp' : 'lastUpdated',
    },

    # Fields that should be retained from a /AirportInfo response
    'airport_info_fields' : [
        'name',
        'location',
        'longitude',
        'latitude',
    ],

    # Fields that should be retained from a /AirlineFlightInfo response
    'airline_flight_info_fields' : [
        'terminal_orig',
        'terminal_dest',
        'bag_claim',
        'gate_dest',
    ],

    # Fields that should be retained from a /FlightInfoEx response
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
        'originName',
    ],
}

###############################################################################
"""Driving Time Settings"""
###############################################################################

# Number of miles to the airport below which driving estimate isn't needed
config['close_to_airport'] = 0.5

# Number of miles to the airport above which driving estimate isn't needed
config['far_from_airport'] = 200.0

# Cache expiration for driving route data when using real-time traffic
config['traffic_cache_time'] = 3600

# Bing Maps Credentials
config['bing_maps'] = {
    'key' : 'AjUZ_rECu8dsAMwFNtVRXALPksPaXALYysv-pZ8FSFCWpyhcBkJRb82LEWgECEgZ',
}

###############################################################################
"""Mixpanel API Tokens for Server-Side Event Tracking"""
###############################################################################

config['mixpanel'] = {
    'development': {
        'token' : '8e09212ccbbf47f17b73b4b8a4b7f574',
    },
    'staging' : {
        'token' : '1b4f24a49a9ddc08bf3623c5411f4e0d',
    },
    'production' : {
        'token' : 'd45dd2321bba446a177ed0febc97bf69',
    },
}

###############################################################################
"""Push Notification Settings & API Keys"""
###############################################################################

config['urbanairship'] = {
  'development': {
    'key': '9HBQrA0ISk2WzkJkWAst1g',
    'secret': 'Ok15UGaPRJqWfTUdmcn7sA',
  },

  # Note: staging uses production push cert & creds
  'staging': {
    'key': 'WZR0ix1mRCeTBmIaLUIi8g',
    'secret': 'Z6c6j5gCRpOseuOjcIpeGQ',
  },

  'production': {
    'key': 'WZR0ix1mRCeTBmIaLUIi8g',
    'secret': 'Z6c6j5gCRpOseuOjcIpeGQ',
  },
}


config['stackmob'] = {
    'app_name' : 'just-landed',
    'development': {
        'public_key' : 'df6126cd-906e-4ee7-b09b-d12208646bb5',
        'private_key' : 'fe2a94b0-d732-4639-90d1-c6b80a4a9bc0',
    },

    # Note: staging uses production push cert & creds
    'staging': {
        'public_key' : 'e417f04b-56d2-4fa9-92c5-c0f8fccfac35',
        'private_key' : '0d7b2a49-bc1d-406f-a918-39b4b538afe1',
    },

    'production': {
        'public_key' : 'e417f04b-56d2-4fa9-92c5-c0f8fccfac35',
        'private_key' : '0d7b2a49-bc1d-406f-a918-39b4b538afe1',
    },
}


###############################################################################
"""Campaign Monitor Settings & API Keys"""
###############################################################################

config['campaignmonitor'] = {
    # Credentials
    'key' : '5bd221f998c1e9712f209eed6a7ce5dc',

    # Subscriber list ids used to record mailing list members
    'local' : {
      'subscriber_list_id' : 'e0df0058fb3d482a890ef41ba4adfbeb',
    },

    'staging' : {
      'subscriber_list_id' : '488414d044f6cff3d98fd5d822147599',
    },

    'production' : {
      'subscriber_list_id' : '768e47891d6f304673e16c299fdf1f91',
    },
}

def subscriber_list_id():
    app_mode = config['app']['mode']
    return config['campaignmonitor'][app_mode]['subscriber_list_id']

###############################################################################
"""Twilio Configuration"""
###############################################################################

config['twilio'] = {
    'account_sid' : 'AC6d2c4040d95548b3affc9ab1c0efa1b4',
    'auth_token' : 'dbc0ecf4c9599a90f970a09df4dacdaf',
    'just_landed_phone' : '+14157993553',
}

###############################################################################
"""Google Analytics Accounts"""
###############################################################################

config['google_analytics'] = {
    'local' : {
        'account_id' : 'UA-30604975-3',
    },
    'staging' : {
        'account_id' : 'UA-30604975-2',
    },
    'production' : {
        'account_id' : 'UA-30604975-1',
    }
}

def google_analytics_account():
    app_mode = config['app']['mode']
    return config['google_analytics'][app_mode]['account_id']
