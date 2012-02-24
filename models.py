#!/usr/bin/python

"""models.py: This module defines model classes used by the Just Landed app.

Some of these models are persisted to the GAE datastore, while others exist only
in memory as a way of keeping data organized and providing a clear interface.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

from datetime import timedelta, datetime

from google.appengine.ext.ndb import model
from utils import *

from config import config

# Supported push notification preference names.
_PREFS = ['push_filed',
          'push_diverted',
          'push_canceled',
          'push_departed',
          'push_arrived',
          'push_delayed']

class Airport(model.Model):
    """ Model associated with an Airport entity stored in the GAE datastore.

    Fields:
    - `altitude` : The altitude (in feet) the airport is at.
    - `city` : The name of the closest city to the aiport.
    - `country` : The country the airport is in.
    - `dst` : The daylight saving zone the airport is in.
    - `iata_code` : The IATA code associated with the airport.
    - `location` : The location of the airport (lat, long)
    - `name` : The name of the aiport.
    - `timezone_offset` : The timezone offset from GMT where the airport is.

    """
    altitude = model.IntegerProperty()
    city = model.StringProperty()
    country = model.StringProperty()
    dst = model.StringProperty()
    iata_code = model.StringProperty(required=True)
    location = model.GeoPtProperty(required=True)
    name = model.StringProperty(required=True)
    timezone_offset = model.FloatProperty()

    def dict_for_client(self):
        """Returns the Airport as a dictionary suitable for being converted to
        JSON and returned to a client.

        """
        return dict(city=self.city,
                    icaoCode=self.key.string_id(),
                    iataCode=self.iata_code,
                    latitude=round_coord(self.location.lat),
                    longitude=round_coord(self.location.lon),
                    name=proper_airport_name(self.name))


class TrackedFlight(model.Model):
    """ Model associated with a flight that is being tracked by Just Landed
    users. Each flight tracked is a unique leg of a potentially multi-leg flight
    with the same tail number. The key of tracked flight is a unique FlightID.

    Intended to be subclassed for each 3rd party flight data API to keep track
    of flights tracked for each datasource.

    Fields:
    - `__key__` : The unique flight_id for the flight.
    - `created` : When the entity was created.
    - `updated` : When the entity was last updated.

    """
    created = model.DateTimeProperty(auto_now_add=True)
    updated = model.DateTimeProperty(auto_now=True)

class FlightAwareTrackedFlight(TrackedFlight):
    """ Subclass of TrackedFlight specialized for the FlightAware datasource.

    Fields:
    - `tail_number` : The flight tail number computed from the flight_id.
    - `alert_id` : The FlightAware alert associated with this tracked flight.
    - `is_tracking` : Whether the flight is still being tracked.
    """
    tail_number = model.ComputedProperty(lambda f: f.key.string_id().split('_')[0])
    alert_id = model.IntegerProperty()
    is_tracking = model.BooleanProperty(default=True)

class _User(model.Model):
    """ A user/client who is tracking their flights using Just Landed. The key
    of the user is their UUID, which is unique to each device/client. So really,
    a single person may have multiple users in the system - one for each device
    with Just Landed installed.

    Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : When the user first tracked a flight.
    - `updated` : When the user was last updated.
    - `tracked_flights` : The flight(s) that the user is currently tracking.
    - `num_tracked_flights` : The number of flights this user has ever tracked.
    - `push_enabled` : Whether or not this user accepts push notifications.
    - `location` : The location that the user last tracked from.
    - `banned` : Whether this user has been banned.
    """
    created = model.DateTimeProperty(auto_now_add=True)
    updated = model.DateTimeProperty(auto_now=True)
    tracked_flights = model.KeyProperty(repeated=True)
    num_tracked_flights = model.IntegerProperty()
    do_push = model.BooleanProperty(default=False)
    location = model.GeoPtProperty()
    banned = model.BooleanProperty(default=False)

class iOSUser(_User):
    """ An iOS user/client. """
    pass


class Origin(object):
    """Container class for a flight origin being returned by the Just Landed API"""
    def __init__(self, origin_info):
        if isinstance(origin_info, dict):
            self._data = origin_info
        else:
            self._data = {}

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
    def name(self, value):
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

    @terminal.setter
    def terminal(self, value):
        self._data['terminal'] = value

    def dict_for_client(self):
        info = {}
        info.update(self._data)
        return info


class Destination(Origin):
    """Container class for a flight destination being returned by the Just Landed API"""
    @property
    def bag_claim(self):
        return self._data.get('bagClaim')

    @bag_claim.setter
    def bag_claim(self, value):
        self._data['bagClaim'] = value


FLIGHT_STATES = Enum(['SCHEDULED', 'ON_TIME', 'DELAYED', 'CANCELED',
                        'DIVERTED', 'LANDED', 'EARLY'])


class Flight(object):
    """Container class for a flight being returned by the Just Landed API"""

    def __init__(self, flight_info):
        if isinstance(flight_info, dict):
            self._data = flight_info
        else:
            self._data = {}

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
    def status(self):
        if self.actual_departure_time == 0:
            # See if it has missed its take-off time
            if timestamp(datetime.utcnow()) > self.scheduled_departure_time:
                time_diff = (self.estimated_arrival_time -
                (self.scheduled_departure_time + self.scheduled_flight_duration))
                if time_diff > config['on_time_buffer']:
                    return FLIGHT_STATES.DELAYED
                else:
                    return FLIGHT_STATES.SCHEDULED
            else:
                return FLIGHT_STATES.SCHEDULED
        elif self.diverted:
            return FLIGHT_STATES.DIVERTED
        elif self.actual_departure_time == -1:
            return FLIGHT_STATES.CANCELED
        elif self.actual_arrival_time > 0:
            return FLIGHT_STATES.LANDED
        else:
            time_diff = (self.estimated_arrival_time -
                (self.scheduled_departure_time + self.scheduled_flight_duration))

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
                        - timestamp(datetime.utcnow()))
            return 'Arrives in %s' % pretty_time_interval(interval)
        elif status == FLIGHT_STATES.LANDED:
            interval = timestamp(datetime.utcnow()) - self.actual_arrival_time
            return 'Landed %s ago' % pretty_time_interval(interval)
        else:
            interval = (self.estimated_arrival_time -
                (self.scheduled_departure_time + self.scheduled_flight_duration))
            if status == FLIGHT_STATES.EARLY:
                return '%s early' % pretty_time_interval(interval)
            elif status == FLIGHT_STATES.DELAYED:
                return '%s late' % pretty_time_interval(interval)
            else:
                return 'On time'

    @property
    def is_old_flight(self):
        arrival_timestamp = self.actual_arrival_time
        arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
        est_arrival_time = datetime.utcfromtimestamp(self.estimated_arrival_time)
        hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
        return ((arrival_timestamp > 0 and arrival_time < hours_ago) or
                est_arrival_time < hours_ago)

    @property
    def is_in_flight(self):
        return (self.actual_departure_time > 0 and
                self.actual_arrival_time == 0)

    @property
    def has_landed(self):
        return self.actual_arrival_time > 0

    @property
    def leave_for_airport_time(self):
        return self._data.get('leaveForAirportTime')

    @leave_for_airport_time.setter
    def leave_for_airport_time(self, value):
        self._data['leaveForAirportTime'] = value

    def set_driving_time(self, driving_time):
        self.leave_for_airport_time = self.estimated_arrival_time - driving_time

    def dict_for_client(self):
        info = sub_dict_select(self._data, config['flight_fields'])
        info['origin'] = self.origin.dict_for_client()
        info['destination'] = self.destination.dict_for_client()
        info['status'] = self.status
        info['detailedStatus'] = self.detailed_status
        return info