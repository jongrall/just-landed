#!/usr/bin/env python

"""cron.py: Handlers for cron jobs."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
from datetime import datetime, timedelta

from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from main import BaseHandler
from config import config
from models.v2 import FlightAwareTrackedFlight
from api.v1.data_sources import FlightAwareSource
from custom_exceptions import *
from notifications import LeaveSoonAlert, LeaveNowAlert
import reporting
from reporting import report_event, report_event_transactionally
import utils

source = FlightAwareSource()
reminder_types = config['reminder_types']

class UntrackOldFlightsWorker(BaseHandler):
    """Cron worker for untracking old flights (efficiently)."""
    @ndb.toplevel
    def get(self):
        # Only do something if the datastore allows writes
        if not config['maintenance_in_progress'] and utils.datastore_writes_enabled():
            # Figure out which flights are old and who is tracking them
            definitely_old, maybe_old = yield FlightAwareTrackedFlight.old_flight_keys()
            flight_ids_to_check = list(set([f_key.string_id() for f_key in maybe_old]))

            # Optimization: check if the flights are old in async batches
            old_flight_ids = []

            for batch in utils.chunks(flight_ids_to_check, 20): # Batch size 20
                @ndb.tasklet
                def check_if_old(flight_id):
                    flight_num = utils.flight_num_from_fa_flight_id(flight_id)
                    try:
                        # Could be old, let's check
                        yield source.flight_info(flight_id=flight_id,
                                                 flight_number=flight_num)
                    except Exception as e:
                        # If we see one of these exceptions, we should untrack the flight
                        untrack_with_exceptions = (OldFlightException,
                                                    InvalidFlightNumberException,
                                                    FlightNotFoundException,
                                                    AssertionError)
                        if isinstance(e, untrack_with_exceptions):
                            raise tasklets.Return(flight_id)

                results = yield [check_if_old(f_id) for f_id in batch]
                old_flight_ids.extend([f_id for f_id in results if f_id is not None])

            # Optimization: batch untrack all the flights
            definitely_old.extend([f_key for f_key in maybe_old if f_key.string_id() in old_flight_ids])
            untrack_tasks = []
            for old_flight_key in definitely_old:
                untrack_tasks.append(taskqueue.Task(params = {
                    'flight_id' : old_flight_key.string_id(),
                    'uuid' : old_flight_key.parent().string_id(), # The user id
                }))

            if untrack_tasks:
                logging.info('UNTRACKING %d OLD FLIGHTS' % len(untrack_tasks))
                for task_batch in utils.chunks(untrack_tasks, 100): # Batch size 100 is max
                    taskqueue.Queue('untrack').add(task_batch)


class SendRemindersWorker(BaseHandler):
    """Cron worker for sending unsent reminders."""
    @ndb.toplevel
    def get(self):
        # Only do something if the datastore allows writes
        if not config['maintenance_in_progress'] and utils.datastore_writes_enabled():
            # Get all the flights with overdue reminders
            reminder_qry = FlightAwareTrackedFlight.flights_with_overdue_reminders_qry()

            # TRANSACTIONAL SENDING PER USER PER FLIGHT ENSURES DUPES REMINDERS NOT SENT
            @ndb.transactional
            @ndb.tasklet
            def callback(f_key):
                u_key = f_key.parent()
                user, flight = yield ndb.get_multi_async([u_key, f_key])

                if flight: # Only proceed if the flight is still being tracked
                    if not user: # Every flight must have a user
                        f_id = f_key.string_id()
                        error = OrphanedFlightError(flight_id=f_id)
                        logging.exception(error) # Don't throw, just log
                        utils.sms_report_exception(error)
                        raise tasklets.Return()

                    elif not user.push_enabled: # Only send reminders to users with push enabled
                        flight.reminders = [] # Remove the reminders from the flight
                        yield flight.put_async()
                        raise tasklets.Return()

                    outbox = []
                    now = datetime.utcnow()
                    unsent_reminders = flight.get_unsent_reminders()

                    for r in unsent_reminders:
                        if r.fire_time <= now:
                            # Max 5 transactional tasks per txn
                            if len(outbox) <= 5 and user.wants_notification_type(r.reminder_type):
                                r.sent = True # Mark sent
                                if r.reminder_type == reminder_types.LEAVE_SOON:
                                    outbox.append(LeaveSoonAlert(user.push_token, r.body))
                                else:
                                    outbox.append(LeaveNowAlert(user.push_token, r.body))
                    if outbox:
                        yield flight.put_async() # Save the changes to the flight reminders
                        for r in outbox:
                            r.push(_transactional=True) # Transactional push
                            if isinstance(r, LeaveSoonAlert):
                                report_event_transactionally(reporting.SENT_LEAVE_SOON_NOTIFICATION)
                            else:
                                report_event_transactionally(reporting.SENT_LEAVE_NOW_NOTIFICATION)

            yield reminder_qry.map_async(callback, keys_only=True)


class ClearOrphanedAlertsWorker(BaseHandler):
    """Cron worker for clearing orphaned FlightAware alerts."""
    @ndb.toplevel
    def get(self):
        # Only do something if the datastore allows writes
        if not config['maintenance_in_progress'] and utils.datastore_writes_enabled():
            alerts = yield source.get_all_alerts()

            # Get all the valid alert ids
            def eligible_alert(a):
                # Eligible for deletion if created at least an hour ago
                # Prevents alerts that were just created in a transaction from being cleared when cron runs
                alert_created = a.get('alert_created')
                if not alert_created or not isinstance(alert_created, (int, long)):
                    return False
                hour_ago = datetime.utcnow() - timedelta(hours=1)
                return datetime.utcfromtimestamp(alert_created) < hour_ago

            alerts = [a for a in alerts if eligible_alert(a)]
            alert_ids = [alert.get('alert_id') for alert in alerts]
            valid_alert_ids = [alert_id for alert_id in alert_ids if isinstance(alert_id, (int, long))]

            # Figure out which ones are no longer in use
            orphaned_alerts = []
            for batch in utils.chunks(valid_alert_ids, 20): # Batch size 20
                in_use_flags = yield [FlightAwareTrackedFlight.flight_alert_in_use(alert_id) for alert_id in batch]
                results = zip(batch, in_use_flags)

                for alert_id, in_use in results:
                    if not in_use: # There is no flight matching that alert
                        orphaned_alerts.append(alert_id)

            # Do the removal
            if orphaned_alerts:
                logging.info('DELETING %d ORPHANED ALERTS' % len(orphaned_alerts))
                yield source.delete_alerts(orphaned_alerts, orphaned=True)


class OutageCheckerWorker(BaseHandler):
    """Cron worker for checking whether possible outages have finished."""
    def get(self):
        possible_outages = [
            FlightAwareUnavailableError(),
            BingMapsUnavailableError(),
            GoogleDistanceAPIUnavailableError(),
            UrbanAirshipUnavailableError(),
            StackMobUnavailableError(),
            # MixpanelUnavailableError(), # No longer used
            GoogleAnalyticsUnavailableError(),
        ]

        client = memcache.Client()
        cache_keys = [utils.service_error_cache_key(e) for e in possible_outages]
        sms_to_send = []
        retries = 0

        while retries < 20: # Retry loop for CAS
            sms_to_send = [] # Reset sms
            report_map = client.get_multi(cache_keys, for_cas=True)
            to_set = {}

            for e in possible_outages:
                error_name = type(e).__name__
                error_cache_key = utils.service_error_cache_key(e)
                outage_start_date = None
                last_error_date = None

                report = report_map.get(error_cache_key)
                if not report or not report['alert_sent']:
                    continue # Skip to the next error, nothing to do yet
                else:
                    # An alert was previously sent for this type of outage
                    error_dates = report['error_dates']
                    outage_start_date = report['outage_start_date']
                    error_dates = sorted(error_dates)
                    now = datetime.utcnow()
                    last_error_date = error_dates[-1]

                    if (len(error_dates) == 0 or
                       last_error_date < now - timedelta(seconds=config['outage_over_wait'])):
                       # Outage is over, prime system to detect another outage
                       report['alert_sent'] = False
                       report['outage_start_date'] = None
                       to_set[error_cache_key] = report

                       # Record that we need to send an sms for this outage
                       last_error_seconds_ago = abs(now - last_error_date).total_seconds()
                       outage_duration = abs(last_error_date - outage_start_date).total_seconds()
                       outage_end_date = datetime.now(utils.Pacific) - timedelta(seconds=last_error_seconds_ago)
                       sms_to_send.append("[%s] Outage over.\n%s stopped. Outage lasted %s." %
                                              (outage_end_date.strftime('%T'),
                                              error_name,
                                              utils.pretty_time_interval(outage_duration)))
                    else:
                        continue # Outage in progress, not over

            if not(to_set) or not(client.cas_multi(to_set)): # cas_multi returns empty list on success
                break # Successful
            else:
                retries += 1

        for sms in sms_to_send:
            utils.sms_alert_admin(sms)