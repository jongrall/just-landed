class FlightNotFoundException (Exception):
    def __init__(self, message="Flight not found."):
        self.message = message
        self.code = 404

class InvalidFlightNumber (Exception):
    def __init__(self, message="Invalid flight number."):
        self.message = message
        self.code = 400