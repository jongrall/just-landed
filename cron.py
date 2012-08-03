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
from config import on_development, config
from models import FlightAwareTrackedFlight, iOSUser, FlightAwareAlert, Flight
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
        # Figure out all the users tracking flights
        @ndb.tasklet
        def user_cbk(u):
            flight_ids = [f.flight.string_id() for f in u.tracked_flights]
            tups = [(u.key.string_id(), f_id) for f_id in set(flight_ids)]
            raise tasklets.Return(tups)

        # Build a list of all the (uuid, flight_id) pairs for users tracking flights
        users_qry = iOSUser.users_tracking_qry()
        user_flight_tups = yield users_qry.map_async(user_cbk)

        # Build a mapping of flight_ids to lists of users tracking those flight_ids
        user_flight_tups = [item for sublist in user_flight_tups for item in sublist]
        flight_user_map = {}

        for uuid, f_id in user_flight_tups:
            vals = flight_user_map.setdefault(f_id, [])
            vals.append(uuid)

        # Optimization: check if the flights are old in async batches
        def chunks(l, n):
            for i in xrange(0, len(l), n):
                yield l[i:i+n]

        old_flight_ids = []
        for batch in chunks(flight_user_map.keys(), 20): # Batch size 20
            @ndb.tasklet
            def check_if_old(flight_id):
                flight_num = utils.flight_num_from_fa_flight_id(flight_id)
                flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
                flight_ent = yield flight_key.get_async()

                if flight_ent:
                    flight = Flight.from_dict(flight_ent.last_flight_data)

                    try:
                        # Optimization: prevents overzealous checking
                        if flight.is_old_flight:
                            # We are certain it is old
                            raise OldFlightException(flight_number=flight_num,
                                                     flight_id=flight_id)
                        else:
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
            old_flight_ids.extend(results)

        old_flight_ids = [f_id for f_id in old_flight_ids if f_id is not None]

        # Optimization: batch untrack all the flights
        untrack_tasks = []
        for old_id in old_flight_ids:
            uuids = flight_user_map.get(old_id)
            untrack_tasks.extend([taskqueue.Task(params = {
                'flight_id' : old_id,
                'uuid' : uuid,
            }) for uuid in uuids])

        if untrack_tasks:
            taskqueue.Queue('untrack').add(untrack_tasks)


class SendRemindersWorker(BaseHandler):
    """Cron worker for sending unsent reminders."""
    @ndb.toplevel
    def get(self):
        # Get all users who have overdue reminders
        reminder_qry = iOSUser.users_with_overdue_reminders_qry()

        # TRANSACTIONAL REMINDER SENDING PER USER - ENSURE DUPE REMINDERS NOT SENT
        @ndb.transactional
        @ndb.tasklet
        def callback(u_key):
            user = yield u_key.get_async()
            unsent_reminders = user.get_unsent_reminders()
            outbox = []
            now = datetime.utcnow()
            # max_age = now - timedelta(seconds=config['max_reminder_age'])

            for r in unsent_reminders:
                if r.fire_time <= now:
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


class OutageCheckerWorker(BaseHandler):
    """Cron worker for checking whether possible outages have finished."""
    def get(self):
        possible_outages = [
            FlightAwareUnavailableError(),
            BingMapsUnavailableError(),
            GoogleDistanceAPIUnavailableError(),
            UrbanAirshipUnavailableError(),
            StackMobUnavailableError(),
            MixpanelUnavailableError(),
            GoogleAnalyticsUnavailableError(),
        ]

        client = memcache.Client()

        for e in possible_outages:
            error_name = type(e).__name__
            error_cache_key = utils.service_error_cache_key(e)
            retries = 0
            send_outage_over_sms = False
            outage_start_date = None
            last_error_date = None

            while retries < 20: # Retry loop for CAS
                report = client.gets(error_cache_key)
                if not report or not report['alert_sent']:
                    break # No need to detect finished outage
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

                       if client.cas(error_cache_key, report):
                           send_outage_over_sms = True
                           break # Write was successful
                       else:
                           retries += 1
                    else:
                        break # Outage in progress, not over

            if send_outage_over_sms:
                now = datetime.utcnow()
                last_error_seconds_ago = abs(now - last_error_date).total_seconds()
                outage_duration = abs(last_error_date - outage_start_date).total_seconds()
                utils.sms_alert_admin("[%s] Outage over.\n%s stopped %s ago. Outage lasted %s." %
                                    (datetime.now(utils.Pacific).strftime('%T'),
                                    error_name,
                                    utils.pretty_time_interval(last_error_seconds_ago),
                                    utils.pretty_time_interval(outage_duration)))