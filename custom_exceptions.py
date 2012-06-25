#!/usr/bin/env python

"""custom_exceptions.py: defines all the exceptions thrown by Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

###############################################################################
"""Reporting Exceptions"""
###############################################################################

class MixpanelUnavailableError(Exception):
    def __init__(self):
        self.message = 'Mixpanel API is unavailable.'
        self.code = 503 # Service unavailable

class ReportEventFailedException(Exception):
    def __init__(self, status_code=403, event_name=''):
        self.message = 'Unable to report event: %s' % event_name
        self.code = status_code

###############################################################################
"""Flight Data Source Exceptions"""
###############################################################################

class FlightAwareUnavailableError(Exception):
    def __init__(self):
        self.message = 'FlightAware API is unavailable.'
        self.code = 503 # Service unavailable

class InvalidFlightNumberException(Exception):
    def __init__(self, flight_number=''):
        self.message = 'Invalid flight number: %s' % flight_number
        self.code = 400 # Bad request

class FlightNotFoundException(Exception):
    def __init__(self, flight=''):
        self.message = 'Flight not found: %s' % flight
        self.code = 404 # Not found

class TerminalsUnknownException(Exception):
    def __init__(self, flight_id=''):
        self.message = 'Terminal info not found: %s' % flight_id
        self.code = 404 # Not found

class AirportNotFoundException(Exception):
    def __init__(self, airport='', flight_num=''):
        self.message = 'Airport not found: %s for flight %s' % (airport, flight_num)
        self.code = 404 # Not found

class OldFlightException(Exception):
    def __init__(self, flight_number='', flight_id=''):
        self.message = 'Old flight: %s %s' % (flight_number, flight_id)
        self.code = 410 # Gone

class UnableToSetAlertException(Exception):
    def __init__(self, reason=''):
        self.message = 'Unable to set alert: %s' % reason
        self.code = 403 # Gone

class UnableToSetEndpointException(Exception):
    def __init__(self, endpoint=''):
        self.message = 'Unable to set endpoint: %s' % endpoint
        self.code = 400 # Bad request

class UnableToGetAlertsException(Exception):
    def __init__(self):
        self.message = 'Unable to get alerts from the datasource.'
        self.code = 400 # Bad request

class UnableToDeleteAlertException(Exception):
    def __init__(self, alert_id):
        self.message = 'Unable to delete alert %s from the datasource.' % alert_id
        self.code = 400 # Bad request

###############################################################################
"""Driving Time Data Source Exceptions"""
###############################################################################

class DrivingTimeUnavailableError(Exception):
    def __init__(self):
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
        self.message = "Can't get driving time (%f,%f) to (%f,%f): \n %s" % (
                        orig_lat, orig_lon, dest_lat, dest_lon, data)
        self.code = 404 # Not found

class DrivingAPIQuotaException(Exception):
    def __init__(self):
        self.message = 'Exceeded driving API quota.'
        self.code = 403 # Forbidden

class DrivingTimeUnauthorizedException(Exception):
    def __init__(self):
        self.message = 'Driving time request unauthorized.'
        self.code = 401 # Unauthorized

class NoDrivingRouteException(Exception):
    def __init__(self, status_code, orig_lat, orig_lon, dest_lat, dest_lon):
        self.message = "Can't get driving time (%f,%f) to (%f,%f)" % (
                        orig_lat, orig_lon, dest_lat, dest_lon)
        self.code = status_code

###############################################################################
"""Push Notification Exceptions"""
###############################################################################

class PushNotificationsUnavailableError(Exception):
    def __init__(self):
        self.message = 'Push notifications are unavailable.'
        self.code = 503 # Service unavailable

class PushNotificationsUnauthorizedError(Exception):
    def __init__(self):
        self.message = 'Push notification unauthorized.'
        self.code = 401 # Unauthorized

class PushNotificationsUnknownError(Exception):
    def __init__(self, status_code=500, message=''):
        self.message = message
        self.code = status_code

class UrbanAirshipUnavailableError(PushNotificationsUnavailableError):
    def __init__(self):
        super(UrbanAirshipUnavailableError, self).__init__()
        self.message = 'Urban Airship is unavailable.'

class StackMobUnavailableError(PushNotificationsUnavailableError):
    def __init__(self):
        super(StackMobUnavailableError, self).__init__()
        self.message = 'StackMob is unavailable.'

###############################################################################
"""Mailing List Exceptions"""
###############################################################################

class CampaignMonitorUnavailableError(Exception):
    def __init__(self):
        self.message = 'Mailing list is unavailable.'
        self.code = 503 # Service unavailable

class CampaignMonitorUnauthorizedError(Exception):
    def __init__(self):
        self.message = 'Mailing list unauthorized.'
        self.code = 401 # Unauthorized