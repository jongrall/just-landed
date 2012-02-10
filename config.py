import os

config = {}

config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

# Buffer in seconds within which a flight is said to be "on time"
config['on_time_buffer'] = 900

# Num. of miles to the airport below which driving estimate isn't needed
config['close_to_airport'] = 1.0

# Num. of miles to the airport above which driving estimate isn't needed
config['far_from_airport'] = 200.0

# Fields to send on /track
config['track_fields'] = [
    'actualArrivalTime',
    'actualDepartureTime',
    'destination',
    'detailedStatus',
    'estimatedArrivalTime',
    'flightID',
    'flightNumber',
    'heading',
    'lastUpdated',
    'latitude',
    'leaveForAirportTime',
    'leaveForAirportRecommendation',
    'longitude',
    'mapUrl',
    'origin',
    'scheduledDepartureTime',
    'scheduledFlightTime',
    'status',
]


###############################################################################
"""External Services API Keys"""
###############################################################################

# Flight Aware API keys & secrets
config['flightaware'] = {
    'inflight_info_cache_time' : 600,
    'flight_path_cache_time' : 600,
    'flight_info_cache_time' : 10800,
    'username' : 'airportpickupapp',
    'key' : 'e9ff7563419763e3936a2d5412112abc12a54c14',
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
    'airport_info_fields' : [
        'name',
        'location',
        'longitude',
        'latitude',
    ],
    'airline_flight_info_fields' : [
        'terminal_orig',
        'terminal_dest',
        'bag_claim',
    ],
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
    'inflight_info_fields' : [
        'timestamp',
        'longitude',
        'latitude',
        'heading',
        'waypoints',
    ],
    'historical_flight_path_fields' : [
        'latitude',
        'longitude',
    ],
}

# Urban Airship development and production API keys and secrets
config['urbanairship'] = {
  'development': {
    'key': '',
    'secret': '',
  },

  'production': {
    'key': '',
    'secret': '',
  },
}