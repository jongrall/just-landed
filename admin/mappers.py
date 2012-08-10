#!/usr/bin/env python

"""mappers.py: Module that defines admin map reduce mappers."""

import logging

from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets

import models.v1 as v1
import models.v2 as v2
import utils

@ndb.toplevel
def migrate_schema(v1_key):
    # Migrate the user, the flights and the alerts
    v1_key = ndb.Key(urlsafe=str(v1_key))

    @ndb.tasklet
    def migrate_user_txn():
        # Fetch the old user
        v1_user = yield v1_key.get_async()

        futs = []

        # Create the new user entity
        v2_user_fut = v2.iOSUser.get_or_insert_async(v1_user.key.string_id(),
                             created=v1_user.created, # Preserve creation date of original user
                             last_known_location=v1_user.last_known_location,
                             push_token=v1_user.push_token,
                             push_settings=v1_user.push_settings)
        futs.append(v2_user_fut)

        if v1_user.is_tracking_flights:
            # Get the alerts set for this user
            old_alerts = []
            if v1_user.alerts:
                old_alerts = yield ndb.get_multi_async(v1_user.alerts)

            # Get the flights this user is tracking
            old_flights = yield ndb.get_multi_async([f.flight for f in v1_user.tracked_flights])

            u_key = ndb.Key(v2.iOSUser, v1_user.key.string_id())

            for f in v1_user.tracked_flights:
                f_key = f.flight
                flight_id = f_key.string_id()
                flight_num = utils.flight_num_from_fa_flight_id(flight_id)
                u_f_num = f.user_flight_num
                old_reminders = [r for r in v1_user.reminders if r.flight == f_key]
                new_reminders = []
                matching_flight = None
                matching_alert = None

                for of in old_flights:
                    if of.key.string_id() == flight_id:
                        matching_flight = of
                        break

                for alert in old_alerts:
                    if alert.key.string_id() == flight_num:
                        matching_alert = alert
                        break

                for r in old_reminders:
                    new_reminders.append(v2.FlightReminder(fire_time=r.fire_time,
                        reminder_type=r.reminder_type,
                        sent=r.sent,
                        body=r.body))

                assert utils.is_valid_fa_flight_id(flight_id)
                assert utils.valid_flight_number(flight_num)
                assert utils.valid_flight_number(u_f_num)
                assert matching_flight
                assert matching_alert
                assert len(new_reminders <= 2)

                # Create the new flight
                v2_flight_fut = v2.FlightAwareTrackedFlight.get_or_insert_async(
                    flight_id,
                    parent=u_key,
                    created=matching_flight.created, # Preserve creation date of original flight
                    last_flight_data=matching_flight.last_flight_data,
                    orig_departure_time=matching_flight.orig_departure_time,
                    orig_flight_duration=matching_flight.orig_flight_duration,
                    alert_id=matching_alert.alert_id,
                    user_flight_num=u_f_num,
                    reminders=new_reminders)

                futs.append(v2_flight_fut)

        # Commit in parallel
        yield futs

    yield ndb.transaction_async(migrate_user_txn,
                                force_writes=True, # Works in read-only environment
                                xg=True)