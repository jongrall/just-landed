"""custom_exceptions.py: defines all the exceptions thrown by Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Little Details LLC"
__email__ = "jon@littledetails.net"

###############################################################################
# Reporting Exceptions
###############################################################################

class ReportingServiceUnavailableError(Exception):
    def __init__(self):
        super(ReportingServiceUnavailableError, self).__init__()
        self.message = 'Reporting service is unavailable.'
        self.code = 503 # Service unavailable

class MixpanelUnavailableError(ReportingServiceUnavailableError):
    def __init__(self):
        super(MixpanelUnavailableError, self).__init__()
        self.message = 'Mixpanel API is unavailable.'

class GoogleAnalyticsUnavailableError(ReportingServiceUnavailableError):
    def __init__(self):
        super(GoogleAnalyticsUnavailableError, self).__init__()
        self.message = 'Google Analytics is unavailable.'

class ReportEventFailedException(Exception):
    def __init__(self, status_code=403, event_name=''):
        super(ReportEventFailedException, self).__init__()
        self.message = 'Unable to report event: %s' % event_name
        self.code = status_code

class EventClassNotFoundException(Exception):
    def __init__(self, class_name=''):
        super(EventClassNotFoundException, self).__init__()
        self.message = 'Unable to report event with class: %s' % class_name
        self.code = 400 # Bad request

class UnableToCreateUniqueEventKey(Exception):
    def __init__(self, class_name=''):
        super(UnableToCreateUniqueEventKey, self).__init__()
        self.message = 'Unable to build key for unique %s event.' % class_name
        self.code = 500 # Server error

###############################################################################
# Flight Data Source Exceptions
###############################################################################

class FlightDataUnavailableError(Exception):
    def __init__(self):
        super(FlightDataUnavailableError, self).__init__()
        self.message = 'Flight datasource is unavailable.'
        self.code = 503 # Service unavailable

class FlightAwareUnavailableError(FlightDataUnavailableError):
    def __init__(self):
        super(FlightAwareUnavailableError, self).__init__()
        self.message = 'FlightAware API is unavailable.'

class InvalidFlightNumberException(Exception):
    def __init__(self, flight_number=''):
        super(InvalidFlightNumberException, self).__init__()
        self.message = 'Invalid flight number: %s' % flight_number
        self.code = 400 # Bad request

class FlightNotFoundException(Exception):
    def __init__(self, flight=''):
        super(FlightNotFoundException, self).__init__()
        self.message = 'Flight not found: %s' % flight
        self.code = 404 # Not found

class CurrentFlightNotFoundException(FlightNotFoundException):
    def __init__(self, flight=''):
        super(CurrentFlightNotFoundException, self).__init__()
        self.message = 'No recent %s flights found.' % flight

class TerminalsUnknownException(Exception):
    def __init__(self, flight_id=''):
        super(TerminalsUnknownException, self).__init__()
        self.message = 'Terminal info not found: %s' % flight_id
        self.code = 404 # Not found

class AirportNotFoundException(Exception):
    def __init__(self, airport='', flight_num=''):
        super(AirportNotFoundException, self).__init__()
        self.message = 'Airport not found: %s for flight %s' % (airport, flight_num)
        self.code = 404 # Not found

class FlightDurationUnknown(Exception):
    def __init__(self, flight_id='', ete=''):
        super(FlightDurationUnknown, self).__init__()
        self.message = 'Unknown duration %s for flight %s' % (ete, flight_id)
        self.code = 404 # Not found

class InvalidAlertCallbackException(Exception):
    def __init__(self):
        super(InvalidAlertCallbackException, self).__init__()
        self.message = 'Invalid alert callback.'
        self.code = 400 # Bad request

class OldFlightException(Exception):
    def __init__(self, flight_number='', flight_id=''):
        super(OldFlightException, self).__init__()
        self.message = 'Old flight: %s %s' % (flight_number, flight_id)
        self.code = 410 # Gone

class UnableToSetAlertException(Exception):
    def __init__(self, reason=''):
        super(UnableToSetAlertException, self).__init__()
        self.message = 'Unable to set alert: %s' % reason
        self.code = 403 # Gone

class UnableToSetEndpointException(Exception):
    def __init__(self, endpoint=''):
        super(UnableToSetEndpointException, self).__init__()
        self.message = 'Unable to set endpoint: %s' % endpoint
        self.code = 400 # Bad request

class UnableToGetAlertsException(Exception):
    def __init__(self):
        super(UnableToGetAlertsException, self).__init__()
        self.message = 'Unable to get alerts from the datasource.'
        self.code = 400 # Bad request

class UnableToDeleteAlertException(Exception):
    def __init__(self, alert_id):
        super(UnableToDeleteAlertException, self).__init__()
        self.message = 'Unable to delete alert %s from the datasource.' % alert_id
        self.code = 400 # Bad request

###############################################################################
# Model Exceptions
###############################################################################

class OrphanedFlightError(Exception):
    def __init__(self, flight_id=''):
        super(OrphanedFlightError, self).__init__()
        self.message = 'Orphaned flight: %s' % flight_id
        self.code = 500 # Server error

###############################################################################
# Driving Time Data Source Exceptions
###############################################################################

class DrivingTimeUnavailableError(Exception):
    def __init__(self):
        super(DrivingTimeUnavailableError, self).__init__()
        self.message = 'Driving time is unavailable.'
        self.code = 503 # Service unavailable

class BingMapsUnavailableError(DrivingTimeUnavailableError):
    def __init__(self):
        super(BingMapsUnavailableError, self).__init__()
        self.message = 'Bing Maps API is unavailable.'

class GoogleDistanceAPIUnavailableError(DrivingTimeUnavailableError):
    def __init__(self):
        super(GoogleDistanceAPIUnavailableError, self).__init__()
        self.message = 'Google distance API is unavailable.'

class MalformedDrivingDataException(Exception):
    def __init__(self, orig_lat, orig_lon, dest_lat, dest_lon, data):
        super(MalformedDrivingDataException, self).__init__()
        self.message = "Can't get driving time (%f,%f) to (%f,%f): \n %s" % (
                        orig_lat, orig_lon, dest_lat, dest_lon, data)
        self.code = 404 # Not found

class DrivingAPIQuotaException(Exception):
    def __init__(self):
        super(DrivingAPIQuotaException, self).__init__()
        self.message = 'Exceeded driving API quota.'
        self.code = 403 # Forbidden

class DrivingTimeUnauthorizedException(Exception):
    def __init__(self):
        super(DrivingTimeUnauthorizedException, self).__init__()
        self.message = 'Driving time request unauthorized.'
        self.code = 401 # Unauthorized

class NoDrivingRouteException(Exception):
    def __init__(self, status_code, orig_lat, orig_lon, dest_lat, dest_lon):
        super(NoDrivingRouteException, self).__init__()
        self.message = "Can't get driving time (%f,%f) to (%f,%f)" % (
                        orig_lat, orig_lon, dest_lat, dest_lon)
        self.code = status_code

###############################################################################
# Push Notification Exceptions
###############################################################################

class PushNotificationsUnavailableError(Exception):
    def __init__(self):
        super(PushNotificationsUnavailableError, self).__init__()
        self.message = 'Push notifications are unavailable.'
        self.code = 503 # Service unavailable

class UrbanAirshipUnavailableError(PushNotificationsUnavailableError):
    def __init__(self):
        super(UrbanAirshipUnavailableError, self).__init__()
        self.message = 'Urban Airship is unavailable.'

class PushBotsUnavailableError(PushNotificationsUnavailableError):
    def __init__(self):
        super(PushBotsUnavailableError, self).__init__()
        self.message = 'PushBots is unavailable.'

class PushNotificationsUnauthorizedError(Exception):
    def __init__(self):
        super(PushNotificationsUnauthorizedError, self).__init__()
        self.message = 'Push notification unauthorized.'
        self.code = 401 # Unauthorized

class UrbanAirshipUnauthorizedError(PushNotificationsUnauthorizedError):
    def __init__(self):
        super(UrbanAirshipUnauthorizedError, self).__init__()
        self.message = 'Urban Airship request is unauthorized.'

class PushBotsUnauthorizedError(PushNotificationsUnauthorizedError):
    def __init__(self):
        super(PushBotsUnauthorizedError, self).__init__()
        self.message = 'PushBots request is unauthorized.'

class PushNotificationsUnknownError(Exception):
    def __init__(self, status_code=500, message=''):
        super(PushNotificationsUnknownError, self).__init__()
        self.message = message
        self.code = status_code

class UrbanAirshipUnknownError(PushNotificationsUnknownError):
    def __init__(self, status_code=500, message=''):
        super(UrbanAirshipUnknownError, self).__init__(status_code, message)

class PushBotsUnknownError(PushNotificationsUnknownError):
    def __init__(self, status_code=500, message=''):
        super(PushBotsUnknownError, self).__init__(status_code, message)