#!/usr/bin/python

"""notifications.py: Utilities for sending push notifications via Urban Airship."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os
import pickle
import logging

from google.appengine.api import taskqueue
from google.appengine.ext import webapp

from lib import urbanairship

from config import config, on_local
import utils

def get_airship():
    """Returns an Urban Airship instance initialized with the correct production
    or development credentials.

    """
    if not on_local():
        ua_creds = config['urbanairship']['production']
    else:
        ua_creds = config['urbanairship']['development']

    return urbanairship.Airship(**ua_creds)

debug_push = True
_UA = get_airship()
push_types = config['push_types']
FLIGHT_STATES = config['flight_states']

###############################################################################
"""Helper Methods for Deferring Notification Work"""
###############################################################################

def _defer(method, *args, **kwargs):
    """Adds a method to the push notification queue for later execution."""
    payload = pickle.dumps((method, args, kwargs))
    task = taskqueue.Task(payload=payload)
    taskqueue.Queue('mobile-push').add(task)


def register_token(device_token):
    """Registers an iOS push notification device token with Urban Airship.

    Arguments:
    - `device_token` : The device notification token to register.
    """
    assert device_token, 'No device token'
    _defer('register', device_token)


def deregister_token(device_token):
    assert device_token, 'No device token'
    _defer('deregister', device_token)


def push(cls, payload, **kwargs):
    """Convenience method for pushing notifications to iOS devices using a
    taskqueue.

    Arguments:
    - `payload` : The payload to push to the device(s).
    - `device_tokens` : The push notification device tokens to send to.
    """
    _defer('push', payload, **kwargs)

###############################################################################
"""Request Handler for Push Notification Taskqueue Callback"""
###############################################################################

class PushWorker(webapp.RequestHandler):
    """Taskqueue worker for sending our push notifications."""
    def post(self):
        # Find out what we were supposed to do
        method, args, kwds = pickle.loads(self.request.body)

        # Debug push
        if debug_push:
            if method == 'register':
                token = args[0]
                logging.info('REGISTERING DEVICE TOKEN: %s' % token)
            elif method == 'deregister':
                token = args[0]
                logging.info('DE-REGISTERING DEVICE TOKEN: %s' % token)
            elif method == 'push':
                token = kwds.get('device_tokens')[0]
                # FIXME: Assumes iOS
                data = args[0]
                message = data['aps']['alert']
                logging.info('PUSHING MESSAGE TO %s: \n%s' % (token, message))

        # Check that urban airship supports the method we want to call
        func = getattr(_UA, method, None)
        if func:
            # Call the function with the supplied arguments
            func(*args, **kwds)

###############################################################################
"""Convenience Functions for sending push notifications to a user about
specific types of events."""
###############################################################################

class _FlightAlert(object):
    """Defines an object to represent a push notification. Not intended to be
    used directly, but rather subclassed."""
    def __init__(self, device_token, flight, user_flight_num):
        assert device_token
        assert flight
        assert utils.valid_flight_number(user_flight_num)
        self._device_token = device_token
        self._flight = flight
        self._user_flight_num = user_flight_num
        self._origin_city_or_airport = (flight.origin.city or
                                       flight.origin.best_name)
        self._destination_city_or_airport = (flight.destination.city or
                                            flight.destination.best_name)

    def push(self):
        data =  self.payload
        # Don't send empty messages
        if data['aps']['alert']:
            _defer('push', data, device_tokens=[self._device_token])

    @property
    def payload(self):
        return {
          'notification_type': self.notification_type,
          'aps': {
            'alert': self.message,
            'sound': self.notification_sound,
          },
        }

    @property
    def message(self):
        """Returns the message body of the push notification. Subclasses are
        expected to implement this method and return a short string to be
        displayed to the user."""
        pass

    @property
    def notification_type(self):
        """Returns the notification type of the push notification.

        Subclasses are expected to implement this method and return a
        NotificationType."""
        pass

    @property
    def notification_sound(self):
        """Returns the name of the sound that should play when the alert
        arrives on the receiving device."""
        return 'announcement.caf'


class FlightDivertedAlert(_FlightAlert):
    """A push notification indicating a flight has been diverted."""
    @property
    def message(self):
        return 'Flight %s from %s has been diverted to another airport.' % (
            self._user_flight_num,
            self._origin_city_or_airport)

    @property
    def notification_type(self):
        return push_types.DIVERTED


class FlightCanceledAlert(_FlightAlert):
    """A push notification indicating a flight has been canceled."""
    @property
    def message(self):
        return 'Flight %s from %s has been canceled.' % (
            self._user_flight_num,
            self._origin_city_or_airport)

    @property
    def notification_type(self):
        return push_types.CANCELED


class FlightDepartedAlert(_FlightAlert):
    """A push notification indicating a flight has departed."""
    @property
    def message(self):
        return 'Flight %s to %s just took off from %s.' % (
                self._user_flight_num,
                self._destination_city_or_airport,
                self._origin_city_or_airport)

    @property
    def notification_type(self):
        return push_types.DEPARTED

    @property
    def notification_sound(self):
        return 'takeoff.caf'


class FlightArrivedAlert(_FlightAlert):
    """A push notification indicating a flight has arrived."""
    @property
    def message(self):
        # Show terminal info if we have it
        terminal = self._flight.destination.terminal
        if terminal:
            if terminal == 'I':
                return 'Flight %s from %s just landed at %s international terminal.' % (
                        self._user_flight_num,
                        self._origin_city_or_airport,
                        self._flight.destination.best_name)
            else:
                return 'Flight %s from %s just landed at %s terminal %s.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    self._flight.destination.best_name,
                    terminal)
        else:
            return 'Flight %s from %s just landed at %s.' % (
                self._user_flight_num,
                self._origin_city_or_airport,
                self._flight.destination.best_name)

    @property
    def notification_type(self):
        return push_types.ARRIVED

    @property
    def notification_sound(self):
        return 'landing.caf'


class FlightPlanChangeAlert(_FlightAlert):
    """A push notification indicating a flight plan has changed."""
    @property
    def message(self):
        flight_status = self._flight.status
        time_diff = self._flight.est_arrival_diff_from_schedule
        pretty_time_diff = utils.pretty_time_interval(time_diff, round_days=True)

        if flight_status == FLIGHT_STATES.DELAYED:
            return 'Flight %s from %s is %s late.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    pretty_time_diff)
        elif flight_status == FLIGHT_STATES.EARLY:
            return 'Flight %s from %s is %s early.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    pretty_time_diff)
        elif flight_status == FLIGHT_STATES.ON_TIME:
            # FIXME: Maybe this isn't needed
            return 'Flight %s from %s is now on time.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport)

    @property
    def notification_type(self):
        return push_types.CHANGED


class FlightFiledAlert(FlightPlanChangeAlert):
    """A push notification indicating a flight plan has been filed."""
    @property
    def notification_type(self):
        return push_types.FILED