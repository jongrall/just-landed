#!/usr/bin/env python

"""notifications.py: Utilities for sending push notifications via Urban Airship."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import logging
import os
import pickle
from datetime import datetime

from google.appengine.api import memcache, taskqueue

from lib import urbanairship
from lib import stackmob

from custom_exceptions import *
from main import BaseHandler
from config import config, on_development, on_staging
import utils

# Enable to log informational messages about push notification activity
debug_push = on_development() and False

push_types = config['push_types']
FLIGHT_STATES = config['flight_states']

###############################################################################
"""Push Notification Services"""
###############################################################################

class PushNotificationService(object):
    """Class that defines a generic push notification service interface."""

    def register_token(self, device_token):
        """Registers a device token with the push service."""
        pass

    def deregister_token(self, device_token):
        """De-registers a device token from the service."""

    def push(self, payload, device_tokens=None):
        """Pushes a notification payload using the push service to the supplied
        device tokens."""
        pass


class UrbanAirshipService(PushNotificationService):
    """Concrete implementation of a Push Notification Service using Urban
    Airship.

    """
    def __init__(self):
        if on_development():
            ua_creds = config['urbanairship']['development']
        elif on_staging():
            ua_creds = config['urbanairship']['staging']
        else:
            ua_creds = config['urbanairship']['production']

        self._UA = urbanairship.Airship(**ua_creds)

    def call_ua_func(self, func, *args, **kwargs):
        # Reliability: intercept & translate UA exceptions
        try:
            func(*args, **kwargs)
        except urbanairship.Unauthorized:
            raise PushNotificationsUnauthorizedError()
        except urbanairship.AirshipFailure as e:
            raise PushNotificationsUnknownError(status_code=e.args[0], message=e.args[1])
        except Exception:
            raise UrbanAirshipUnavailableError()

    def register_token(self, device_token):
        self.call_ua_func(self._UA.register, device_token)

    def deregister_token(self, device_token):
        self.call_ua_func(self._UA.deregister, device_token)

    def push(self, payload, device_tokens=None):
        self.call_ua_func(self._UA.push, payload, device_tokens=device_tokens)


class StackMobService(PushNotificationService):
    """Concrete implementation of a PushNotificationService using StackMob."""

    def __init__(self):
        if on_development():
            creds = config['stackmob']['development']
        elif on_staging():
            creds = config['stackmob']['staging']
        else:
            creds = config['stackmob']['production']

        kwargs = {
            'production' : not on_development(),
        }
        kwargs.update(creds)
        self._SM = stackmob.StackMob(**kwargs)

    def call_sm_func(self, func, *args, **kwargs):
        # Reliability: intercept & translate exceptions
        try:
            func(*args, **kwargs)
        except stackmob.Unauthorized:
            raise PushNotificationsUnauthorizedError()
        except stackmob.StackMobFailure as e:
            raise PushNotificationsUnknownError(status_code=e.code, message='StackMob Failure')
        except Exception as e:
            raise StackMobUnavailableError()

    def register_token(self, device_token):
        self.call_sm_func(self._SM.register, device_token)

    def deregister_token(self, device_token):
        self.call_sm_func(self._SM.deregister, device_token)

    def push(self, payload, device_tokens=None):
        self.call_sm_func(self._SM.push, payload, device_tokens=device_tokens)

###############################################################################
"""Helper Methods for Deferring Notification Work"""
###############################################################################

def _defer(method, *args, **kwargs):
    """Adds a method to the push notification queue for later execution.
    Supports transactional notification enqueueing using the _transactional kwd.

    """
    transactional = kwargs.get('_transactional') or False
    payload = pickle.dumps((method, args, kwargs))
    task = taskqueue.Task(payload=payload)
    taskqueue.Queue('mobile-push').add(task, transactional=transactional)


def register_token(device_token, **kwargs):
    """Defers registering an iOS push notification device token for sending push
    notifications to that device in the future.

    Arguments:
    - `device_token` : The device notification token to register.

    """
    assert device_token, 'No device token'
    force = kwargs.get('force') or False

    # Optimization: only re-register if we haven't done so recently
    if not memcache.get(device_token) or force:
        _defer('register_token', device_token, **kwargs)


def deregister_token(device_token, **kwargs):
    """Defers deregistering a device token from the push notification service."""
    assert device_token, 'No device token'
    _defer('deregister_token', device_token, **kwargs)


def push(cls, payload, **kwargs):
    """Convenience method for pushing notifications to iOS devices using a
    taskqueue.

    Arguments:
    - `payload` : The payload to push to the device(s).
    - `device_tokens` : The push notification device tokens to send to.
    """
    assert payload
    _defer('push', payload, **kwargs)

###############################################################################
"""Request Handler for Push Notification Taskqueue Callback"""
###############################################################################

# Reliability: UrbanAirship is the primary push service, StackMob is a fallback
push_service = UrbanAirshipService()
fallback_push_service = StackMobService()

class PushWorker(BaseHandler):
    """Taskqueue worker for sending push notifications."""
    def post(self):
        # Reliability: disable retries, a flood of duplicate push notifications
        # being sent to users would be disastrous.
        # TODO: Implement fully transactional, retry-able notification tasks.
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        # Find out what we were supposed to do
        method, args, kwds = pickle.loads(self.request.body)
        if '_transactional' in kwds.keys():
            del(kwds['_transactional'])
        if 'force' in kwds.keys():
            del(kwds['force'])

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

        # Reliability: check that the push service supports the method we want to call
        func = getattr(push_service, method, None)

        if func:
            try:
                func(*args, **kwds)

                if method == 'register_token':
                    push_token = args[0]
                    # Optimization: cache push token registration so it doesn't happen every time
                    if not memcache.set(push_token, True, config['max_push_token_age']):
                        logging.error('Unable to cache push token: %s' % push_token)

            # Reliability: don't allow push notification exceptions to propagate
            except Exception as e:
                # Reliability: call the fallback service for pushing messages only
                if method == 'push':
                    utils.sms_report_exception(e)
                    logging.exception(e)

                    # Register and push to the fallback service (the device is
                    # probably not previously registered)
                    fallback_push_service.register_token(kwds['device_tokens'][0])
                    fallback_push_service.push(*args, **kwds)
                else:
                    raise # Re-raise only for methods other than push


###############################################################################
"""Convenience Functions for sending push notifications to a user about
specific types of events."""
###############################################################################

class _Alert(object):
    """Represents a push notification. Not intended to be used directly, but
    rather subclassed."""
    def __init__(self, device_token):
        assert device_token
        self._device_token = device_token

    def push(self, **kwargs):
        """Push the alert (adds to taskqueue for processing)."""
        data =  self.payload
        kwargs['device_tokens'] = [self._device_token]
        # Don't send empty messages
        if data['aps']['alert']:
            _defer('push', data, **kwargs)

    @property
    def payload(self):
        """Returns a valid iOS push notification payload for the alert."""
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
        return 'announcement.wav'


class _FlightAlert(_Alert):
    """Represents a Flight Alert notification. Not intended to be used directly,
    but rather subclassed."""
    def __init__(self, device_token, flight, user_flight_num):
        super(_FlightAlert, self).__init__(device_token)
        assert flight
        assert utils.valid_flight_number(user_flight_num)
        self._flight = flight
        self._user_flight_num = user_flight_num
        self._origin_city_or_airport = (flight.origin.city or
                                       flight.origin.best_name)
        self._destination_city_or_airport = (flight.destination.city or
                                            flight.destination.best_name)


class _GenericAlert(_Alert):
    """Defines a generic alert that sends a push notification."""
    def __init__(self, device_token, message):
        super(_GenericAlert, self).__init__(device_token)
        self._message = message

    @property
    def message(self):
        """Returns the message body of the push notification. Subclasses are
        expected to implement this method and return a short string to be
        displayed to the user."""
        return self._message


class FlightDivertedAlert(_FlightAlert):
    """A push notification indicating a flight has been diverted."""
    @property
    def message(self):
        # TODO: Figure out what airport it was diverted to
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
        return 'takeoff.wav'


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
        return 'landing.wav'


class FlightPlanChangeAlert(_FlightAlert):
    """A push notification indicating a flight plan has changed."""
    @property
    def message(self):
        flight_status = self._flight.status
        time_diff = self._flight.estimated_arrival_time - utils.timestamp(date=datetime.utcnow())
        pretty_interval = utils.pretty_time_interval(time_diff, round_days=True)

        # Figure out what changed about the flight
        if flight_status == FLIGHT_STATES.DELAYED:
            return 'Flight %s from %s is delayed. Estimated to arrive at %s in %s.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    self._flight.destination.best_name,
                    pretty_interval)
        elif flight_status == FLIGHT_STATES.EARLY:
            return 'Flight %s from %s is early. Estimated to arrive at %s in %s.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    self._flight.destination.best_name,
                    pretty_interval)
        elif flight_status == FLIGHT_STATES.ON_TIME:
            return 'Flight %s from %s is on time. Estimated to arrive at %s in %s.' % (
                    self._user_flight_num,
                    self._origin_city_or_airport,
                    self._flight.destination.best_name,
                    pretty_interval)

    @property
    def notification_type(self):
        return push_types.CHANGED


class TerminalChangeAlert(FlightPlanChangeAlert):
    """Push notification indicating that the destination terminal has changed."""
    @property
    def message(self):
        terminal = self._flight.destination.terminal
        time_diff = self._flight.estimated_arrival_time - utils.timestamp(date=datetime.utcnow())
        pretty_interval = utils.pretty_time_interval(time_diff, round_days=True)

        if terminal and terminal == 'I':
            return 'Flight %s from %s will land at %s international terminal in %s.' % (
                self._user_flight_num,
                self._origin_city_or_airport,
                self._flight.destination.best_name,
                pretty_interval)
        elif terminal:
            return 'Flight %s from %s will land at %s terminal %s in %s.' % (
                self._user_flight_num,
                self._origin_city_or_airport,
                self._flight.destination.best_name,
                terminal,
                pretty_interval)


class FlightFiledAlert(FlightPlanChangeAlert):
    """A push notification indicating a flight plan has been filed."""
    @property
    def notification_type(self):
        return push_types.FILED


class LeaveSoonAlert(_GenericAlert):
    """A push notification indicating that the user should leave soon for the airport."""
    @property
    def notification_type(self):
        return push_types.LEAVE_SOON


class LeaveNowAlert(_GenericAlert):
    """A push notification indicating that the user should leave now for the airport."""
    @property
    def notification_type(self):
        return push_types.LEAVE_NOW