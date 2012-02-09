import os

config = {}

config['template_dir'] = os.path.join(os.path.dirname(__file__), 'templates')

###############################################################################
"""External Services API Keys"""
###############################################################################

# Flight Aware API keys & secrets
config['flightaware'] = {
    'username' : 'airportpickupapp',
    'key' : 'e9ff7563419763e3936a2d5412112abc12a54c14',
    'key_mapping' : {
        'actualarrivaltime' : 'actualArrivalTime',
        'actualdeparturetime' : 'actualDepartureTime',
        'aircrafttype' : 'aircraftType',
        'estimatedarrivaltime' : 'estimatedArrivalTime',
        'faFlightID' : 'flightID',
        'filed_airspeed_kts' : 'filedAirspeed',
        'filed_airspeed_mach' : 'filedAirspeedMach',
        'filed_altitude' : 'filedAltitude',
        'filed_departuretime' : 'scheduledDepartureTime',
        'filed_ete' : 'scheduledFlightTime',
        'filed_time' : 'lastUpdated',
        'ident' : 'flightNumber',
    },
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