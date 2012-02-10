class FlightNotFoundException (Exception):
    def __init__(self, flight=''):
        self.message = 'Flight not found: %s' % flight
        self.code = 404 # Not found

class TerminalsUnknownException(Exception):
    def __init__(self, flight_id=''):
        self.message = 'Terminal info not found: %s' % flight_id
        self.code = 404 # Not found

class MissingFlightPathException(Exception):
    def __init__(self, flight_id=''):
        self.message = 'Flight path not found: %s' % flight_id
        self.code = 404 # Not found

class AirportNotFoundException (Exception):
    def __init__(self, airport=''):
        self.message = 'Airport not found: %s' % airport
        self.code = 404 # Not found

class InvalidFlightNumber (Exception):
    def __init__(self, flight_number=''):
        self.message = 'Invalid flight number: %s' % flight_number
        self.code = 400 # Bad request

class MissingInflightInfoException (Exception):
    def __init__(self, flight_number=''):
        self.message = "Can't get in-flight info: %s" % flight_number
        self.code = 404 # Not found

class OldFlightException (Exception):
    def __init__(self, flight_number='', flight_id=''):
        self.message = 'Old flight: %s %s' % (flight_number, flight_id)
        self.code = 410 # Gone