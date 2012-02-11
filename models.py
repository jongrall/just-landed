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
    iata_code = model.StringProperty()
    location = model.GeoPtProperty()
    name = model.StringProperty()
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