#!/usr/bin/python

"""data_sources.py: This module defines all the data sources that power
the Just Landed app.

Flight data is pulled from either commercial APIs or from the datastore (in the
case of static data such as airport codes and locations). Commercial flight API
data sources are made to conform to a common FlightDataSource interface in
anticipation of possibly switching to alternate datasources in the future.

In addition to flight data, Just Landed estimates the user's driving time to the
airport so that it can make recommendations about when you should leave to
pick someone up at the terminal. This data also comes from commercial APIs, and
again is made to conform to a common DrivingTimeDataSource in case we switch
to new datasources in the future.

In addition to conforming to common interfaces, datasource responses are also
mapped to a predetermined JSON data format, and the JSON keys used are
standardized in config.py so that switching to new data sources in the future
will not break clients that are expecting a specific API from the JustLanded
server.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json

# We use memcache service to cache results from 3rd party APIs. This improves
# performance and also reduces our bill :)
from google.appengine.api import memcache

from config import config
from datasource_exceptions import *
from models import Airport
import utils

###############################################################################
"""Flight Data Sources"""
###############################################################################

class FlightDataSource (object):
    """A class that defines a FlightDataSource interface that flight data
    sources should implement."""
    @property
    def base_url(self):
        """Returns the base URL of the API used by the datasource."""
        pass

    @property
    def api_key_mapping(self):
        """Returns a mapping of keys from the commercial API to keys used
        by the Just Landed API which is in turn consumed by our clients. This
        translation ensures that new datasources don't break clients.

        """
        pass

    def register_alert_endpoint(self, url, **kwargs):
        """Registers a Just Landed endpoint with the 3rd party API. This
        endpoint will handle flight status callbacks e.g. by triggering push
        notifications to clients.

        """
        pass

    def flight_info(self, flight_id, **kwargs):
        """Looks up and returns a specific Flight. The amount of information
        returned depends on whether or not the flight is en route or whether it
        is commercial, private or international.

        """
        pass

    def lookup_flights(self, flight_number, **kwargs):
        """Looks up flights by flight/tail number. This number is made up of
        the airline code and the flight number e.g. 'CO 1101'. Returns a list of
        flights matching this flight number. Flights returned should include
        only flights that are no older than those that landed an hour or so ago.

        The flights are sorted by departure time from earliest to latest.

        """
        pass

    def process_alert(self, alert_body):
        """Processes an incoming alert body posted to a Just Landed endpoint
        by a 3rd party API callback and returns an instance of a FlightAlert
        to the Just Landed application.

        """
        pass

    def set_alert(self, **kwargs):
        """Registers a callback with the 3rd party API for a specific flight."""
        pass

    def delete_alert(self, alert_id):
        """Deletes a callback from the 3rd party API e.g. when a flight is no
        longer being tracked by the user.

        """
        pass

class FlightAwareSource (FlightDataSource):
    """Concrete subclass of FlightDataSource that pulls its data from the
    commercial FlightAware FlightXML2 API:

    http://flightaware.com/commercial/flightxml/documentation2.rvt

    """
    @property
    def base_url(self):
        return "http://flightxml.flightaware.com/json/FlightXML2/"

    @property
    def api_key_mapping(self):
        return config['flightaware']['key_mapping']

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url,
            username=config['flightaware']['username'],
            password=config['flightaware']['key'])

    def airport_info(self, icao_code="", iata_code=""):
        """Looks up information about an airport using its ICAO or IATA code."""
        if utils.is_valid_iata(iata_code):
            # Check the DB
            qry = Airport.query(Airport.iata_code == iata_code)
            airport = qry.get()
            return (airport and airport.dict_for_client()) or None
        elif utils.is_valid_icao(icao_code):
            # Check the DB first
            airport = Airport.get_by_id(icao_code)
            if airport:
                return airport.dict_for_client()
            else:
                # Check FlightAware for the AiportInfo
                memcache_key = "%s-airport_info-%s" % (self.__class__.__name__,
                                                       icao_code)
                airport = memcache.get(memcache_key)
                if airport is not None:
                    return airport
                else:
                    resp = self.conn.request_get('/AirportInfo',
                                                 args={'airportCode':icao_code})
                    # Turn the JSON response into a dict
                    result = json.loads(resp['body'])

                    if result.get('error'):
                        raise AirportNotFoundException(iata_code)
                    else:
                        airport = result['AirportInfoResult']

                        # Filter out fields we don't want
                        fields = config['flightaware']['airport_info_fields']
                        airport = utils.sub_dict_strict(airport, fields)

                        # Map field names
                        airport = utils.map_dict_keys(airport,
                                                      self.api_key_mapping)

                        # Add ICAO & IATA code back in
                        airport['icaoCode'] = icao_code
                        airport['iataCode'] = None

                        # Round lat & long
                        airport['latitude'] = utils.round_coord(airport['latitude'])
                        airport['longitude'] = utils.round_coord(airport['longitude'])

                        if not memcache.set(memcache_key, airport):
                            logging.error("Unable to cache airport info!")
                        return airport
        else:
            raise AirportNotFoundException(icao_code or iata_code)

    def register_alert_endpoint(self, url, **kwargs):
        pass

    def flight_info(self, flight_id, **kwargs):
        flight_number = kwargs.get('flight_number')

        if not flight_id or not flight_number:
            raise FlightNotFoundException(flight_number)

        sanitized_f_num = utils.sanitize_flight_number(flight_number)

        # Find the flight
        flights = self.lookup_flights(sanitized_f_num)
        matching_flights = [f for f in flights if f['flightID'] == flight_id]

        if not matching_flights:
            # Probably tracking an old flight
            raise OldFlightException(flight_number=sanitized_f_num,
                                     flight_id=flight_id)

        flight_info = matching_flights[0]

        # Get information about the airports
        origin = flight_info['origin']
        destination = flight_info['destination']

        if utils.is_valid_iata(origin):
            flight_info['origin'] = self.airport_info(iata_code=origin)
        else:
            flight_info['origin'] = self.airport_info(icao_code=origin)

        if utils.is_valid_iata(destination):
            flight_info['destination'] = self.airport_info(iata_code=destination)
        else:
            flight_info['destination'] = self.airport_info(icao_code=destination)

        # Get detailed terminal & gate information
        airline_info_key = "%s-airline_info-%s" % (self.__class__.__name__,
                                                   flight_id)
        airline_info = memcache.get(airline_info_key)

        if airline_info is not None:
            # Add in the airline info
            flight_info.update(airline_info)
        else:
            resp = self.conn.request_get('/AirlineFlightInfo',
                                         args={'faFlightID': flight_id})
            # Turn the JSON response into a dict
            result = json.loads(resp['body'])

            if result.get('error'):
                raise TerminalsUnknownException(flight_id)

            # Filter & map the result
            fields = config['flightaware']['airline_flight_info_fields']
            info = result['AirlineFlightInfoResult']
            info = utils.sub_dict_strict(info, fields)
            info = utils.map_dict_keys(info, self.api_key_mapping)

            if not memcache.set(airline_info_key, info):
                logging.error("Unable to cache airline flight info!")
            flight_info.update(info)

        flight_info['status'] = utils.flight_status(flight_info)
        flight_info['detailedStatus'] = utils.detailed_status(flight_info)

        # Keep only desired fields, move others
        flight_info['flightNumber'] = sanitized_f_num
        flight_info['origin']['city'] = flight_info['originCity']
        flight_info['origin']['name'] = flight_info['originName']
        flight_info['origin']['terminal'] = flight_info['originTerminal']
        flight_info['destination']['city'] = flight_info['destinationCity']
        flight_info['destination']['name'] = flight_info['destinationName']
        flight_info['destination']['terminal'] = flight_info['destinationTerminal']
        flight_info['destination']['bagClaim'] = flight_info['bagClaim']
        return flight_info

    def lookup_flights(self, flight_number, **kwargs):
        sanitized_f_num = utils.sanitize_flight_number(flight_number)
        memcache_key = "%s-lookup_flights-%s" % (self.__class__.__name__,
                                                sanitized_f_num)
        flights = memcache.get(memcache_key)

        def stale(flights):
            for f in flights:
                if utils.is_old_flight(f):
                    return True
            return False

        if flights is not None and not stale(flights):
            return flights
        else:
            resp = self.conn.request_get('/FlightInfoEx',
                     args={'ident': sanitized_f_num,
                           'howMany': 15})
            # Turn the JSON response into a dict
            flights = json.loads(resp['body'])

            if flights.get('error'):
                raise FlightNotFoundException(sanitized_f_num)
            else:
                flights = flights['FlightInfoExResult']['flights']

                # Keep a subset of the response fields
                fields = config['flightaware']['flight_info_fields']
                flights = [utils.sub_dict_strict(f, fields)
                           for f in flights]

                # Map the response dict keys
                flights = [utils.map_dict_keys(f, self.api_key_mapping)
                           for f in flights]

                # Filter out old flights
                flights = [f for f in flights if not utils.is_old_flight(f)]

                # Sort by departure date (earliest first)
                flights.sort(key=lambda f: f['scheduledDepartureTime'])

                # Try to convert to IATA airport codes & clean up flight time
                for f in flights:
                    f['flightNumber'] = sanitized_f_num
                    f['origin'] = utils.icao_to_iata(f['origin']) or f['origin']
                    f['destination'] = utils.icao_to_iata(f['destination']) or \
                                        f['destination']
                    # Convert flight times
                    flight_time = f['scheduledFlightTime'].split(':')
                    secs = (int(flight_time[0]) * 3600) + (int(flight_time[1]) * 60)
                    f['scheduledFlightTime'] = secs

            if not memcache.set(memcache_key, flights,
                                config['flightaware']['flight_info_cache_time']):
                logging.error("Unable to cache lookup response!")
            return flights

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass

###############################################################################
"""Driving Time Data Sources"""
###############################################################################

class DrivingTimeDataSource (object):
    """A class that defines a DrivingTimeDataSource interface that driving time
    data sources should implement."""

    @property
    def base_url(self):
        """Returns the base URL of the API used by the datasource."""
        pass

    def driving_time(origin_lat, origin_lon, dest_lat, dest_lon):
        """Returns an estimate of the driving time from (origin_lat, origin_lon)
        to (dest_lat, dest_lon) or throws an exception if this estimate cannot
        be calculated - either due to a problem with the datasource, or due
        to there being no driving route between the two points.

        The driving time returned is in seconds.

        """
        pass

class GoogleDistanceSource (DrivingTimeDataSource):
    """Concrete subclass of DrivingTimeDataSource that pulls its data from the
    commercial Google Distance Matrix API:

    http://code.google.com/apis/maps/documentation/distancematrix/

    """
    @property
    def base_url(self):
        return 'http://maps.googleapis.com/maps/api/distancematrix'

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url,
            username=config['flightaware']['username'],
            password=config['flightaware']['key'])

    def driving_time(self, origin_lat, origin_lon, dest_lat, dest_lon):
        driving_cache_key = '%s-driving_time-%f,%f,%f,%f' % (
            self.__class__.__name__,
            utils.round_coord(origin_lat, sf=2),
            utils.round_coord(origin_lon, sf=2),
            utils.round_coord(dest_lat, sf=2),
            utils.round_coord(dest_lon, sf=2),
        )

        time = memcache.get(driving_cache_key)

        if time is not None:
            return time
        else:
            params = dict(
                origins='%f,%f' % (origin_lat, origin_lon),
                destinations='%f,%f' % (dest_lat, dest_lon),
                sensor='true',
                mode='driving',
                units='imperial',
            )
            resp = self.conn.request_get('/json', args=params)

            # Turn the JSON response into a dict
            result = json.loads(resp.get('body'))
            status = result.get('status')

            if status == 'OK':
                try:
                    time = result['rows'][0]['elements'][0]['duration']['value']
                    if not memcache.set(driving_cache_key, time):
                        logging.error("Unable to cache driving time!")
                    return time
                except Exception:
                    raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon)
            elif status == 'REQUEST_DENIED':
                raise DrivingDistanceDeniedException(origin_lat, origin_lon,
                                                     dest_lat, dest_lon)
            elif status == 'OVER_QUERY_LIMIT':
                raise DrivingAPIQuotaException()
            else:
                raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                  dest_lat, dest_lon)
