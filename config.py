#!/usr/bin/python

"""config.py: This module contains all settings for the Just Landed app."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os

config = {}

# The directory where templates are found
config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

# Buffer within which a flight is said to be "on time". Buffer is in seconds.
config['on_time_buffer'] = 600

# Hours after a flight lands when it becomes "old"
config['flight_old_hours'] = 2

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
    'leaveForAirportRecommendation',
    'origin',
    'scheduledDepartureTime',
    'scheduledFlightTime',
    'status',
]

###############################################################################
"""Flight Data API Keys & Settings"""
###############################################################################

# FlightAware settings
config['flightaware'] = {
    # Credentials
    'username' : 'airportpickupapp',
    'key' : 'e9ff7563419763e3936a2d5412112abc12a54c14',

    # Caching settings
    'flight_lookup_cache_time' : 10800,
    'flight_cache_time' : 600,

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
        'filed_ete' : 'scheduledFlightTime',
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
    'secret': 'v3FyOzaAS22xZJqHiPyYgw',
  },

  'production': {
    'key': 'WZR0ix1mRCeTBmIaLUIi8g',
    'secret': 'dPA6KgPSTzOVTe1NCzHQRw',
  },
}