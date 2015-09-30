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
__copyright__ = "Copyright 2012, Little Details LLC"
__email__ = "jon@littledetails.net"

import logging
import base64
import json

from google.appengine.api import taskqueue
from google.appengine.api import urlfetch
from google.appengine.ext import ndb

from main import BaseHandler
from config import config, on_development, on_staging, google_analytics_account, domain_name
from custom_exceptions import *
import utils

from lib.pyga.requests import Tracker as GoogleAnalyticsTracker
from lib.pyga.entities import Visitor as GoogleAnalyticsVisitor
from lib.pyga.entities import Event as GoogleAnalyticsEvent
from lib.pyga.entities import Session as GoogleAnalyticsSession

# Enable to log informational messages about reported events
debug_reporting = on_development() and False

###############################################################################
# Flight Counters
###############################################################################

FLIGHT_TAKEOFF = 'Flight.Takeoff'
FLIGHT_LANDED = 'Flight.Landed'
FLIGHT_CANCELED = 'Flight.Canceled'
FLIGHT_DIVERTED = 'Flight.Diverted'
FLIGHT_CHANGE = 'Flight.Change'
FLIGHT_TERMINAL_CHANGE = 'Flight.TerminalChange'

###############################################################################
# Cron Counters
###############################################################################

UNTRACKED_OLD_FLIGHT = 'Cron.UntrackedOldFlight'
SENT_LEAVE_SOON_NOTIFICATION = 'Cron.SentLeaveSoon'
SENT_LEAVE_NOW_NOTIFICATION = 'Cron.SentLeaveNow'
DELETED_ORPHANED_ALERT = 'Cron.DeletedOrphanedAlert'

###############################################################################
# 3rd Party API Usage Counters
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
HERE_ROUTES_FETCH_DRIVING_TIME = 'Here.DrivingTime'

###############################################################################
# Reporting Service
###############################################################################

class ReportingService(object):
    """Defines a 3rd party event reporting service."""
    def report(self, event_name, **properties):
        """Report a single event with optional properties."""
        pass


class MixpanelService(ReportingService):
    """A concrete implementation of an event reporting service. Service is
    provided by Mixpanel.

    """
    def __init__(self):
        super(MixpanelService, self).__init__()
        self._report_url = 'http://api.mixpanel.com/track/?data=' # HTTPS supported but not used

        if on_development():
            self._token = config['mixpanel']['development']['token']
        elif on_staging():
            self._token = config['mixpanel']['staging']['token']
        else:
            self._token = config['mixpanel']['production']['token']

    def report(self, event_name, **properties):
        """Reports an event to Mixpanel."""
        assert isinstance(event_name, basestring) and len(event_name)

        if debug_reporting:
            logging.info('Reporting event: %s', event_name)

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
            result = urlfetch.fetch(url=url, validate_certificate=url.startswith('https'))
            if result.status_code != 200:
                # Log, don't raise
                logging.exception(ReportEventFailedException(status_code=result.status_code,
                                                             event_name=event_name))

        # Reliability: don't allow reporting exceptions to propagate
        except Exception as e:
            utils.report_service_error(MixpanelUnavailableError())
            logging.exception(e)


class GoogleAnalyticsService(ReportingService):
    """A concrete implementation of an event reporting service. Service is
    provided by Google Analytics."""
    def __init__(self):
        super(GoogleAnalyticsService, self).__init__()
        self._visitor = GoogleAnalyticsVisitor()
        self._eventClass = GoogleAnalyticsEvent
        self._tracker = GoogleAnalyticsTracker(account_id=google_analytics_account(),
                                                domain_name=domain_name())

    def report(self, event_name, **properties):
        """Reports an event to Google Analytics."""
        assert isinstance(event_name, basestring) and len(event_name)
        if debug_reporting:
            logging.info('Reporting event: %s', event_name)

        props = (properties and unicode(properties)) or None
        event = self._eventClass(category='GAE Server',
                                 action=event_name,
                                 label=props,
                                 noninteraction=True) # Shouldn't impact bounce rate

        try:
            self._tracker.track_event(event, GoogleAnalyticsSession(), self._visitor)

        # Reliability: don't allow reporting exceptions to propagate
        except Exception as e:
            utils.report_service_error(GoogleAnalyticsUnavailableError())
            logging.exception(e)

###############################################################################
# Events Stored in the Datastore
###############################################################################

