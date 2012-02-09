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

    def flight_info(self, flight_number, **kwargs):
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
        pass

    def register_alert_endpoint(self, url, **kwargs):
        pass

    def flight_info(self, flight_number, **kwargs):
        pass

    def lookup_flights(self, flight_number, **kwargs):
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
                raise FlightNotFoundException()
            else:
                flights = flights['FlightInfoExResult']['flights']

                # Keep a subset of the response fields
                desired_fields = config['flightaware']['flight_info_fields']
                flights = [utils.sub_dict_strict(f, desired_fields)
                           for f in flights]

                # Map the response dict keys
                flights = [utils.map_dict_keys(f, self.api_key_mapping())
                           for f in flights]

                # Filter out old flights
                flights = [f for f in flights if not utils.is_old_flight(f)]

                # Sort by departure date (earliest first)
                flights.sort(key=lambda f: f['scheduledDepartureTime'])

                # Convert ICAO airport codes to IATA codes
                for f in flights:
                    f['flightNumber'] = flight_number
                    f['origin'] = utils.icao_to_iata(f['origin']) or f['origin']
                    f['destination'] = utils.icao_to_iata(f['destination']) or \
                                       f['destination']

            if not memcache.set(memcache_key, flights, 10800):
                logging.error("Unable to cache lookup response!")
            return flights

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass