#!/usr/bin/python

"""datasource_exceptions.py: This module defines all the exceptions thrown by
the various data sources used by the Just Landed app.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

###############################################################################
"""Flight Data Source Exceptions"""
###############################################################################

class InvalidFlightNumberException (Exception):
    def __init__(self, flight_number=''):
        self.message = 'Invalid flight number: %s' % flight_number
        self.code = 400 # Bad request

class FlightNotFoundException (Exception):
    def __init__(self, flight=''):
        self.message = 'Flight not found: %s' % flight
        self.code = 404 # Not found

class TerminalsUnknownException(Exception):
    def __init__(self, flight_id=''):
        self.message = 'Terminal info not found: %s' % flight_id
        self.code = 404 # Not found

class AirportNotFoundException (Exception):
    def __init__(self, airport=''):
        self.message = 'Airport not found: %s' % airport
        self.code = 404 # Not found

class OldFlightException (Exception):
    def __init__(self, flight_number='', flight_id=''):
        self.message = 'Old flight: %s %s' % (flight_number, flight_id)
        self.code = 410 # Gone

###############################################################################
"""Flight Alert Exceptions"""
###############################################################################

class UnableToSetAlertException (Exception):
    def __init__(self, reason=''):
        self.message = 'Unable to set alert: %s' % reason
        self.code = 403 # Gone

class UnableToSetEndpointException (Exception):
    def __init__(self, endpoint=''):
        self.message = 'Unable to set endpoint: %s' % endpoint
        self.code = 400 # Bad request

class UnableToGetAlertsException (Exception):
    def __init__(self):
        self.message = 'Unable to get alerts from the datasource.'
        self.code = 400 # Bad request

class UnableToDeleteAlertException (Exception):
    def __init__(self, alert_id):
        self.message = 'Unable to delete alert %s from the datasource.' % alert_id
        self.code = 400 # Bad request

###############################################################################
"""Driving Time Data Source Exceptions"""
###############################################################################

class UnknownDrivingTimeException (Exception):
    def __init__(self, orig_lat, orig_lon, dest_lat, dest_lon):
        self.message = "Can't get driving distance (%f,%f) to (%f,%f)" % (
                        orig_lat, orig_lon, dest_lat, dest_lon)
        self.code = 404 # Not found

class DrivingAPIQuotaException (Exception):
    def __init__(self):
        self.message = 'Exceeded driving API quota.'
        self.code = 403 # Forbidden

class DrivingDistanceDeniedException (Exception):
    def __init__(self, orig_lat, orig_lon, dest_lat, dest_lon):
        self.message = 'Driving distance request denied (%f,%f) to (%f,%f)' % (
                        orig_lat, orig_lon, dest_lat, dest_lon)
        self.code = 403 # Forbidden