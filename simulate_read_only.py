"""simulate_read_only.py: Utilities for simulating readonly mode on devserver."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Little Details LLC"
__email__ = "jon@littledetails.net"

from google.appengine.api.capabilities import CapabilitySet

_simulate_writes_disabled = False

def datastore_writes_enabled():
    actually_disabled = not CapabilitySet('datastore_v3', capabilities=['write']).is_enabled()
    return not (_simulate_writes_disabled or actually_disabled)

def simulate_datastore_readonly():
    from google.appengine.runtime.apiproxy_errors import CapabilityDisabledError
    from google.appengine.api import apiproxy_stub_map

    global _simulate_writes_disabled
    _simulate_writes_disabled = True

    def hook(service, call, request, response):
        assert(service == 'datastore_v3')
        if call in ('Put', 'Delete'):
            raise CapabilityDisabledError('Datastore is in read-only mode.')

    apiproxy_stub_map.apiproxy.GetPreCallHooks().Push('readonly_datastore', hook, 'datastore_v3')