class _Event(ndb.Model):
    """A logged event of interest.

    Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : When the event was logged.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)

    @classmethod
    def ensure_unique(cls):
        """Returns whether or not events of this type should be unique in the datastore."""
        return False


class _UserEvent(_Event):
    """A logged user event of interest.

    Not intended to be used directly, but rather subclassed.

    Fields:
    - `user_id` : The id of the user who triggered the event.
    - `datasource` : The datasource that was searched (FlightAware, etc.)

    """
    user_id = ndb.StringProperty(required=True)
    datasource = ndb.StringProperty('source', choices=['FlightAware, FlightStats'], default='FlightAware')


class FlightSearchEvent(_UserEvent):
    """Event: A user searched for a flight.

    Fields:
    - `flight_number` : The flight number that the user searched for.

    """
    flight_number = ndb.StringProperty('f_num', required=True)


class FlightSearchMissEvent(FlightSearchEvent):
    """Event: A flight search failed to find a match."""


class FlightTrackedEvent(_UserEvent):
    """Event: A user began tracking a flight.

    Fields:
    - `flight_id` : The id of the flight that the user tracked.

    """
    flight_id = ndb.StringProperty(required=True)


class UserAtAirportEvent(_UserEvent):
    """Event: A user went to the airport.

    Fields:
    - `flight_id` : The id of the flight that the user was tracking.
    - `airport` : The IATA/ICAO identifier of the airport the user was at.

    """
    flight_id = ndb.StringProperty(required=True)
    airport = ndb.StringProperty(required=True)

    @classmethod
    def ensure_unique(cls):
        return True # We only want to see one event for the user at the airport

    @classmethod
    def unique_key(cls, **kwargs):
        return '_'.join([kwargs['user_id'], kwargs['flight_id']])

###############################################################################
# Report Helper Methods
###############################################################################

def _defer_report(event_name, transactional, **properties):
    """Defers reporting an event and properties using the Taskqueue service.
    Specifying transactional ensures the event only gets added to the queue if
    the enclosing transaction is committed successfully.

    """
    properties['event_name'] = event_name
    report_task = taskqueue.Task(params=properties)
    taskqueue.Queue('report-event').add(report_task, transactional=transactional)

def report_event(event_name, **properties):
    """Adds an event to the taskqueue for deferred reporting."""
    _defer_report(event_name, False, **properties)

def report_event_transactionally(event_name, **properties):
    """Adds an event to the taskqueue for deferred reporting. Event is only
    enqueued if the enclosing transaction is committed successfully.

    """
    _defer_report(event_name, True, **properties)

###############################################################################
# Datastore Report Helper Methods
###############################################################################

def get_class(class_path):
    parts = class_path.split('.')
    module = ".".join(parts[:-1])
    m = __import__( module )
    for comp in parts[1:]:
        m = getattr(m, comp)
    return m

def _defer_ds_log(event_cls, transactional, **properties):
    """Defers logging an event and properties to the datastore using the
    Taskqueue service. Specifying transactional ensures the event only gets
    added to the queue if the enclosing transaction is committed successfully.

    """
    properties['event_class'] = '.'.join([event_cls.__module__, event_cls.__name__])
    report_task = taskqueue.Task(params=properties)
    taskqueue.Queue('log-event').add(report_task, transactional=transactional)

def log_event(event_cls, **properties):
    """Adds an event to the taskqueue for deferred logging to the datastore."""
    _defer_ds_log(event_cls, False, **properties)

def log_event_transactionally(event_cls, **properties):
    """Adds an event to the taskqueue for deferred logging to the datastore.
    Event is only enqueued if the enclosing transaction is committed successfully.

    """
    _defer_ds_log(event_cls, True, **properties)

###############################################################################
# Reporting Handlers
###############################################################################

service = GoogleAnalyticsService()

class ReportWorker(BaseHandler):
    """Worker that actually reports events to the 3rd party reporting service."""
    def post(self):
        # Reliability: disable retries, would rather lose events than have them
        # erroneously reported many times.
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


class DatastoreLogWorker(BaseHandler):
    """Worker that logs events to the datastore."""
    @ndb.toplevel
    def post(self):
        # Reliability: disable retries, would rather lose events than have them
        # erroneously reported many times.
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        params = dict(self.request.params)
        event_cls_path = params.get('event_class')
        event_cls = event_cls_path and get_class(event_cls_path)
        if not issubclass(event_cls, ndb.Model):
            raise EventClassNotFoundException(class_name=(event_cls_path or ''))

        del(params['event_class']) # Remove the event class from the args

        if event_cls.ensure_unique():
            try:
                event_id = event_cls.unique_key(**params)
            except KeyError:
                raise UnableToCreateUniqueEventKey(class_name=(event_cls_path or ''))
            # Transactionally get or insert the event
            yield event_cls.get_or_insert_async(event_id, **params)
        else:
            log_entity = event_cls(**params)
            yield log_entity.put_async() # Store the event in the datastore