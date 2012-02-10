#!/usr/bin/python

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json

from google.appengine.api import memcache

from config import config
from api_exceptions import *

import utils
from models import Airport

class FlightDataSource (object):

    @classmethod
    def base_url(cls):
        pass

    @classmethod
    def api_key_mapping(cls):
        pass

    def airport_info(self, icao_code="", iata_code=""):
        pass

    def register_alert_endpoint(self, url, **kwargs):
        pass

    def flight_info(self, flight_id, **kwargs):
        pass

    def lookup_flights(self, flight_number, **kwargs):
        pass

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass


class FlightAwareSource (FlightDataSource):

    @classmethod
    def base_url(cls):
        return "http://flightxml.flightaware.com/json/FlightXML2/"

    @classmethod
    def api_key_mapping(cls):
        return config['flightaware']['key_mapping']

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url(),
            username=config['flightaware']['username'],
            password=config['flightaware']['key'])

    def airport_info(self, icao_code="", iata_code=""):
        """Looks up information about an airport using its ICAO or IATA code"""
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
                                                      self.api_key_mapping())

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

        # TODO(jon): Cache entire flight info dict

        # Find the flight
        flights = self.lookup_flights(flight_number)
        matching_flights = [f for f in flights if f['flightID'] == flight_id]

        if not matching_flights:
            # Probably tracking an old flight
            raise OldFlightException(flight_number=flight_number,
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
            info = utils.map_dict_keys(info, self.api_key_mapping())

            if not memcache.set(airline_info_key, info):
                logging.error("Unable to cache airline flight info!")
            flight_info.update(info)

        # If in flight, get flight path etc.
        if utils.is_in_flight(flight_info):
            inflight_info_key = "%s-inflight_info-%s" % (self.__class__.__name__,
                                                        flight_number)
            inflight_info = memcache.get(inflight_info_key)

            if inflight_info is not None:
                # Add in the inflight info
                flight_info.update(inflight_info)
            else:
                resp = self.conn.request_get('/InFlightInfo',
                                             args={'ident': flight_number})
                # Turn the JSON response into a dict
                result = json.loads(resp['body'])

                if result.get('error'):
                    raise MissingInflightInfoException(flight_number)

                # Filter & map the result
                fields = config['flightaware']['inflight_info_fields']
                info = result['InFlightInfoResult']
                info = utils.sub_dict_strict(info, fields)
                info = utils.map_dict_keys(info, self.api_key_mapping())

                # Round latitude
                info['latitude'] = utils.round_coord(info['latitude'])
                info['longitude'] = utils.round_coord(info['longitude'])

                # Convert waypoints
                waypoints = info['waypoints'].split()
                formatted_waypoints = []
                for lat, lon in zip(waypoints[::2], waypoints[1::2]):
                    formatted_waypoints.append(
                        '%f,%f' % (utils.round_coord(float(lat)),
                                  utils.round_coord(float(lon))))

                # Reduce the number of waypoints
                formatted_waypoints = utils.sample_waypoints(formatted_waypoints)
                info['waypoints'] = '|'.join(formatted_waypoints)

                # Cache the result
                if not memcache.set(inflight_info_key, info,
                            config['flightaware']['inflight_info_cache_time']):
                    logging.error("Unable to cache inflight info!")
                flight_info.update(info)

            # Get historical flight path
            flight_path_key = "%s-historical_flight_track-%s" % (self.__class__.__name__,
                                                                 flight_id)
            flight_path = memcache.get(flight_path_key)

            if flight_path is not None:
                # Add in the flight path
                flight_info.update(flight_path)
            else:
                resp = self.conn.request_get('/GetHistoricalTrack',
                                             args={'faFlightID': flight_id})
                # Turn the JSON response into a dict
                result = json.loads(resp['body'])

                if result.get('error'):
                    raise MissingFlightPathException(flight_id)

                # Filter & map the result
                fields = config['flightaware']['inflight_info_fields']
                path_info = result['GetHistoricalTrackResult']['data']
                points = []
                for p in path_info:
                    points.append(
                        '%f,%f' % (utils.round_coord(p['latitude']),
                        utils.round_coord(p['longitude']))
                    )

                # Reduce the number of path points
                points = utils.sample_waypoints(points)
                path_info = {'flightPath': '|'.join(points)}
                flight_info.update(path_info)

                # Cache the result
                if not memcache.set(flight_path_key, path_info,
                            config['flightaware']['flight_path_cache_time']):
                    logging.error("Unable to cache flight path info!")

        flight_info['mapUrl'] = utils.map_url(flight_info)
        flight_info['status'] = utils.flight_status(flight_info)
        flight_info['detailedStatus'] = utils.detailed_status(flight_info)

        # Keep only desired fields, move others
        flight_info['origin']['city'] = flight_info['originCity']
        flight_info['origin']['name'] = flight_info['originName']
        flight_info['origin']['terminal'] = flight_info['originTerminal']
        flight_info['destination']['city'] = flight_info['destinationCity']
        flight_info['destination']['name'] = flight_info['destinationName']
        flight_info['destination']['terminal'] = flight_info['destinationTerminal']
        flight_info['destination']['bag_claim'] = flight_info['bagClaim']
        return flight_info


    def lookup_flights(self, flight_number, **kwargs):
        """Looks up information about upcoming flights using a flight number."""
        # First check to see if the flight information is cached
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
                flights = [utils.map_dict_keys(f, self.api_key_mapping())
                           for f in flights]

                # Filter out old flights
                flights = [f for f in flights if not utils.is_old_flight(f)]

                # Sort by departure date (earliest first)
                flights.sort(key=lambda f: f['scheduledDepartureTime'])

                # Re-insert formatted flight number
                for f in flights:
                    f['flightNumber'] = flight_number
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


class DrivingTimeDataSource (object):

    @classmethod
    def base_url(cls):
        pass

    def driving_time(origin_lat, origin_lon, dest_lat, dest_lon):
        pass


class GoogleDistanceSource (DrivingTimeDataSource):

    @classmethod
    def base_url(cls):
        return 'http://maps.googleapis.com/maps/api/distancematrix'

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url(),
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
            result = json.loads(resp['body'])
            status = result['status']

            if status == 'OK':
                if result['rows'] and result['rows'][0]['elements']:
                    time = result['rows'][0]['elements'][0]['duration']['value']
                    if not memcache.set(driving_cache_key, time):
                        logging.error("Unable to cache driving time!")
                    return time
                else:
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

