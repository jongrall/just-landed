#!/usr/bin/python

"""cron.py: Handlers for cron jobs."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
from datetime import datetime, timedelta

from google.appengine.ext import ndb

from main import BaseHandler
from config import on_local, config
from models import FlightAwareTrackedFlight, iOSUser, FlightAwareAlert, Flight
from api.v1.data_sources import FlightAwareSource
from exceptions import *

import utils
import reporting
from reporting import report_event, report_event_transactionally
from notifications import LeaveSoonAlert, LeaveNowAlert

source = FlightAwareSource()
reminder_types = config['reminder_types']


class UntrackOldFlightsWorker(BaseHandler):
    """Cron worker for untracking old flights."""
    @ndb.toplevel
    def get(self):
        # Get all flights that are currently tracking
        flights = yield FlightAwareTrackedFlight.tracked_flights()

        while (yield flights.has_next_async()):
            f = flights.next()
            flight_id = f.key.string_id()
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)
            flight = Flight.from_dict(f.last_flight_data)

            try:
                # Optimization prevents overzealous checking
                if flight.is_old_flight:
                    # We are certain it is old
                    raise OldFlightException(flight_number=flight_num,
                                             flight_id=flight_id)
                elif flight.is_probably_old: # Based on est_arrival_time
                  # Probably old, just make sure (flight_info will yield OldFlightException)
                  yield source.flight_info(flight_id=flight_id,
                                           flight_number=flight_num)

                else:
                    # Do nothing for flights that aren't old or landed
                    continue

            except Exception as e:
                if isinstance(e, OldFlightException): # Only care about old flights
                    # We should untrack this flight for each user who was tracking it
                    user_keys_tracking = yield iOSUser.users_tracking_flight(flight_id)

                    # Generate the URL and API signature
                    url_scheme = (not on_local() and 'https') or 'http'
                    to_sign = self.uri_for('untrack', flight_id=flight_id)
                    sig = utils.api_query_signature(to_sign, client='Server')
                    untrack_url = self.uri_for('untrack',
                                                flight_id=flight_id,
                                                _full=True,
                                                _scheme=url_scheme)
                    ctx = ndb.get_context()
                    report_event(reporting.UNTRACKED_OLD_FLIGHT)

                    while (yield user_keys_tracking.has_next_async()):
                        u_key = user_keys_tracking.next()
                        headers = {'X-Just-Landed-UUID' : u_key.string_id(),
                                   'X-Just-Landed-Signature' : sig}

                        yield ctx.urlfetch(untrack_url,
                                           headers=headers,
                                           deadline=120,
                                           validate_certificate=not on_local())


class SendRemindersWorker(BaseHandler):
    """Cron worker for sending unsent reminders."""
    @ndb.toplevel
    def get(self):
        # Get all users who have overdue reminders
        user_keys = yield iOSUser.users_with_overdue_reminders()

        while (yield user_keys.has_next_async()):
            u_key = user_keys.next()

            @ndb.tasklet
            def send_txn():
                user = yield u_key.get_async()
                unsent_reminders = user.get_unsent_reminders()
                outbox = []
                now = datetime.utcnow()
                max_age = now - timedelta(seconds=config['max_reminder_age'])

                for r in unsent_reminders:
                    if ((max_age < r.fire_time <= now) or
                        (r.reminder_type == reminder_types.LEAVE_NOW and r.fire_time <= now)):
                        # Max 5 transactional tasks per txn
                        if len(outbox) < 6 and user.wants_notification_type(r.reminder_type):
                            r.sent = True # Mark sent
                            if r.reminder_type == reminder_types.LEAVE_SOON:
                                outbox.append(LeaveSoonAlert(user.push_token, r.body))
                            else:
                                outbox.append(LeaveNowAlert(user.push_token, r.body))
                if outbox:
                    yield user.put_async() # Save the changes to reminders
                    for r in outbox:
                        r.push(_transactional=True)
                        if isinstance(r, LeaveSoonAlert):
                            report_event_transactionally(reporting.SENT_LEAVE_SOON_NOTIFICATION)
                        else:
                            report_event_transactionally(reporting.SENT_LEAVE_NOW_NOTIFICATION)

            # TRANSACTIONAL REMINDER SENDING PER USER - ENSURE DUPE REMINDERS NOT SENT
            yield ndb.transaction_async(send_txn)


class ClearOrphanedAlertsWorker(BaseHandler):
    """Cron worker for clearing orphaned FlightAware alerts."""
    @ndb.toplevel
    def get(self):
        alerts = yield source.get_all_alerts()

        # Get all the valid alert ids
        alert_ids = [alert.get('alert_id') for alert in alerts]
        valid_alert_ids = [alert_id for alert_id in alert_ids if isinstance(alert_id, (int, long))]

        # Figure out which ones are no longer in use
        orphaned_alerts = []
        for alert_id in valid_alert_ids:
            alert = yield FlightAwareAlert.get_by_alert_id(alert_id)
            if not alert or not alert.is_enabled:
                orphaned_alerts.append(alert_id)

        # Do the removal
        if orphaned_alerts:
            logging.info('DELETING %d ORPHANED ALERTS' % len(orphaned_alerts))
            yield source.delete_alerts(valid_alert_ids, orphaned=True)