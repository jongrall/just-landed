import os

config = {}

config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

###############################################################################
"""External Services API Keys"""
###############################################################################

# Fields to send on /track
config['track_fields'] = [
    'actualArrivalTime',
    'actualDepartureTime',
    'destination',
    'estimatedArrivalTime',
    'flightID',
    'flightNumber',
    'heading',
    'lastUpdated',
    'latitude',
    'longitude',
    'map_url',
    'origin',
    'scheduledDepartureTime',
    'scheduledFlightTime',
    'waypoints'
]

# Flight Aware API keys & secrets
config['flightaware'] = {
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