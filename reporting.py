#!/usr/bin/python

"""reporting.py: This module defines functions for doing deferred server-side
event tracking and reporting to any 3rd party HTTP/REST based reporting service.
Currently it supports reporting events to Mixpanel. Supports basic counters as well
as arbitrary keywords / params supported by the third party.

Event reporting work is deferred to a reporting taskqueue so the impact to the running
app is minimal. A future version could perhaps use memcache to store events and then
harvest them on a cron periodically to batch events to the 3rd party. This isn't
necessary at small scale however.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import base64
import json
import logging

from google.appengine.api import taskqueue
from google.appengine.api import urlfetch
from google.appengine.api.urlfetch import DownloadError

from main import BaseHandler
from config import config, on_local, on_staging
from custom_exceptions import *
import utils

debug_reporting = on_local() and False

###############################################################################
"""Flight Counters"""
###############################################################################

NEW_FLIGHT = 'Flight.NewFlight'
FLIGHT_TAKEOFF = 'Flight.Takeoff'
FLIGHT_LANDED = 'Flight.Landed'
FLIGHT_CANCELED = 'Flight.Canceled'
FLIGHT_DIVERTED = 'Flight.Diverted'
FLIGHT_CHANGE = 'Flight.Change'

###############################################################################
"""Cron Counters"""
###############################################################################

UNTRACKED_OLD_FLIGHT = 'Cron.UntrackedOldFlight'
SENT_LEAVE_SOON_NOTIFICATION = 'Cron.SentLeaveSoon'
SENT_LEAVE_NOW_NOTIFICATION = 'Cron.SentLeaveNow'
DELETED_ORPHANED_ALERT = 'Cron.DeletedOrphanedAlert'

###############################################################################
"""3rd Party API Usage Counters"""
###############################################################################

FA_AIRPORT_INFO = 'FlightAware.AirportInfo'
FA_AIRLINE_FLIGHT_INFO = 'FlightAware.AirlineFlightInfo'
FA_FLIGHT_INFO_EX = 'FlightAware.FlightInfoEx'
FA_SET_ALERT = 'FlightAware.SetAlert'
FA_GET_ALERTS = 'FlightAware.GetAlerts'
FA_DELETED_ALERT = 'FlightAware.DeletedAlert'
FA_FLIGHT_ALERT_CALLBACK = 'FlightAware.AlertCallback'
GOOG_FETCH_DRIVING_TIME = 'Google.DrivingTime'
BING_FETCH_DRIVING_TIME = 'Bing.DrivingTime'

###############################################################################
"""Reporting Service"""
###############################################################################

class ReportingService(object):
    """Defines a 3rd party event reporting service."""
    def report(self, event_name, **properties):
        """Report a single event with optional properties."""
        pass


class MixpanelService(ReportingService):
    def __init__(self):
        self._report_url = 'https://api.mixpanel.com/track/?data='

        if on_local():
            self._token = config['mixpanel']['development']['token']
        elif on_staging():
            self._token = config['mixpanel']['staging']['token']
        else:
            self._token = config['mixpanel']['production']['token']

    def report(self, event_name, **properties):
        assert isinstance(event_name, basestring) and len(event_name)

        if debug_reporting:
            logging.info('Reporting event: %s' % event_name)

        # Add in the token
        properties['token'] = self._token
        properties['distinct_id'] = 'GAE Server'

        params = {
            'event' : event_name,
            'properties' : properties,
        }

        data = base64.b64encode(json.dumps(params))
        url = self._report_url + data

        try:
            result = urlfetch.fetch(url=url, validate_certificate=True)
            if result.status_code != 200:
                # Log, don't raise
                logging.exception(ReportEventFailedException(status_code=result.status_code,
                                                             event_name=event_name))
        except DownloadError:
            utils.sms_report_exception(MixpanelUnavailableError())

###############################################################################
"""Report Helper Methods"""
###############################################################################

def _defer_report(event_name, transactional, **properties):
    properties['event_name'] = event_name
    report_task = taskqueue.Task(params=properties)
    taskqueue.Queue('report-event').add(report_task, transactional=transactional)


def report_event(event_name, **properties):
    _defer_report(event_name, False, **properties)


def report_event_transactionally(event_name, **properties):
    _defer_report(event_name, True, **properties)

###############################################################################
"""Reporting Handler"""
###############################################################################

service = MixpanelService()

class ReportWorker(BaseHandler):
    """Deferred work when reporting an event."""
    def post(self):
        # Disable retries
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        params = self.request.params
        event_name = params.get('event_name')

        assert isinstance(event_name, basestring) and len(event_name)
        properties = {}
        for k in params.keys():
            if k != 'event_name':
                properties[k] = params[k]

        service.report(event_name, **properties)