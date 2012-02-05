import logging
import json

from lib import webapp2 as webapp

from data_sources import FlightAwareSource
source = FlightAwareSource()

import utils
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
    def get(self, flight_id):
        self.respond('Tracking %s goes here.' % flight_id)


class SearchHandler(BaseAPIHandler):
    def get(self, flight_number):
        flight_number = utils.valid_flight_number(flight_number)
        if not flight_number:
            raise InvalidFlightNumber()

        flights = source.lookup_flights(flight_number)
        self.respond(flights)

class UntrackHandler(BaseAPIHandler):
    def get(self, flight_id):
        self.respond('Untrack %s goes here.' % flight_id)

class AlertHandler(BaseAPIHandler):
    def post(self):
        self.respond('Alert handler goes here.')