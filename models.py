import logging

from google.appengine.ext.ndb import model, tasklets

################################################################################
"""Airport Model Class"""
################################################################################

class Airport(model.Model):
    """ Model representing an airport.

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
        return dict(city=self.city,
                    icaoCode=self.key.string_id(),
                    iataCode=self.iata_code,
                    latitude=self.location.lat,
                    longitude=self.location.lon,
                    name=self.name)