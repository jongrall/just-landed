import logging
import json

from lib import webapp2 as webapp

from data_sources import FlightAwareSource
source = FlightAwareSource()

import utils
from config import config
from api_exceptions import *


class BaseAPIHandler(webapp.RequestHandler):
    def handle_exception(self, exception, debug):
        self.respond({'error' : exception.message or 'An error occurred.'})
        if hasattr(exception, 'code'):
            if exception.code == 500:
                # Only log 500s as exceptions
                logging.exception(exception)
            else:
                # Log informational
                logging.info(exception)
            self.response.set_status(exception.code)
        else:
            logging.exception(exception)
            self.response.set_status(500)

    def respond(self, response_dict):
        if self.request.GET.get('debug'):
            # Pretty print JSON
            formatted_resp = json.dumps(response_dict, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            self.response.write(json.dumps(response_dict))

class TrackHandler(BaseAPIHandler):
    def get(self, flight_number, flight_id):
        #self.respond('Tracking %s goes here.' % flight_id)
        info = source.flight_info(flight_id=flight_id,
                                  flight_number=flight_number)

        push = self.request.params.get('push')
        begin_track = self.request.params.get('begin_track')

        if push and begin_track:
            # TODO(jon): Register the client's UDID for push notifications
            pass

        latitude = self.request.params.get('latitude')
        longitude = self.request.params.get('longitude')

        if latitude and longitude:
            # TODO(jon): Lookup the driving time & distance to the airport
            pass

        info = utils.sub_dict_select(info, config['track_fields'])
        self.respond(info)

class SearchHandler(BaseAPIHandler):
    def get(self, flight_number):
        flight_number = utils.valid_flight_number(flight_number)
        if not flight_number:
            raise InvalidFlightNumber(flight_number)

        flights = source.lookup_flights(flight_number)
        self.respond(flights)

class UntrackHandler(BaseAPIHandler):
    def get(self, flight_id):
        self.respond('Untrack %s goes here.' % flight_id)

class AlertHandler(BaseAPIHandler):
    def post(self):
        self.respond('Alert handler goes here.')