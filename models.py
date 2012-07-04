#!/usr/bin/env python

"""models.py: This module defines model classes used by the Just Landed app.

Some of these models are persisted to the GAE datastore, while others exist only
in memory as a way of keeping data organized and providing a clear interface.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
from datetime import timedelta, datetime

# Optimization : extensive use of NDB and tasklets to improve concurrency and
# performance of datastore operations.
from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets

from config import config, on_development
import utils

FLIGHT_STATES = config['flight_states']
DATA_SOURCES = config['data_sources']
reminder_types = config['reminder_types']

# Set to true to log informational messages about datastore operations
debug_datastore = on_development() and False

# Optimization: indexed=False is set for most datastore properties to improve
# write performance of entities. Also, short names are set to reduce space
# used by property names in the datastore.

class Airport(ndb.Model):
    """ Model associated with an Airport entity stored in the GAE datastore.

    Fields:
    - `__key__` : The ICAO code associated with the airport.
    - `altitude` : The altitude (in feet) the airport is at.
    - `city` : The name of the closest city to the aiport.
    - `country` : The country the airport is in.
    - `dst` : The daylight saving zone the airport is in.
    - `iata_code` : The IATA code associated with the airport.
    - `location` : The location of the airport (lat, long)
    - `name` : The name of the aiport.
    - `timezone_name` : The standard name of the timezone.
    - `timezone_offset` : The timezone offset from GMT where the airport is.

    """
    altitude = ndb.IntegerProperty('alt')
    city = ndb.TextProperty()
    country = ndb.TextProperty()
    dst = ndb.TextProperty()
    iata_code = ndb.StringProperty('iata', required=True)
    location = ndb.GeoPtProperty('loc', required=True, indexed=False)
    name = ndb.TextProperty(required=True)
    timezone_name = ndb.TextProperty('tz')
    timezone_offset = ndb.FloatProperty('tz_off', indexed=False)

    @classmethod
    @ndb.tasklet
    def get_by_icao_code(cls, icao_code):
        # Optimization: only fetch the airport if the ICAO code looks valid
        if utils.is_valid_icao(icao_code):
            airport_key = ndb.Key(cls, icao_code)
            airport = yield airport_key.get_async()
            raise tasklets.Return(airport)

    @classmethod
    @ndb.tasklet
    def get_by_iata_code(cls, iata_code):
        # Optimization: only fetch the airport if the IATA code looks valid
        if utils.is_valid_iata(iata_code):
            qry = cls.query(cls.iata_code == iata_code)
            airport = yield qry.get_async()
            raise tasklets.Return(airport)

    def dict_for_client(self):
        """Returns the Airport as a dictionary suitable for being converted to
        JSON and returned to a client.

        """
        return dict(city=self.city,
                    country=self.country,
                    altitude=self.altitude,
                    icaoCode=self.key.string_id(),
                    iataCode=self.iata_code,
                    latitude=utils.round_coord(self.location.lat),
                    longitude=utils.round_coord(self.location.lon),
                    timezone=self.timezone_name,
                    name=utils.proper_airport_name(self.name))


class TrackedFlight(ndb.Model):
    """ Model associated with a flight that is being tracked by Just Landed
    users. Each flight tracked is a unique leg of a potentially multi-leg flight
    with the same tail number. The key of tracked flight is a unique FlightID.

    Intended to be subclassed for each 3rd party flight data API to keep track
    of flights tracked for each datasource.

    Fields:
    - `__key__` : The unique flight_id for the flight.
    - `created` : When the entity was created.
    - `updated` : When the entity was last updated.
    - `num_users_tracking` : The number of users currently tracking a flight.
    - `is_tracking` : Whether the flight is still being tracked.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    num_users_tracking = ndb.IntegerProperty('num_u', default=0, indexed=False)
    is_tracking = ndb.ComputedProperty(lambda f: f.num_users_tracking > 0, 'tracking')


class FlightAwareTrackedFlight(TrackedFlight):
    """ Subclass of TrackedFlight specialized for the FlightAware datasource.

    Fields:
    - `last_flight_data` : The last flight data we have.
    - `orig_departure_time` : The original departure time as far as we know.
    - `orig_flight_duration` : The original flight duration as far as we know.
    """
    last_flight_data = ndb.JsonProperty('data', required=True)
    orig_departure_time = ndb.IntegerProperty('orig_dep', required=True, indexed=False)
    orig_flight_duration = ndb.IntegerProperty('orig_dur', required=True, indexed=False)

    @classmethod
    @ndb.tasklet
    def get_flight_by_id(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = ndb.Key(cls, flight_id)
        flight = yield flight_key.get_async()
        raise tasklets.Return(flight)

    @classmethod
    @ndb.tasklet
    def create_flight(cls, flight):
        assert isinstance(flight, Flight)
        new_flight = cls(id=flight.flight_id,
                         orig_departure_time=flight.scheduled_departure_time,
                         orig_flight_duration=flight.scheduled_flight_duration,
                         last_flight_data=flight.to_dict())
        yield new_flight.put_async()
        raise tasklets.Return(new_flight)

    @classmethod
    def tracked_flights_qry(cls):
        return cls.query(cls.is_tracking == True)

    @classmethod
    @ndb.tasklet
    def count_tracked_flights(cls):
        q = cls.query(cls.is_tracking == True)
        count = yield q.count_async(keys_only=True)
        raise tasklets.Return(count)

    @ndb.tasklet
    def update_last_flight_data(self, flight_data):
        self.last_flight_data = flight_data
        yield self.put_async()
        raise tasklets.Return(self)


class FlightAlert(ndb.Model):
    """Model class associated with a push alert that has been registered with
    a 3rd party API. Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : The date the alert was created.
    - `updated` : The date the alert was last updated.
    - `num_users_with_alert` : The number of users with the alert.
    - `is_enabled` : Whether the alert is enabled or not.
    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    num_users_with_alert = ndb.IntegerProperty('num_u', default=0, indexed=False)
    is_enabled = ndb.ComputedProperty(lambda a: a.num_users_with_alert > 0, 'enabled')


class FlightAwareAlert(FlightAlert):
    """Model class associated with a FlightAware push alert. Key is the
    flight number.

    Fields:
    - `alert_id` : The id of the alert in the FlightAware system.
    """
    alert_id = ndb.IntegerProperty(required=True)

    @classmethod
    @ndb.tasklet
    def get_by_flight_id(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)
        assert utils.valid_flight_number(flight_num)
        alert = yield ndb.Key(cls, flight_num).get_async()
        raise tasklets.Return(alert)

    @classmethod
    @ndb.tasklet
    def get_by_alert_id(cls, alert_id):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        q = cls.query(cls.alert_id == alert_id)
        alert = yield q.get_async()
        raise tasklets.Return(alert)

    @classmethod
    @ndb.tasklet
    def create_or_reuse_alert(cls, flight_id, alert_id):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)
        assert isinstance(flight_num, basestring) and utils.valid_flight_number(flight_num)

        alert = yield ndb.Key(cls, flight_num).get_async()

        # Optimization: alerts are re-used if possible
        if not alert:
            # Create alert in DB
            alert = cls(id=flight_num,
                        alert_id=alert_id)
            if debug_datastore:
                logging.info('CREATED ALERT %s, %d' % (flight_num, alert_id))
        else:
            # Previous alert existed for flight_num, recycle it with new alert_id
            alert.alert_id = alert_id
            alert.num_users_with_alert = 0
            if debug_datastore:
                logging.info('RECYCLED ALERT %s, %d' % (flight_num, alert_id))

        yield alert.put_async()
        raise tasklets.Return(alert)

    @ndb.tasklet
    def disable(self):
        # Optimization: only disable if the alert is currently enabled
        if self.is_enabled:
            self.num_users_with_alert = 0
            yield self.put_async()


class FlightReminder(ndb.Model):
    """Model for a reminder telling a user to leave for the airport.

    Fields:
    - `fire_time` : The date and time when the reminder should be sent.
    - `reminder_type` : The type of the reminder.
    - `sent` : Whether the reminder has been sent or not.
    - `body` : The body of the reminder.
    - `flight` : The flight this reminder is associated with.
    """
    fire_time = ndb.DateTimeProperty(required=True)
    reminder_type = ndb.StringProperty('type', choices=[reminder_types.LEAVE_SOON, reminder_types.LEAVE_NOW],
                                       required=True, indexed=False)
    sent = ndb.BooleanProperty(default=False, indexed=False)
    body = ndb.TextProperty(required=True)
    flight = ndb.KeyProperty(required=True, indexed=False)


class PushNotificationSetting(ndb.Model):
  """Model for a push notification setting (stored as key-value).

  E.g. push_arrived = True

  Represents a single push notification setting that will be associated with
  a specific Device.

  Fields:
  - `name` : The name of the setting.
  - `value` : The value of the setting (True/False)

  """
  name = ndb.StringProperty('n', required=True, indexed=False)
  value = ndb.BooleanProperty('v', required=True, indexed=False)


class _User(ndb.Model):
    """A user/client who is tracking their flights using Just Landed.

    Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : When the user first tracked a flight.
    - `updated` : When the user was last updated.
    - `banned` : Whether this user has been banned.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    banned = ndb.BooleanProperty(default=False)


class UserTrackedFlight(ndb.Model):
    """Model representing a flight that a user is tracking.

    Fields:
    - `flight` : The flight being tracked.
    - `user_flight_num` : The flight number the user entered to find this flight.
    """
    flight = ndb.KeyProperty(required=True)
    user_flight_num = ndb.StringProperty('u_f_num', required=True)


class iOSUser(_User):
    """An iOS user/client. The key of the user is their UUID, which is unique
    to each device/client. So really, a single person may have multiple users
    in the system - one for each device with Just Landed installed.

    Fields:
    - `last_known_location` : The user's last known location.
    - `tracked_flights` : The flight(s) that the user is currently tracking.
    - `is_tracking_flights` : Whether the user is currently tracking flights.
    - `alerts` : The flight alert(s) that this user should receive.
    - `reminders` : The flight reminders that are set for this user.
    - `has_unsent_reminders` : Whether this user has unsent reminders.
    - `push_token` : The push token associated with this user.
    - `push_settings` : The push notification settings for this user.
    - `push_enabled` : Whether this user accepts push notifications.
    - `lifetime_flights_tracked` : The number of flights this user has ever tracked.

    """
    last_known_location = ndb.GeoPtProperty('loc', indexed=False)
    tracked_flights = ndb.StructuredProperty(UserTrackedFlight, 'flights', repeated=True)
    is_tracking_flights = ndb.ComputedProperty(lambda u: bool(len(u.tracked_flights)), 'is_tracking')
    alerts = ndb.KeyProperty(repeated=True)
    reminders = ndb.StructuredProperty(FlightReminder, repeated=True)
    has_unsent_reminders = ndb.ComputedProperty(lambda u: bool([r for r in u.reminders if r.sent == False]))
    push_token = ndb.TextProperty()
    push_settings = ndb.StructuredProperty(PushNotificationSetting, repeated=True)
    push_enabled = ndb.ComputedProperty(lambda u: bool(u.push_token))
    lifetime_flights_tracked = ndb.IntegerProperty('lifetime_tracks', default=0)

    @classmethod
    @ndb.tasklet
    def get_by_uuid(cls, uuid):
        assert isinstance(uuid, basestring) and len(uuid)
        user_key = ndb.Key(cls, uuid)
        user = yield user_key.get_async()
        raise tasklets.Return(user)

    @classmethod
    def default_settings(cls):
        """Returns a list of the default PushNotificationSettings for an iOS user."""
        settings = []
        # Prefs are True by default
        for push in config['push_types']:
            settings.append(PushNotificationSetting(name=push, value=True))
        return settings

    @classmethod
    @ndb.tasklet
    def track_flight(cls, uuid, flight, tracked_flight, user_flight_num,
                     user_latitude=None, user_longitude=None, driving_time=None,
                     push_token=None, alert=None, source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert utils.valid_flight_number(user_flight_num)

        if source == DATA_SOURCES.FlightAware:
            assert isinstance(tracked_flight, FlightAwareTrackedFlight)

        flight_id = tracked_flight.key.string_id()
        to_put = []

        # See if the user exists, create if necessary
        user = yield cls.get_by_uuid(uuid)
        if not user:
            user = cls(id=uuid,
                       push_settings=cls.default_settings())
            if debug_datastore:
                logging.info('CREATED NEW USER %s' % uuid)
        elif debug_datastore:
            logging.info('UPDATING EXISTING USER %s' % uuid)

        # Optimization: only update the user's location if it has changed
        if (user_latitude is not None) and (user_longitude is not None) and not user.location_is_current(user_latitude, user_longitude):
            user.last_known_location = ndb.GeoPt(user_latitude, lon=user_longitude)

        # Track the flight if they weren't tracking it yet
        if not user.is_tracking_flight(flight_id):
            user.add_tracked_flight(flight_id, user_flight_num, source=source)
            tracked_flight.num_users_tracking += 1
            to_put.append(tracked_flight.put_async())

            if debug_datastore:
                logging.info('USER STARTED TRACKING FLIGHT %s' % flight_id)

        # Add the alert if they didn't have it yet
        if alert and alert.key not in user.alerts:
            user.alerts.append(alert.key)
            alert.num_users_with_alert += 1
            to_put.append(alert.put_async())
            if debug_datastore:
                logging.info('USER SUBSCRIBED TO ALERT %s' % alert.alert_id)

        # Update the push token if we have a new one
        if push_token and push_token != user.push_token:
            user.push_token = push_token
            if debug_datastore:
                logging.info('USER PUSH TOKEN UPDATED')

        # If we have driving time, update their reminders
        if driving_time is not None:
            user.set_or_update_flight_reminders(flight, driving_time, source=source)

        to_put.append(user.put_async())
        yield to_put
        raise tasklets.Return(user)

    def set_or_update_flight_reminders(self, flight, driving_time, source=DATA_SOURCES.FlightAware):
        assert isinstance(flight, Flight)
        assert isinstance(driving_time, (int, long))

        flight_id = flight.flight_id
        reminders = self.get_reminders_for_flight(flight_id, source=source)

        # If the flight is canceled or diverted, remove the alerts and don't add or update them
        if flight.status in [FLIGHT_STATES.CANCELED, FLIGHT_STATES.DIVERTED]:
            if reminders:
                self.remove_flight_reminders(flight_id, source=source)
            return

        flight_num = self.flight_num_for_flight_id(flight_id)
        dest_terminal = flight.destination.terminal
        dest_name = flight.destination.best_name
        leave_soon_interval = config['leave_soon_seconds_before']
        leave_soon_pretty_interval = utils.pretty_time_interval(leave_soon_interval, round_days=True)

        # Figure out the reminder messages
        leave_soon_body = None
        leave_now_body = None
        if dest_terminal and dest_terminal == 'I':
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives at the international terminal.' % (
                                dest_name, leave_soon_pretty_interval, flight_num)
            leave_now_body = 'Leave now for %s. Flight %s arrives at the international terminal.' % (
                                dest_name, flight_num)
        elif dest_terminal:
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives at terminal %s.' % (
                                dest_name, leave_soon_pretty_interval, flight_num, dest_terminal)
            leave_now_body = 'Leave now for %s. Flight %s arrives at terminal %s.' % (
                                dest_name, flight_num, dest_terminal)
        else:
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives soon.' % (
                                dest_name, leave_soon_pretty_interval, flight_num)
            leave_now_body = 'Leave now for %s. Flight %s arrives soon.' % (
                                dest_name, flight_num)

        # Calculate the reminder times
        leave_soon_time = utils.leave_soon_time(flight, driving_time)
        leave_now_time = utils.leave_now_time(flight, driving_time)

        # If they have no reminders for this flight, set them (even if they were supposed to fire in the past)
        if not reminders:
            flight_key = None
            if source == DATA_SOURCES.FlightAware:
                flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            assert flight_key

            # Set a leave soon reminder
            leave_soon = FlightReminder(fire_time=leave_soon_time,
                                        reminder_type=reminder_types.LEAVE_SOON,
                                        flight=flight_key,
                                        body=leave_soon_body,
                                        sent=leave_soon_time < datetime.utcnow())

            # Set a leave now reminder
            leave_now = FlightReminder(fire_time=leave_now_time,
                                       reminder_type=reminder_types.LEAVE_NOW,
                                       flight=flight_key,
                                       body=leave_now_body)

            self.reminders.extend([leave_soon, leave_now])

        else:
            for r in reminders:
                # Only update unsent reminders (stops reminders from potentially being sent again)
                if r.sent == False:
                    if r.reminder_type == reminder_types.LEAVE_SOON:
                        r.fire_time = leave_soon_time
                        r.body = leave_soon_body
                    else:
                        r.fire_time = leave_now_time
                        r.body = leave_now_body

    @classmethod
    @ndb.tasklet
    def clear_alert_from_users(cls, alert):
        assert isinstance(alert, ndb.Model)
        alert_key = alert.key

        @ndb.tasklet
        @ndb.transactional
        def remove_alert(u_key):
            # Getting the user again inside transaction ensures consistency
            u = yield u_key.get_async()
            if u and alert_key in u.alerts:
                u.alerts.remove(alert_key)
                yield u.put_async()

        qry = cls.query(cls.alerts == alert_key)
        yield qry.map_async(remove_alert, keys_only=True)

    @classmethod
    @ndb.tasklet
    def stop_tracking_flight(cls, uuid, flight_id, alert=None, source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight_id, basestring) and len(flight_id)

        flight_fut = None

        if source == DATA_SOURCES.FlightAware:
            flight_fut = FlightAwareTrackedFlight.get_flight_by_id(flight_id)

        # Optimization: parallel yield
        user, flight = yield cls.get_by_uuid(uuid), flight_fut

        # We must have a matching user & flight
        if user and flight:
            to_put = []

            # Remove the tracked flight
            if user.is_tracking_flight(flight_id):
                # Could potentially be tracking the same flight multiple times
                num_times_removed = user.remove_tracked_flight(flight_id)
                flight.num_users_tracking -= num_times_removed
                to_put.append(flight.put_async())

            # Remove the alert (if appropriate)
            if alert and alert.key in user.alerts:
                alert_key = alert.key

                # EDGE CASE: User could be tracking several different flights with same ident
                # Remove alert from the user only if no other flight they are tracking needs it
                needs_alert = False

                if source == DATA_SOURCES.FlightAware:
                    untracking_flight_num = utils.flight_num_from_fa_flight_id(flight_id)

                    # Check the remaining flights they are tracking (if any)
                    for f in user.tracked_flights:
                        # FIXME: Assumes FlightAware is not being used alongside another data source
                        tracked_f_num = utils.flight_num_from_fa_flight_id(f.flight.string_id())
                        needs_alert = tracked_f_num == untracking_flight_num
                        if needs_alert:
                            break # Optimization: stop as soon as we find one

                if not needs_alert:
                    to_remove = []
                    # Remove the alert (possibly occurs multiple times)
                    for a in user.alerts:
                        if a == alert_key:
                            to_remove.append(a)
                    for a in to_remove:
                        user.alerts.remove(a)
                        alert.num_users_with_alert -= len(to_remove)
                        to_put.append(alert.put_async())

            # Remove reminders
            user.remove_flight_reminders(flight_id, source=source)

            # Write the result
            to_put.append(user.put_async())
            yield to_put

        raise tasklets.Return((flight, alert))

    @classmethod
    def users_tracking_flight_qry(cls, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(flight_id, basestring) and len(flight_id)
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            return cls.query(cls.tracked_flights.flight == flight_key)

    @classmethod
    def users_to_notify_qry(cls, alert, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(alert, ndb.Model)
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

        assert flight_key
        return cls.query(cls.tracked_flights.flight == flight_key,
                         cls.alerts == alert.key,
                         cls.push_enabled == True)

    @classmethod
    def users_with_overdue_reminders_qry(cls):
        return cls.query(cls.has_unsent_reminders == True,
                        cls.push_enabled == True,
                        cls.reminders.fire_time < datetime.utcnow())

    @classmethod
    @ndb.tasklet
    def multiple_users_tracking_flight_num(cls, flight_num):
        qry = cls.query(cls.tracked_flights.user_flight_num == flight_num,
                        cls.push_enabled == True)
        # Optimization: count no more than 2, keys_only
        count = yield qry.count_async(limit=2, keys_only=True)
        raise tasklets.Return(count == 2)

    @classmethod
    @ndb.tasklet
    def count_users_tracking(cls):
        q = cls.query(cls.is_tracking_flights == True)
        # Optimization: count keys only
        count = yield q.count_async(keys_only=True)
        raise tasklets.Return(count)

    def wants_notification_type(self, push_type):
        assert push_type
        for setting in self.push_settings:
            if setting.name == push_type and setting.value == True:
                return True
        return False

    def flight_num_for_flight_id(self, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        for f in self.tracked_flights:
            if f.flight.string_id() == flight_id:
                return f.user_flight_num

    def is_tracking_flight(self, flight_id):
        for f in self.tracked_flights:
            if f.flight.string_id() == flight_id:
                return True
        return False

    def add_tracked_flight(self, flight_id, flight_num, source=DATA_SOURCES.FlightAware):
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

        assert flight_key
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert utils.valid_flight_number(flight_num)

        # Guard against tracking the same flight twice
        if not self.is_tracking_flight(flight_id):
            new_flight = UserTrackedFlight(flight=flight_key,
                                           user_flight_num=flight_num)
            self.tracked_flights.append(new_flight)
            self.lifetime_flights_tracked += 1 # Count towards lifetime tracks

    def remove_tracked_flight(self, flight_id):
        to_remove = []
        for f in self.tracked_flights:
            if f.flight.string_id() == flight_id:
                to_remove.append(f)
        for f in to_remove:
            self.tracked_flights.remove(f)
        return len(to_remove)

    def get_reminders_for_flight(self, flight_id, source=DATA_SOURCES.FlightAware):
        flight_key = None
        matches = []
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
        assert flight_key

        for r in self.reminders:
            if r.flight == flight_key:
                matches.append(r)
        return matches

    def location_is_current(self, latitude, longitude):
        loc = self.last_known_location
        return loc and loc.lat == latitude and loc.lon == longitude

    def get_unsent_reminders(self):
        unsent = []
        for r in self.reminders:
            if r.sent == False:
                unsent.append(r)
        return unsent

    def remove_flight_reminders(self, flight_id, source=DATA_SOURCES.FlightAware):
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
        assert flight_key
        to_remove = []
        for r in self.reminders:
            if r.flight == flight_key:
                to_remove.append(r)
        for r in to_remove:
            self.reminders.remove(r)


class Origin(object):
    """Container class for a flight origin being returned by the Just Landed API"""
    def __init__(self, origin_info):
        if isinstance(origin_info, dict):
            self._data = origin_info
        else:
            self._data = {}

    @property
    def altitude(self):
        return self._data.get('altitude')

    @altitude.setter
    def altitude(self, value):
        self._data['altitude'] = value

    @property
    def iata_code(self):
        return self._data.get('iataCode')

    @iata_code.setter
    def iata_code(self, value):
        self._data['iataCode'] = value

    @property
    def icao_code(self):
        return self._data.get('icaoCode')

    @icao_code.setter
    def icao_code(self, value):
        self._data['icaoCode'] = value

    @property
    def city(self):
        return self._data.get('city')

    @city.setter
    def city(self, value):
        self._data['city'] = value

    @property
    def country(self):
        return self._data.get('country')

    @country.setter
    def country(self, value):
        self._data['country'] = value

    @property
    def name(self):
        return self._data.get('name')

    @name.setter
    def name(self, value):
        self._data['name'] = value

    @property
    def latitude(self):
        return self._data.get('latitude')

    @latitude.setter
    def latitude(self, value):
        self._data['latitude'] = value

    @property
    def longitude(self):
        return self._data.get('longitude')

    @longitude.setter
    def longitude(self, value):
        self._data['longitude'] = value

    @property
    def terminal(self):
        return self._data.get('terminal')

    @property
    def best_name(self):
        """Returns city, then name, falling back to iata_code, falling back to icao_code"""
        return self.name or self.iata_code or self.icao_code

    @terminal.setter
    def terminal(self, value):
        self._data['terminal'] = value.upper().strip()

    @property
    def timezone(self):
        """Returns the name of the timezone."""
        return self._data.get('timezone') or ''

    @timezone.setter
    def timezone(self, value):
        self._data['timezone'] = value

    def dict_for_client(self):
        info = {}
        info.update(self._data)
        info = utils.sub_dict_select(info, config['airport_fields'])
        return info


class Destination(Origin):
    """Container class for a flight destination being returned by the Just Landed API"""
    @property
    def bag_claim(self):
        return self._data.get('bagClaim')

    @bag_claim.setter
    def bag_claim(self, value):
        self._data['bagClaim'] = value

    @property
    def gate(self):
        return self._data.get('gate')

    @gate.setter
    def gate(self, value):
        self._data['gate'] = value


class Flight(object):
    """Container class for a flight being returned by the Just Landed API"""

    def __init__(self, flight_info):
        if isinstance(flight_info, dict):
            self._data = flight_info
        else:
            self._data = {}

    @classmethod
    def from_dict(cls, flight_dict):
        assert isinstance(flight_dict, dict)
        f = cls(flight_dict)
        assert isinstance(f.flight_id, basestring) and len(f.flight_id)
        assert utils.valid_flight_number(f.flight_number)
        f.origin = Origin(flight_dict.get('origin'))
        f.destination = Destination(flight_dict.get('destination'))
        return f

    @property
    def aircraft_type(self):
        return self._data.get('aircraftType')

    @aircraft_type.setter
    def aircraft_type(self, value):
        self._data['aircraftType'] = value

    @property
    def actual_arrival_time(self):
        return self._data.get('actualArrivalTime')

    @actual_arrival_time.setter
    def actual_arrival_time(self, value):
        self._data['actualArrivalTime'] = value

    @property
    def actual_departure_time(self):
        return self._data.get('actualDepartureTime')

    @actual_departure_time.setter
    def actual_departure_time(self, value):
        self._data['actualDepartureTime'] = value

    @property
    def destination(self):
        return self._data.get('destination')

    @destination.setter
    def destination(self, value):
        self._data['destination'] = value

    @property
    def diverted(self):
        return self._data.get('diverted')

    @diverted.setter
    def diverted(self, value):
        self._data['diverted'] = value

    @property
    def estimated_arrival_time(self):
        return self._data.get('estimatedArrivalTime')

    @estimated_arrival_time.setter
    def estimated_arrival_time(self, value):
        self._data['estimatedArrivalTime'] = value

    @property
    def flight_id(self):
        return self._data.get('flightID')

    @flight_id.setter
    def flight_id(self, value):
        self._data['flightID'] = value

    @property
    def flight_number(self):
        return self._data.get('flightNumber')

    @flight_number.setter
    def flight_number(self, value):
        self._data['flightNumber'] = value

    @property
    def last_updated(self):
        return self._data.get('lastUpdated')

    @last_updated.setter
    def last_updated(self, value):
        self._data['lastUpdated'] = value

    @property
    def origin(self):
        return self._data.get('origin')

    @origin.setter
    def origin(self, value):
        self._data['origin'] = value

    @property
    def scheduled_departure_time(self):
        return self._data.get('scheduledDepartureTime')

    @scheduled_departure_time.setter
    def scheduled_departure_time(self, value):
        self._data['scheduledDepartureTime'] = value

    @property
    def scheduled_flight_duration(self):
        return self._data.get('scheduledFlightDuration')

    @scheduled_flight_duration.setter
    def scheduled_flight_duration(self, value):
        self._data['scheduledFlightDuration'] = value

    @property
    def scheduled_arrival_time(self):
        return self.scheduled_departure_time + self.scheduled_flight_duration

    @property
    def est_arrival_diff_from_schedule(self):
        return (self.estimated_arrival_time -
            (self.scheduled_departure_time + self.scheduled_flight_duration))

    @property
    def status(self):
        if self.actual_departure_time == 0:
            # See if it has missed its take-off time
            if utils.timestamp(datetime.utcnow()) > self.scheduled_departure_time + config['on_time_buffer']:
                return FLIGHT_STATES.DELAYED
            else:
                return FLIGHT_STATES.SCHEDULED
        elif self.diverted:
            return FLIGHT_STATES.DIVERTED
        elif self.actual_departure_time == -1:
            return FLIGHT_STATES.CANCELED
        elif self.actual_arrival_time > 0:
            return FLIGHT_STATES.LANDED
        else:
            time_diff = self.est_arrival_diff_from_schedule
            time_buff = config['on_time_buffer']
            if abs(time_diff) < time_buff:
                return FLIGHT_STATES.ON_TIME
            elif time_diff < 0:
                return FLIGHT_STATES.EARLY
            else:
                return FLIGHT_STATES.DELAYED

    @property
    def detailed_status(self):
        status = self.status

        if status == FLIGHT_STATES.SCHEDULED:
            interval = (self.scheduled_departure_time + self.scheduled_flight_duration
                        - utils.timestamp(datetime.utcnow()))
            return 'Scheduled to arrive in %s.' % utils.pretty_time_interval(interval)
        elif status == FLIGHT_STATES.LANDED:
            interval = utils.timestamp(datetime.utcnow()) - self.actual_arrival_time
            return 'Landed %s ago.' % utils.pretty_time_interval(interval)
        elif status == FLIGHT_STATES.CANCELED:
            return 'Flight canceled.'
        elif status == FLIGHT_STATES.DIVERTED:
            return 'Flight diverted to another airport.'
        else:
            interval = (self.estimated_arrival_time - utils.timestamp(datetime.utcnow()))
            if interval > 0:
                return 'Arrives in %s.' % utils.pretty_time_interval(interval)
            else:
                # Estimated arrival time is before now, arrival is imminent
                return 'Arriving shortly'

    @property
    def is_old_flight(self):
        """Returns true if the flight is definitely old."""
        if self.has_landed:
            arrival_timestamp = self.actual_arrival_time
            arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
            hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
            return arrival_time < hours_ago
        else:
            return False

    @property
    def is_probably_old(self):
        """Returns true if the flight is probably old based on the estimated
        arrival time."""
        est_arrival_timestamp = self.estimated_arrival_time
        if utils.is_int(est_arrival_timestamp) and est_arrival_timestamp > 0:
            est_arrival_time = datetime.utcfromtimestamp(est_arrival_timestamp)
            hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
            return est_arrival_time < hours_ago
        else:
            return False

    @property
    def is_in_flight(self):
        return (self.actual_departure_time > 0 and
                self.actual_arrival_time == 0)

    @property
    def has_landed(self):
        return self.actual_arrival_time > 0

    @property
    def is_night(self):
        if not self.is_in_flight:
            if self.status == FLIGHT_STATES.LANDED:
                # The flight has arrived, use the destination
                return utils.is_dark_now(self.destination.latitude,
                                         self.destination.longitude,
                                         altitude_in_feet=self.destination.altitude or 0)
            else:
                # The flight hasn't left, use the origin
                return utils.is_dark_now(self.origin.latitude,
                                         self.origin.longitude,
                                         altitude_in_feet=self.origin.altitude or 0)
        else:
            # The flight is in progress, approximate whether it is light or dark
            origin_sun_angle = utils.sun_altitude_degrees(self.origin.latitude,
                                                          self.origin.longitude,
                                                          altitude_in_feet=self.origin.altitude or 0)
            dest_sun_angle = utils.sun_altitude_degrees(self.destination.latitude,
                                                        self.destination.longitude,
                                                        altitude_in_feet=self.destination.altitude or 0)
            now = utils.timestamp(datetime.utcnow())
            progress = 0.0

            if now > self.estimated_arrival_time:
                progress = 0.999 # Landing overdue
            else:
                time_since_takeoff = now - self.actual_departure_time
                total_flight_time = self.estimated_arrival_time - self.actual_departure_time
                progress = time_since_takeoff / float(total_flight_time)

            sun_angle_approx = ((dest_sun_angle - origin_sun_angle) * progress) + origin_sun_angle
            return sun_angle_approx < 0.0

    def to_dict(self):
        info = utils.sub_dict_select(self._data, config['flight_fields'])
        info['origin'] = self.origin.dict_for_client()
        info['destination'] = self.destination.dict_for_client()
        return info

    def dict_for_client(self):
        info = self.to_dict()
        info['status'] = self.status
        info['detailedStatus'] = self.detailed_status
        info['isNight'] = self.is_night
        return info