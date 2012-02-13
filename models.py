#!/usr/bin/python

"""models.py: This module defines model classes used by the Just Landed app.

Some of these models are persisted to the GAE datastore, while others exist only
in memory as a way of keeping data organized and providing a clear interface.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

from google.appengine.ext.ndb import model
import utils

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
                    latitude=utils.round_coord(self.location.lat),
                    longitude=utils.round_coord(self.location.lon),
                    name=self.name)

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