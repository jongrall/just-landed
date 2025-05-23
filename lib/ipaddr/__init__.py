#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#  Licensed to PSF under a Contributor Agreement.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.

"""A fast, lightweight IPv4/IPv6 manipulation library in Python.

This library is used to create/poke/manipulate IPv4 and IPv6 addresses
and networks.

"""

__version__ = 'branches/3144'

import struct

IPV4LENGTH = 32
IPV6LENGTH = 128


class AddressValueError(ValueError):
    """A Value Error related to the address."""


class NetmaskValueError(ValueError):
    """A Value Error related to the netmask."""


def ip_address(address, version=None):
    """Take an IP string/int and return an object of the correct type.

    Args:
        address: A string or integer, the IP address.  Either IPv4 or
          IPv6 addresses may be supplied; integers less than 2**32 will
          be considered to be IPv4 by default.
        version: An Integer, 4 or 6. If set, don't try to automatically
          determine what the IP address type is. important for things
          like ip_address(1), which could be IPv4, '0.0.0.1',  or IPv6,
          '::1'.

    Returns:
        An IPv4Address or IPv6Address object.

    Raises:
        ValueError: if the string passed isn't either a v4 or a v6
          address.

    """
    if version:
        if version == 4:
            return IPv4Address(address)
        elif version == 6:
            return IPv6Address(address)

    try:
        return IPv4Address(address)
    except (AddressValueError, NetmaskValueError):
        pass

    try:
        return IPv6Address(address)
    except (AddressValueError, NetmaskValueError):
        pass

    raise ValueError('%r does not appear to be an IPv4 or IPv6 address' %
                     address)


def ip_network(address, version=None):
    """Take an IP string/int and return an object of the correct type.

    Args:
        address: A string or integer, the IP network.  Either IPv4 or
          IPv6 networks may be supplied; integers less than 2**32 will
          be considered to be IPv4 by default.
        version: An Integer, if set, don't try to automatically
          determine what the IP address type is. important for things
          like ip_network(1), which could be IPv4, '0.0.0.1/32', or IPv6,
          '::1/128'.

    Returns:
        An IPv4Network or IPv6Network object.

    Raises:
        ValueError: if the string passed isn't either a v4 or a v6
          address. Or if the network has host bits set.

    """
    if version:
        if version == 4:
            return IPv4Network(address)
        elif version == 6:
            return IPv6Network(address)

    try:
        return IPv4Network(address)
    except (AddressValueError, NetmaskValueError):
        pass

    try:
        return IPv6Network(address)
    except (AddressValueError, NetmaskValueError):
        pass

    raise ValueError('%r does not appear to be an IPv4 or IPv6 network' %
                     address)


def ip_interface(address, version=None):
    """Take an IP string/int and return an object of the correct type.

    Args:
        address: A string or integer, the IP address.  Either IPv4 or
          IPv6 addresses may be supplied; integers less than 2**32 will
          be considered to be IPv4 by default.
        version: An Integer, if set, don't try to automatically
          determine what the IP address type is. important for things
          like ip_network(1), which could be IPv4, '0.0.0.1/32', or IPv6,
          '::1/128'.

    Returns:
        An IPv4Network or IPv6Network object.

    Raises:
        ValueError: if the string passed isn't either a v4 or a v6
          address.

    Notes:
        The IPv?Interface classes describe an Address on a particular
        Network, so they're basically a combination of both the Address
        and Network classes.
    """
    if version:
        if version == 4:
            return IPv4Interface(address)
        elif version == 6:
            return IPv6Interface(address)

    try:
        return IPv4Interface(address)
    except (AddressValueError, NetmaskValueError):
        pass

    try:
        return IPv6Interface(address)
    except (AddressValueError, NetmaskValueError):
        pass

    raise ValueError('%r does not appear to be an IPv4 or IPv6 network' %
                     address)


def v4_int_to_packed(address):
    """The binary representation of this address.

    Args:
        address: An integer representation of an IPv4 IP address.

    Returns:
        The binary representation of this address.

    Raises:
        ValueError: If the integer is too large to be an IPv4 IP
          address.
    """
    if address > _BaseV4._ALL_ONES:
        raise ValueError('Address too large for IPv4')
    return struct.pack('!I', address)


def v6_int_to_packed(address):
    """The binary representation of this address.

    Args:
        address: An integer representation of an IPv4 IP address.

    Returns:
        The binary representation of this address.
    """
    return struct.pack('!QQ', address >> 64, address & (2**64 - 1))


def _find_address_range(addresses):
    """Find a sequence of addresses.

    Args:
        addresses: a list of IPv4 or IPv6 addresses.

    Returns:
        A tuple containing the first and last IP addresses in the sequence.

    """
    first = last = addresses[0]
    for ip in addresses[1:]:
        if ip._ip == last._ip + 1:
            last = ip
        else:
            break
    return (first, last)

def _get_prefix_length(number1, number2, bits):
    """Get the number of leading bits that are same for two numbers.

    Args:
        number1: an integer.
        number2: another integer.
        bits: the maximum number of bits to compare.

    Returns:
        The number of leading bits that are the same for two numbers.

    """
    for i in range(bits):
        if number1 >> i == number2 >> i:
            return bits - i
    return 0

def _count_righthand_zero_bits(number, bits):
    """Count the number of zero bits on the right hand side.

    Args:
        number: an integer.
        bits: maximum number of bits to count.

    Returns:
        The number of zero bits on the right hand side of the number.

    """
    if number == 0:
        return bits
    for i in range(bits):
        if (number >> i) % 2:
            return i

def summarize_address_range(first, last):
    """Summarize a network range given the first and last IP addresses.

    Example:
        >>> summarize_address_range(IPv4Address('1.1.1.0'),
            IPv4Address('1.1.1.130'))
        [IPv4Network('1.1.1.0/25'), IPv4Network('1.1.1.128/31'),
        IPv4Network('1.1.1.130/32')]

    Args:
        first: the first IPv4Address or IPv6Address in the range.
        last: the last IPv4Address or IPv6Address in the range.

    Returns:
        The address range collapsed to a list of IPv4Network's or
        IPv6Network's.

    Raise:
        TypeError:
            If the first and last objects are not IP addresses.
            If the first and last objects are not the same version.
        ValueError:
            If the last object is not greater than the first.
            If the version is not 4 or 6.

    """
    if not (isinstance(first, _BaseAddress) and isinstance(last, _BaseAddress)):
        raise TypeError('first and last must be IP addresses, not networks')
    if first.version != last.version:
        raise TypeError("%s and %s are not of the same version" % (
                str(first), str(last)))
    if first > last:
        raise ValueError('last IP address must be greater than first')

    networks = []

    if first.version == 4:
        ip = IPv4Network
    elif first.version == 6:
        ip = IPv6Network
    else:
        raise ValueError('unknown IP version')

    ip_bits = first._max_prefixlen
    first_int = first._ip
    last_int = last._ip
    while first_int <= last_int:
        nbits = _count_righthand_zero_bits(first_int, ip_bits)
        current = None
        while nbits >= 0:
            addend = 2**nbits - 1
            current = first_int + addend
            nbits -= 1
            if current <= last_int:
                break
        prefix = _get_prefix_length(first_int, current, ip_bits)
        net = ip('%s/%d' % (str(first), prefix))
        networks.append(net)
        if current == ip._ALL_ONES:
            break
        first_int = current + 1
        first = ip_address(first_int, version=first._version)
    return networks

def _collapse_address_list_recursive(addresses):
    """Loops through the addresses, collapsing concurrent netblocks.

    Example:

        ip1 = IPv4Network('1.1.0.0/24')
        ip2 = IPv4Network('1.1.1.0/24')
        ip3 = IPv4Network('1.1.2.0/24')
        ip4 = IPv4Network('1.1.3.0/24')
        ip5 = IPv4Network('1.1.4.0/24')

        _collapse_address_list_recursive([ip1, ip2, ip3, ip4, ip5, ip6]) ->
          [IPv4Network('1.1.0.0/22'), IPv4Network('1.1.4.0/24')]

        This shouldn't be called directly; it is called via
          collapse_address_list([]).

    Args:
        addresses: A list of IPv4Network's or IPv6Network's

    Returns:
        A list of IPv4Network's or IPv6Network's depending on what we were
        passed.

    """
    ret_array = []
    optimized = False

    for cur_addr in addresses:
        if not ret_array:
            ret_array.append(cur_addr)
            continue
        if cur_addr in ret_array[-1]:
            optimized = True
        elif cur_addr == ret_array[-1].supernet().subnet()[1]:
            ret_array.append(ret_array.pop().supernet())
            optimized = True
        else:
            ret_array.append(cur_addr)

    if optimized:
        return _collapse_address_list_recursive(ret_array)

    return ret_array


def collapse_address_list(addresses):
    """Collapse a list of IP objects.

    Example:
        collapse_address_list([IPv4Network('1.1.0.0/24'),
                               IPv4Network('1.1.1.0/24')]) ->
                              [IPv4Network('1.1.0.0/23')]

    Args:
        addresses: A list of IPv4Network or IPv6Network objects.

    Returns:
        A list of IPv4Network or IPv6Network objects depending on what we
        were passed.

    Raises:
        TypeError: If passed a list of mixed version objects.

    """
    i = 0
    addrs = []
    ips = []
    nets = []

    # split IP addresses and networks
    for ip in addresses:
        if isinstance(ip, _BaseAddress):
            if ips and ips[-1]._version != ip._version:
                raise TypeError("%s and %s are not of the same version" % (
                        str(ip), str(ips[-1])))
            ips.append(ip)
        elif ip._prefixlen == ip._max_prefixlen:
            if ips and ips[-1]._version != ip._version:
                raise TypeError("%s and %s are not of the same version" % (
                        str(ip), str(ips[-1])))
            try:
                ips.append(ip.ip)
            except AttributeError:
                ips.append(ip.network_address)
        else:
            if nets and nets[-1]._version != ip._version:
                raise TypeError("%s and %s are not of the same version" % (
                        str(ip), str(ips[-1])))
            nets.append(ip)

    # sort and dedup
    ips = sorted(set(ips))
    nets = sorted(set(nets))

    while i < len(ips):
        (first, last) = _find_address_range(ips[i:])
        i = ips.index(last) + 1
        addrs.extend(summarize_address_range(first, last))

    return _collapse_address_list_recursive(sorted(
        addrs + nets, key=_BaseInterface._get_networks_key))

# backwards compatibility
CollapseAddrList = collapse_address_list

# Test whether this Python implementation supports byte objects that
# are not identical to str ones.
# We need to exclude platforms where bytes == str so that we can
# distinguish between packed representations and strings, for example
# b'12::' (the IPv4 address 49.50.58.58) and '12::' (an IPv6 address).
try:
    _compat_has_real_bytes = bytes is not str
except NameError: # <Python2.6
    _compat_has_real_bytes = False

def get_mixed_type_key(obj):
    """Return a key suitable for sorting between networks and addresses.

    Address and Network objects are not sortable by default; they're
    fundamentally different so the expression

        IPv4Address('1.1.1.1') <= IPv4Network('1.1.1.1/24')

    doesn't make any sense.  There are some times however, where you may wish
    to have ipaddr sort these for you anyway. If you need to do this, you
    can use this function as the key= argument to sorted().

    Args:
      obj: either a Network or Address object.
    Returns:
      appropriate key.

    """
    if isinstance(obj, _BaseInterface):
        return obj._get_networks_key()
    elif isinstance(obj, _BaseAddress):
        return obj._get_address_key()
    return NotImplemented

class _IPAddrBase(object):

    """The mother class."""

    def __index__(self):
        return self._ip

    def __int__(self):
        return self._ip

    def __hex__(self):
        return hex(self._ip)

    @property
    def exploded(self):
        """Return the longhand version of the IP address as a string."""
        return self._explode_shorthand_ip_string()

    @property
    def compressed(self):
        """Return the shorthand version of the IP address as a string."""
        return str(self)


class _BaseAddress(_IPAddrBase):

    """A generic IP object.

    This IP class contains the version independent methods which are
    used by single IP addresses.

    """

    def __init__(self, address):
        if (not (_compat_has_real_bytes and isinstance(address, bytes))
            and '/' in str(address)):
            raise AddressValueError(address)

    def __eq__(self, other):
        try:
            return (self._ip == other._ip
                    and self._version == other._version)
        except AttributeError:
            return NotImplemented

    def __ne__(self, other):
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq

    def __le__(self, other):
        gt = self.__gt__(other)
        if gt is NotImplemented:
            return NotImplemented
        return not gt

    def __ge__(self, other):
        lt = self.__lt__(other)
        if lt is NotImplemented:
            return NotImplemented
        return not lt

    def __lt__(self, other):
        if self._version != other._version:
            raise TypeError('%s and %s are not of the same version' % (
                    str(self), str(other)))
        if not isinstance(other, _BaseAddress):
            raise TypeError('%s and %s are not of the same type' % (
                    str(self), str(other)))
        if self._ip != other._ip:
            return self._ip < other._ip
        return False

    def __gt__(self, other):
        if self._version != other._version:
            raise TypeError('%s and %s are not of the same version' % (
                    str(self), str(other)))
        if not isinstance(other, _BaseAddress):
            raise TypeError('%s and %s are not of the same type' % (
                    str(self), str(other)))
        if self._ip != other._ip:
            return self._ip > other._ip
        return False

    # Shorthand for Integer addition and subtraction. This is not
    # meant to ever support addition/subtraction of addresses.
    def __add__(self, other):
        if not isinstance(other, int):
            return NotImplemented
        return ip_address(int(self) + other, version=self._version)

    def __sub__(self, other):
        if not isinstance(other, int):
            return NotImplemented
        return ip_address(int(self) - other, version=self._version)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, str(self))

    def __str__(self):
        return  '%s' % self._string_from_ip_int(self._ip)

    def __hash__(self):
        return hash(hex(long(self._ip)))

    def _get_address_key(self):
        return (self._version, self)

    @property
    def version(self):
        raise NotImplementedError('BaseIP has no version')


class _BaseInterface(_IPAddrBase):

    """A generic IP object.

    This IP class contains the version independent methods which are
    used by networks.

    """

    def __init__(self, address):
        self._cache = {}

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, str(self))

    def iterhosts(self):
        """Generate Iterator over usable hosts in a network.

           This is like __iter__ except it doesn't return the network
           or broadcast addresses.

        """
        cur = int(self.network_address) + 1
        bcast = int(self.broadcast_address) - 1
        while cur <= bcast:
            cur += 1
            yield ip_address(cur - 1, version=self._version)

    def __iter__(self):
        cur = int(self.network_address)
        bcast = int(self.broadcast_address)
        while cur <= bcast:
            cur += 1
            yield ip_address(cur - 1, version=self._version)

    def __getitem__(self, n):
        network = int(self.network_address)
        broadcast = int(self.broadcast_address)
        if n >= 0:
            if network + n > broadcast:
                raise IndexError
            return ip_address(network + n, version=self._version)
        else:
            n += 1
            if broadcast + n < network:
                raise IndexError
            return ip_address(broadcast + n, version=self._version)

    def __lt__(self, other):
        if self._version != other._version:
            raise TypeError('%s and %s are not of the same version' % (
                    str(self), str(other)))
        if not isinstance(other, _BaseInterface):
            raise TypeError('%s and %s are not of the same type' % (
                    str(self), str(other)))
        if self.network_address != other.network_address:
            return self.network_address < other.network_address
        if self.netmask != other.netmask:
            return self.netmask < other.netmask
        return False

    def __gt__(self, other):
        if self._version != other._version:
            raise TypeError('%s and %s are not of the same version' % (
                    str(self), str(other)))
        if not isinstance(other, _BaseInterface):
            raise TypeError('%s and %s are not of the same type' % (
                    str(self), str(other)))
        if self.network_address != other.network_address:
            return self.network_address > other.network_address
        if self.netmask != other.netmask:
            return self.netmask > other.netmask
        return False

    def __le__(self, other):
        gt = self.__gt__(other)
        if gt is NotImplemented:
            return NotImplemented
        return not gt

    def __ge__(self, other):
        lt = self.__lt__(other)
        if lt is NotImplemented:
            return NotImplemented
        return not lt

    def __eq__(self, other):
        try:
            return (self._version == other._version
                    and self.network_address == other.network_address
                    and int(self.netmask) == int(other.netmask))
        except AttributeError:
            if isinstance(other, _BaseAddress):
                return (self._version == other._version
                        and self._ip == other._ip)

    def __ne__(self, other):
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq

    def __str__(self):
        return  '%s/%s' % (str(self.ip),
                           str(self._prefixlen))

    def __hash__(self):
        return hash(int(self.network_address) ^ int(self.netmask))

    def __contains__(self, other):
        # always false if one is v4 and the other is v6.
        if self._version != other._version:
          return False
        # dealing with another network.
        if isinstance(other, _BaseInterface):
            return (self.network_address <= other.network_address and
                    self.broadcast_address >= other.broadcast_address)
        # dealing with another address
        else:
            return (int(self.network_address) <= int(other._ip) <=
                    int(self.broadcast_address))

    def overlaps(self, other):
        """Tell if self is partly contained in other."""
        return self.network_address in other or (
            self.broadcast_address in other or (
                other.network_address in self or (
                    other.broadcast_address in self)))

    @property
    def network_address(self):
        x = self._cache.get('network_address')
        if x is None:
            x = ip_address(self._ip & int(self.netmask), version=self._version)
            self._cache['network_address'] = x
        return x

    @property
    def broadcast_address(self):
        x = self._cache.get('broadcast_address')
        if x is None:
            x = ip_address(self._ip | int(self.hostmask), version=self._version)
            self._cache['broadcast_address'] = x
        return x

    @property
    def hostmask(self):
        x = self._cache.get('hostmask')
        if x is None:
            x = ip_address(int(self.netmask) ^ self._ALL_ONES,
                          version=self._version)
            self._cache['hostmask'] = x
        return x

    @property
    def network(self):
        return ip_network('%s/%d' % (str(self.network_address),
                                     self.prefixlen))

    @property
    def with_prefixlen(self):
        return '%s/%d' % (str(self.ip), self._prefixlen)

    @property
    def with_netmask(self):
        return '%s/%s' % (str(self.ip), str(self.netmask))

    @property
    def with_hostmask(self):
        return '%s/%s' % (str(self.ip), str(self.hostmask))

    @property
    def numhosts(self):
        """Number of hosts in the current subnet."""
        return int(self.broadcast_address) - int(self.network_address) + 1

    @property
    def version(self):
        raise NotImplementedError('BaseNet has no version')

    @property
    def prefixlen(self):
        return self._prefixlen

    def address_exclude(self, other):
        """Remove an address from a larger block.

        For example:

            addr1 = ip_network('10.1.1.0/24')
            addr2 = ip_network('10.1.1.0/26')
            addr1.address_exclude(addr2) =
                [ip_network('10.1.1.64/26'), ip_network('10.1.1.128/25')]

        or IPv6:

            addr1 = ip_network('::1/32')
            addr2 = ip_network('::1/128')
            addr1.address_exclude(addr2) = [ip_network('::0/128'),
                ip_network('::2/127'),
                ip_network('::4/126'),
                ip_network('::8/125'),
                ...
                ip_network('0:0:8000::/33')]

        Args:
            other: An IPvXNetwork object of the same type.

        Returns:
            A sorted list of IPvXNetwork objects addresses which is self
            minus other.

        Raises:
            TypeError: If self and other are of difffering address
              versions, or if other is not a network object.
            ValueError: If other is not completely contained by self.

        """
        if not self._version == other._version:
            raise TypeError("%s and %s are not of the same version" % (
                str(self), str(other)))

        if not isinstance(other, _BaseInterface):
            raise TypeError("%s is not a network object" % str(other))

        if other not in self:
            raise ValueError('%s not contained in %s' % (str(other),
                                                         str(self)))
        if other == self:
            return []

        ret_addrs = []

        # Make sure we're comparing the network of other.
        other = ip_network('%s/%s' % (str(other.network_address),
                                      str(other.prefixlen)),
                           version=other._version)

        s1, s2 = self.subnet()
        while s1 != other and s2 != other:
            if other in s1:
                ret_addrs.append(s2)
                s1, s2 = s1.subnet()
            elif other in s2:
                ret_addrs.append(s1)
                s1, s2 = s2.subnet()
            else:
                # If we got here, there's a bug somewhere.
                assert True == False, ('Error performing exclusion: '
                                       's1: %s s2: %s other: %s' %
                                       (str(s1), str(s2), str(other)))
        if s1 == other:
            ret_addrs.append(s2)
        elif s2 == other:
            ret_addrs.append(s1)
        else:
            # If we got here, there's a bug somewhere.
            assert True == False, ('Error performing exclusion: '
                                   's1: %s s2: %s other: %s' %
                                   (str(s1), str(s2), str(other)))

        return sorted(ret_addrs, key=_BaseInterface._get_networks_key)

    def compare_networks(self, other):
        """Compare two IP objects.

        This is only concerned about the comparison of the integer
        representation of the network addresses.  This means that the
        host bits aren't considered at all in this method.  If you want
        to compare host bits, you can easily enough do a
        'HostA._ip < HostB._ip'

        Args:
            other: An IP object.

        Returns:
            If the IP versions of self and other are the same, returns:

            -1 if self < other:
              eg: IPv4('1.1.1.0/24') < IPv4('1.1.2.0/24')
              IPv6('1080::200C:417A') < IPv6('1080::200B:417B')
            0 if self == other
              eg: IPv4('1.1.1.1/24') == IPv4('1.1.1.2/24')
              IPv6('1080::200C:417A/96') == IPv6('1080::200C:417B/96')
            1 if self > other
              eg: IPv4('1.1.1.0/24') > IPv4('1.1.0.0/24')
              IPv6('1080::1:200C:417A/112') >
              IPv6('1080::0:200C:417A/112')

            If the IP versions of self and other are different, returns:

            -1 if self._version < other._version
              eg: IPv4('10.0.0.1/24') < IPv6('::1/128')
            1 if self._version > other._version
              eg: IPv6('::1/128') > IPv4('255.255.255.0/24')

        """
        if self._version < other._version:
            return -1
        if self._version > other._version:
            return 1
        # self._version == other._version below here:
        if self.network_address < other.network_address:
            return -1
        if self.network_address > other.network_address:
            return 1
        # self.network_address == other.network_address below here:
        if self.netmask < other.netmask:
            return -1
        if self.netmask > other.netmask:
            return 1
        # self.network_address == other.network_address and
        # self.netmask == other.netmask
        return 0

    def _get_networks_key(self):
        """Network-only key function.

        Returns an object that identifies this address' network and
        netmask. This function is a suitable "key" argument for sorted()
        and list.sort().

        """
        return (self._version, self.network_address, self.netmask)

    def _ip_int_from_prefix(self, prefixlen=None):
        """Turn the prefix length netmask into a int for comparison.

        Args:
            prefixlen: An integer, the prefix length.

        Returns:
            An integer.

        """
        if not prefixlen and prefixlen != 0:
            prefixlen = self._prefixlen
        return self._ALL_ONES ^ (self._ALL_ONES >> prefixlen)

    def _prefix_from_ip_int(self, ip_int, mask=32):
        """Return prefix length from the decimal netmask.

        Args:
            ip_int: An integer, the IP address.
            mask: The netmask.  Defaults to 32.

        Returns:
            An integer, the prefix length.

        """
        while mask:
            if ip_int & 1 == 1:
                break
            ip_int >>= 1
            mask -= 1

        return mask

    def _ip_string_from_prefix(self, prefixlen=None):
        """Turn a prefix length into a dotted decimal string.

        Args:
            prefixlen: An integer, the netmask prefix length.

        Returns:
            A string, the dotted decimal netmask string.

        """
        if not prefixlen:
            prefixlen = self._prefixlen
        return self._string_from_ip_int(self._ip_int_from_prefix(prefixlen))

    def iter_subnets(self, prefixlen_diff=1, new_prefix=None):
        """The subnets which join to make the current subnet.

        In the case that self contains only one IP
        (self._prefixlen == 32 for IPv4 or self._prefixlen == 128
        for IPv6), return a list with just ourself.

        Args:
            prefixlen_diff: An integer, the amount the prefix length
              should be increased by. This should not be set if
              new_prefix is also set.
            new_prefix: The desired new prefix length. This must be a
              larger number (smaller prefix) than the existing prefix.
              This should not be set if prefixlen_diff is also set.

        Returns:
            An iterator of IPv(4|6) objects.

        Raises:
            ValueError: The prefixlen_diff is too small or too large.
                OR
            prefixlen_diff and new_prefix are both set or new_prefix
              is a smaller number than the current prefix (smaller
              number means a larger network)

        """
        if self._prefixlen == self._max_prefixlen:
            yield self
            return

        if new_prefix is not None:
            if new_prefix < self._prefixlen:
                raise ValueError('new prefix must be longer')
            if prefixlen_diff != 1:
                raise ValueError('cannot set prefixlen_diff and new_prefix')
            prefixlen_diff = new_prefix - self._prefixlen

        if prefixlen_diff < 0:
            raise ValueError('prefix length diff must be > 0')
        new_prefixlen = self._prefixlen + prefixlen_diff

        if not self._is_valid_netmask(str(new_prefixlen)):
            raise ValueError(
                'prefix length diff %d is invalid for netblock %s' % (
                    new_prefixlen, str(self)))

        first = ip_network('%s/%s' % (str(self.network_address),
                                     str(self._prefixlen + prefixlen_diff)),
                         version=self._version)

        yield first
        current = first
        while True:
            broadcast = current.broadcast_address
            if broadcast == self.broadcast_address:
                return
            new_addr = ip_address(int(broadcast) + 1, version=self._version)
            current = ip_network('%s/%s' % (str(new_addr), str(new_prefixlen)),
                                version=self._version)

            yield current

    def masked(self):
        """Return the network object with the host bits masked out."""
        return ip_network('%s/%d' % (self.network_address, self._prefixlen),
                         version=self._version)

    def subnet(self, prefixlen_diff=1, new_prefix=None):
        """Return a list of subnets, rather than an iterator."""
        return list(self.iter_subnets(prefixlen_diff, new_prefix))

    def supernet(self, prefixlen_diff=1, new_prefix=None):
        """The supernet containing the current network.

        Args:
            prefixlen_diff: An integer, the amount the prefix length of
              the network should be decreased by.  For example, given a
              /24 network and a prefixlen_diff of 3, a supernet with a
              /21 netmask is returned.

        Returns:
            An IPv4 network object.

        Raises:
            ValueError: If self.prefixlen - prefixlen_diff < 0. I.e., you have a
              negative prefix length.
                OR
            If prefixlen_diff and new_prefix are both set or new_prefix is a
              larger number than the current prefix (larger number means a
              smaller network)

        """
        if self._prefixlen == 0:
            return self

        if new_prefix is not None:
            if new_prefix > self._prefixlen:
                raise ValueError('new prefix must be shorter')
            if prefixlen_diff != 1:
                raise ValueError('cannot set prefixlen_diff and new_prefix')
            prefixlen_diff = self._prefixlen - new_prefix


        if self.prefixlen - prefixlen_diff < 0:
            raise ValueError(
                'current prefixlen is %d, cannot have a prefixlen_diff of %d' %
                (self.prefixlen, prefixlen_diff))
        # TODO (pmoody): optimize this.
        t = ip_interface('%s/%d' % (str(self.network_address),
                                    self.prefixlen - prefixlen_diff),
                         version=self._version)
        return ip_network('%s/%d' % (str(t.network_address), t.prefixlen),
                          version=t._version)

    # backwards compatibility
    Subnet = subnet
    Supernet = supernet
    AddressExclude = address_exclude
    CompareNetworks = compare_networks
    Contains = __contains__


class _BaseV4(object):

    """Base IPv4 object.

    The following methods are used by IPv4 objects in both single IP
    addresses and networks.

    """

    # Equivalent to 255.255.255.255 or 32 bits of 1's.
    _ALL_ONES = (2**IPV4LENGTH) - 1
    _DECIMAL_DIGITS = frozenset('0123456789')

    def __init__(self, address):
        self._version = 4
        self._max_prefixlen = IPV4LENGTH

    def _explode_shorthand_ip_string(self):
        return str(self)

    def _ip_int_from_string(self, ip_str):
        """Turn the given IP string into an integer for comparison.

        Args:
            ip_str: A string, the IP ip_str.

        Returns:
            The IP ip_str as an integer.

        Raises:
            AddressValueError: if ip_str isn't a valid IPv4 Address.

        """
        octets = ip_str.split('.')
        if len(octets) != 4:
            raise AddressValueError(ip_str)

        packed_ip = 0
        for oc in octets:
            try:
                packed_ip = (packed_ip << 8) | self._parse_octet(oc)
            except ValueError:
                raise AddressValueError(ip_str)
        return packed_ip

    def _parse_octet(self, octet_str):
        """Convert a decimal octet into an integer.

        Args:
            octet_str: A string, the number to parse.

        Returns:
            The octet as an integer.

        Raises:
            ValueError: if the octet isn't strictly a decimal from [0..255].

        """
        # Whitelist the characters, since int() allows a lot of bizarre stuff.
        if not self._DECIMAL_DIGITS.issuperset(octet_str):
            raise ValueError
        octet_int = int(octet_str, 10)
        # Disallow leading zeroes, because no clear standard exists on
        # whether these should be interpreted as decimal or octal.
        if octet_int > 255 or (octet_str[0] == '0' and len(octet_str) > 1):
            raise ValueError
        return octet_int

    def _string_from_ip_int(self, ip_int):
        """Turns a 32-bit integer into dotted decimal notation.

        Args:
            ip_int: An integer, the IP address.

        Returns:
            The IP address as a string in dotted decimal notation.

        """
        octets = []
        for _ in xrange(4):
            octets.insert(0, str(ip_int & 0xFF))
            ip_int >>= 8
        return '.'.join(octets)

    @property
    def max_prefixlen(self):
        return self._max_prefixlen

    @property
    def packed(self):
        """The binary representation of this address."""
        return v4_int_to_packed(self._ip)

    @property
    def version(self):
        return self._version

    @property
    def is_reserved(self):
       """Test if the address is otherwise IETF reserved.

        Returns:
            A boolean, True if the address is within the
            reserved IPv4 Network range.

       """
       return self in IPv4Network('240.0.0.0/4')

    @property
    def is_private(self):
        """Test if this address is allocated for private networks.

        Returns:
            A boolean, True if the address is reserved per RFC 1918.

        """
        return (self in IPv4Network('10.0.0.0/8') or
                self in IPv4Network('172.16.0.0/12') or
                self in IPv4Network('192.168.0.0/16'))

    @property
    def is_multicast(self):
        """Test if the address is reserved for multicast use.

        Returns:
            A boolean, True if the address is multicast.
            See RFC 3171 for details.

        """
        return self in IPv4Network('224.0.0.0/4')

    @property
    def is_unspecified(self):
        """Test if the address is unspecified.

        Returns:
            A boolean, True if this is the unspecified address as defined in
            RFC 5735 3.

        """
        return self in IPv4Network('0.0.0.0')

    @property
    def is_loopback(self):
        """Test if the address is a loopback address.

        Returns:
            A boolean, True if the address is a loopback per RFC 3330.

        """
        return self in IPv4Network('127.0.0.0/8')

    @property
    def is_link_local(self):
        """Test if the address is reserved for link-local.

        Returns:
            A boolean, True if the address is link-local per RFC 3927.

        """
        return self in IPv4Network('169.254.0.0/16')


class IPv4Address(_BaseV4, _BaseAddress):

    """Represent and manipulate single IPv4 Addresses."""

    def __init__(self, address):

        """
        Args:
            address: A string or integer representing the IP
              '192.168.1.1'

              Additionally, an integer can be passed, so
              IPv4Address('192.168.1.1') == IPv4Address(3232235777).
              or, more generally
              IPv4Address(int(IPv4Address('192.168.1.1'))) ==
                IPv4Address('192.168.1.1')

        Raises:
            AddressValueError: If ipaddr isn't a valid IPv4 address.

        """
        _BaseAddress.__init__(self, address)
        _BaseV4.__init__(self, address)

        # Efficient constructor from integer.
        if isinstance(address, (int, long)):
            self._ip = address
            if address < 0 or address > self._ALL_ONES:
                raise AddressValueError(address)
            return

        # Constructing from a packed address
        if _compat_has_real_bytes:
            if isinstance(address, bytes) and len(address) == 4:
                self._ip = struct.unpack('!I', address)[0]
                return

        # Assume input argument to be string or any object representation
        # which converts into a formatted IP string.
        addr_str = str(address)
        self._ip = self._ip_int_from_string(addr_str)


class IPv4Interface(_BaseV4, _BaseInterface):

    """This class represents and manipulates 32-bit IPv4 network + addresses..

    Attributes: [examples for IPv4Interface('1.2.3.4/27')]
        ._ip: 16909060
        .ip: IPv4Address('1.2.3.4')
        .network_address: IPv4Address('1.2.3.0')
        .hostmask: IPv4Address('0.0.0.31')
        .broadcast_address: IPv4Address('1.2.3.31')
        .netmask: IPv4Address('255.255.255.224')
        .prefixlen: 27

    """

    # the valid octets for host and netmasks. only useful for IPv4.
    _valid_mask_octets = set((255, 254, 252, 248, 240, 224, 192, 128, 0))

    def __init__(self, address):
        """Instantiate a new IPv4 network object.

        Args:
            address: A string or integer representing the IP [& network].
              '192.168.1.1/24'
              '192.168.1.1/255.255.255.0'
              '192.168.1.1/0.0.0.255'
              are all functionally the same in IPv4. Similarly,
              '192.168.1.1'
              '192.168.1.1/255.255.255.255'
              '192.168.1.1/32'
              are also functionaly equivalent. That is to say, failing to
              provide a subnetmask will create an object with a mask of /32.

              If the mask (portion after the / in the argument) is given in
              dotted quad form, it is treated as a netmask if it starts with a
              non-zero field (e.g. /255.0.0.0 == /8) and as a hostmask if it
              starts with a zero field (e.g. 0.255.255.255 == /8), with the
              single exception of an all-zero mask which is treated as a
              netmask == /0. If no mask is given, a default of /32 is used.

              Additionally, an integer can be passed, so
              IPv4Interface('192.168.1.1') == IPv4Interface(3232235777).
              or, more generally
              IPv4Interface(int(IPv4Interface('192.168.1.1'))) ==
                IPv4Interface('192.168.1.1')

        Raises:
            AddressValueError: If ipaddr isn't a valid IPv4 address.
            NetmaskValueError: If the netmask isn't valid for
              an IPv4 address.
            ValueError: If strict was True and a network address was not
              supplied.

        """
        _BaseInterface.__init__(self, address)
        _BaseV4.__init__(self, address)

        # Efficient constructor from integer.
        if isinstance(address, (int, long)):
            self._ip = address
            self.ip = IPv4Address(self._ip)
            self._prefixlen = self._max_prefixlen
            self.netmask = IPv4Address(self._ALL_ONES)
            if address < 0 or address > self._ALL_ONES:
                raise AddressValueError(address)
            return

        # Constructing from a packed address
        if _compat_has_real_bytes:
            if isinstance(address, bytes) and len(address) == 4:
                self._ip = struct.unpack('!I', address)[0]
                self.ip = IPv4Address(self._ip)
                self._prefixlen = self._max_prefixlen
                self.netmask = IPv4Address(self._ALL_ONES)
                return

        # Assume input argument to be string or any object representation
        # which converts into a formatted IP prefix string.
        addr = str(address).split('/')

        if len(addr) > 2:
            raise AddressValueError(address)

        self._ip = self._ip_int_from_string(addr[0])
        self.ip = IPv4Address(self._ip)

        if len(addr) == 2:
            mask = addr[1].split('.')
            if len(mask) == 4:
                # We have dotted decimal netmask.
                if self._is_valid_netmask(addr[1]):
                    self.netmask = IPv4Address(self._ip_int_from_string(
                            addr[1]))
                elif self._is_hostmask(addr[1]):
                    self.netmask = IPv4Address(
                        self._ip_int_from_string(addr[1]) ^ self._ALL_ONES)
                else:
                    raise NetmaskValueError('%s is not a valid netmask'
                                                     % addr[1])

                self._prefixlen = self._prefix_from_ip_int(int(self.netmask))
            else:
                # We have a netmask in prefix length form.
                if not self._is_valid_netmask(addr[1]):
                    raise NetmaskValueError(addr[1])
                self._prefixlen = int(addr[1])
                self.netmask = IPv4Address(self._ip_int_from_prefix(
                    self._prefixlen))
        else:
            self._prefixlen = self._max_prefixlen
            self.netmask = IPv4Address(self._ip_int_from_prefix(
                self._prefixlen))
        if self._prefixlen == (self._max_prefixlen - 1):
            self.iterhosts = self.__iter__

    def _is_hostmask(self, ip_str):
        """Test if the IP string is a hostmask (rather than a netmask).

        Args:
            ip_str: A string, the potential hostmask.

        Returns:
            A boolean, True if the IP string is a hostmask.

        """
        bits = ip_str.split('.')
        try:
            parts = [int(x) for x in bits if int(x) in self._valid_mask_octets]
        except ValueError:
            return False
        if len(parts) != len(bits):
            return False
        if parts[0] < parts[-1]:
            return True
        return False

    def _is_valid_netmask(self, netmask):
        """Verify that the netmask is valid.

        Args:
            netmask: A string, either a prefix or dotted decimal
              netmask.

        Returns:
            A boolean, True if the prefix represents a valid IPv4
            netmask.

        """
        mask = netmask.split('.')
        if len(mask) == 4:
            if [x for x in mask if int(x) not in self._valid_mask_octets]:
                return False
            if [y for idx, y in enumerate(mask) if idx > 0 and
                y > mask[idx - 1]]:
                return False
            return True
        try:
            netmask = int(netmask)
        except ValueError:
            return False
        return 0 <= netmask <= self._max_prefixlen

    # backwards compatibility
    IsRFC1918 = lambda self: self.is_private
    IsMulticast = lambda self: self.is_multicast
    IsLoopback = lambda self: self.is_loopback
    IsLinkLocal = lambda self: self.is_link_local


class IPv4Network(IPv4Interface):
    def __init__(self, address):
        IPv4Interface.__init__(self, address)
        if self.ip != self.network_address:
          raise ValueError('%s has host bits set' %
                           self.ip)
        del self.__dict__['ip']

    def __str__(self):
        return '%s/%d' % (str(self.network_address),
                          self.prefixlen)

    @property
    def with_prefixlen(self):
        return '%s/%d' % (str(self.network_address), self._prefixlen)

    @property
    def with_netmask(self):
        return '%s/%s' % (str(self.network_address), str(self.netmask))

    @property
    def with_hostmask(self):
        return '%s/%s' % (str(self.network_address), str(self.hostmask))


class _BaseV6(object):

    """Base IPv6 object.

    The following methods are used by IPv6 objects in both single IP
    addresses and networks.

    """

    _ALL_ONES = (2**IPV6LENGTH) - 1
    _HEXTET_COUNT = 8
    _HEX_DIGITS = frozenset('0123456789ABCDEFabcdef')

    def __init__(self, address):
        self._version = 6
        self._max_prefixlen = IPV6LENGTH

    def _ip_int_from_string(self, ip_str):
        """Turn an IPv6 ip_str into an integer.

        Args:
            ip_str: A string, the IPv6 ip_str.

        Returns:
            A long, the IPv6 ip_str.

        Raises:
            AddressValueError: if ip_str isn't a valid IPv6 Address.

        """
        parts = ip_str.split(':')

        # An IPv6 address needs at least 2 colons (3 parts).
        if len(parts) < 3:
            raise AddressValueError(ip_str)

        # If the address has an IPv4-style suffix, convert it to hexadecimal.
        if '.' in parts[-1]:
            ipv4_int = IPv4Address(parts.pop())._ip
            parts.append('%x' % ((ipv4_int >> 16) & 0xFFFF))
            parts.append('%x' % (ipv4_int & 0xFFFF))

        # An IPv6 address can't have more than 8 colons (9 parts).
        if len(parts) > self._HEXTET_COUNT + 1:
            raise AddressValueError(ip_str)

        # Disregarding the endpoints, find '::' with nothing in between.
        # This indicates that a run of zeroes has been skipped.
        try:
            skip_index, = (
                [i for i in xrange(1, len(parts) - 1) if not parts[i]] or
                [None])
        except ValueError:
            # Can't have more than one '::'
            raise AddressValueError(ip_str)

        # parts_hi is the number of parts to copy from above/before the '::'
        # parts_lo is the number of parts to copy from below/after the '::'
        if skip_index is not None:
            # If we found a '::', then check if it also covers the endpoints.
            parts_hi = skip_index
            parts_lo = len(parts) - skip_index - 1
            if not parts[0]:
                parts_hi -= 1
                if parts_hi:
                    raise AddressValueError(ip_str)  # ^: requires ^::
            if not parts[-1]:
                parts_lo -= 1
                if parts_lo:
                    raise AddressValueError(ip_str)  # :$ requires ::$
            parts_skipped = self._HEXTET_COUNT - (parts_hi + parts_lo)
            if parts_skipped < 1:
                raise AddressValueError(ip_str)
        else:
            # Otherwise, allocate the entire address to parts_hi.  The endpoints
            # could still be empty, but _parse_hextet() will check for that.
            if len(parts) != self._HEXTET_COUNT:
                raise AddressValueError(ip_str)
            parts_hi = len(parts)
            parts_lo = 0
            parts_skipped = 0

        try:
            # Now, parse the hextets into a 128-bit integer.
            ip_int = 0L
            for i in xrange(parts_hi):
                ip_int <<= 16
                ip_int |= self._parse_hextet(parts[i])
            ip_int <<= 16 * parts_skipped
            for i in xrange(-parts_lo, 0):
                ip_int <<= 16
                ip_int |= self._parse_hextet(parts[i])
            return ip_int
        except ValueError:
            raise AddressValueError(ip_str)

    def _parse_hextet(self, hextet_str):
        """Convert an IPv6 hextet string into an integer.

        Args:
            hextet_str: A string, the number to parse.

        Returns:
            The hextet as an integer.

        Raises:
            ValueError: if the input isn't strictly a hex number from [0..FFFF].

        """
        # Whitelist the characters, since int() allows a lot of bizarre stuff.
        if not self._HEX_DIGITS.issuperset(hextet_str):
            raise ValueError
        hextet_int = int(hextet_str, 16)
        if hextet_int > 0xFFFF:
            raise ValueError
        return hextet_int

    def _compress_hextets(self, hextets):
        """Compresses a list of hextets.

        Compresses a list of strings, replacing the longest continuous
        sequence of "0" in the list with "" and adding empty strings at
        the beginning or at the end of the string such that subsequently
        calling ":".join(hextets) will produce the compressed version of
        the IPv6 address.

        Args:
            hextets: A list of strings, the hextets to compress.

        Returns:
            A list of strings.

        """
        best_doublecolon_start = -1
        best_doublecolon_len = 0
        doublecolon_start = -1
        doublecolon_len = 0
        for index in range(len(hextets)):
            if hextets[index] == '0':
                doublecolon_len += 1
                if doublecolon_start == -1:
                    # Start of a sequence of zeros.
                    doublecolon_start = index
                if doublecolon_len > best_doublecolon_len:
                    # This is the longest sequence of zeros so far.
                    best_doublecolon_len = doublecolon_len
                    best_doublecolon_start = doublecolon_start
            else:
                doublecolon_len = 0
                doublecolon_start = -1

        if best_doublecolon_len > 1:
            best_doublecolon_end = (best_doublecolon_start +
                                    best_doublecolon_len)
            # For zeros at the end of the address.
            if best_doublecolon_end == len(hextets):
                hextets += ['']
            hextets[best_doublecolon_start:best_doublecolon_end] = ['']
            # For zeros at the beginning of the address.
            if best_doublecolon_start == 0:
                hextets = [''] + hextets

        return hextets

    def _string_from_ip_int(self, ip_int=None):
        """Turns a 128-bit integer into hexadecimal notation.

        Args:
            ip_int: An integer, the IP address.

        Returns:
            A string, the hexadecimal representation of the address.

        Raises:
            ValueError: The address is bigger than 128 bits of all ones.

        """
        if not ip_int and ip_int != 0:
            ip_int = int(self._ip)

        if ip_int > self._ALL_ONES:
            raise ValueError('IPv6 address is too large')

        hex_str = '%032x' % ip_int
        hextets = []
        for x in range(0, 32, 4):
            hextets.append('%x' % int(hex_str[x:x+4], 16))

        hextets = self._compress_hextets(hextets)
        return ':'.join(hextets)

    def _explode_shorthand_ip_string(self):
        """Expand a shortened IPv6 address.

        Args:
            ip_str: A string, the IPv6 address.

        Returns:
            A string, the expanded IPv6 address.

        """
        if isinstance(self, IPv6Network):
            ip_str = str(self.network_address)
        elif isinstance(self, _BaseAddress):
            ip_str = str(self)
        else:
            # _BaseInterface
            ip_str = str(self.ip)

        ip_int = self._ip_int_from_string(ip_str)
        parts = []
        for i in xrange(self._HEXTET_COUNT):
            parts.append('%04x' % (ip_int & 0xFFFF))
            ip_int >>= 16
        parts.reverse()
        if isinstance(self, _BaseInterface):
            return '%s/%d' % (':'.join(parts), self.prefixlen)
        return ':'.join(parts)

    @property
    def max_prefixlen(self):
        return self._max_prefixlen

    @property
    def packed(self):
        """The binary representation of this address."""
        return v6_int_to_packed(self._ip)

    @property
    def version(self):
        return self._version

    @property
    def is_multicast(self):
        """Test if the address is reserved for multicast use.

        Returns:
            A boolean, True if the address is a multicast address.
            See RFC 2373 2.7 for details.

        """
        return self in IPv6Network('ff00::/8')

    @property
    def is_reserved(self):
        """Test if the address is otherwise IETF reserved.

        Returns:
            A boolean, True if the address is within one of the
            reserved IPv6 Network ranges.

        """
        return (self in IPv6Network('::/8') or
                self in IPv6Network('100::/8') or
                self in IPv6Network('200::/7') or
                self in IPv6Network('400::/6') or
                self in IPv6Network('800::/5') or
                self in IPv6Network('1000::/4') or
                self in IPv6Network('4000::/3') or
                self in IPv6Network('6000::/3') or
                self in IPv6Network('8000::/3') or
                self in IPv6Network('A000::/3') or
                self in IPv6Network('C000::/3') or
                self in IPv6Network('E000::/4') or
                self in IPv6Network('F000::/5') or
                self in IPv6Network('F800::/6') or
                self in IPv6Network('FE00::/9'))

    @property
    def is_unspecified(self):
        """Test if the address is unspecified.

        Returns:
            A boolean, True if this is the unspecified address as defined in
            RFC 2373 2.5.2.

        """
        return self._ip == 0 and getattr(self, '_prefixlen', 128) == 128

    @property
    def is_loopback(self):
        """Test if the address is a loopback address.

        Returns:
            A boolean, True if the address is a loopback address as defined in
            RFC 2373 2.5.3.

        """
        return self._ip == 1 and getattr(self, '_prefixlen', 128) == 128

    @property
    def is_link_local(self):
        """Test if the address is reserved for link-local.

        Returns:
            A boolean, True if the address is reserved per RFC 4291.

        """
        return self in IPv6Network('fe80::/10')

    @property
    def is_site_local(self):
        """Test if the address is reserved for site-local.

        Note that the site-local address space has been deprecated by RFC 3879.
        Use is_private to test if this address is in the space of unique local
        addresses as defined by RFC 4193.

        Returns:
            A boolean, True if the address is reserved per RFC 3513 2.5.6.

        """
        return self in IPv6Network('fec0::/10')

    @property
    def is_private(self):
        """Test if this address is allocated for private networks.

        Returns:
            A boolean, True if the address is reserved per RFC 4193.

        """
        return self in IPv6Network('fc00::/7')

    @property
    def ipv4_mapped(self):
        """Return the IPv4 mapped address.

        Returns:
            If the IPv6 address is a v4 mapped address, return the
            IPv4 mapped address. Return None otherwise.

        """
        if (self._ip >> 32) != 0xFFFF:
            return None
        return IPv4Address(self._ip & 0xFFFFFFFF)

    @property
    def teredo(self):
        """Tuple of embedded teredo IPs.

        Returns:
            Tuple of the (server, client) IPs or None if the address
            doesn't appear to be a teredo address (doesn't start with
            2001::/32)

        """
        if (self._ip >> 96) != 0x20010000:
            return None
        return (IPv4Address((self._ip >> 64) & 0xFFFFFFFF),
                IPv4Address(~self._ip & 0xFFFFFFFF))

    @property
    def sixtofour(self):
        """Return the IPv4 6to4 embedded address.

        Returns:
            The IPv4 6to4-embedded address if present or None if the
            address doesn't appear to contain a 6to4 embedded address.

        """
        if (self._ip >> 112) != 0x2002:
            return None
        return IPv4Address((self._ip >> 80) & 0xFFFFFFFF)


class IPv6Address(_BaseV6, _BaseAddress):

    """Represent and manipulate single IPv6 Addresses.
    """

    def __init__(self, address):
        """Instantiate a new IPv6 address object.

        Args:
            address: A string or integer representing the IP

              Additionally, an integer can be passed, so
              IPv6Address('2001:4860::') ==
                IPv6Address(42541956101370907050197289607612071936L).
              or, more generally
              IPv6Address(IPv6Address('2001:4860::')._ip) ==
                IPv6Address('2001:4860::')

        Raises:
            AddressValueError: If address isn't a valid IPv6 address.

        """
        _BaseAddress.__init__(self, address)
        _BaseV6.__init__(self, address)

        # Efficient constructor from integer.
        if isinstance(address, (int, long)):
            self._ip = address
            if address < 0 or address > self._ALL_ONES:
                raise AddressValueError(address)
            return

        # Constructing from a packed address
        if _compat_has_real_bytes:
            if isinstance(address, bytes) and len(address) == 16:
                tmp = struct.unpack('!QQ', address)
                self._ip = (tmp[0] << 64) | tmp[1]
                return

        # Assume input argument to be string or any object representation
        # which converts into a formatted IP string.
        addr_str = str(address)
        if not addr_str:
            raise AddressValueError('')

        self._ip = self._ip_int_from_string(addr_str)


class IPv6Interface(_BaseV6, _BaseInterface):

    """This class represents and manipulates 128-bit IPv6 networks.

    Attributes: [examples for IPv6('2001:658:22A:CAFE:200::1/64')]
        .ip: IPv6Address('2001:658:22a:cafe:200::1')
        .network_address: IPv6Address('2001:658:22a:cafe::')
        .hostmask: IPv6Address('::ffff:ffff:ffff:ffff')
        .broadcast_address: IPv6Address('2001:658:22a:cafe:ffff:ffff:ffff:ffff')
        .netmask: IPv6Address('ffff:ffff:ffff:ffff::')
        .prefixlen: 64

    """


    def __init__(self, address):
        """Instantiate a new IPv6 Network object.

        Args:
            address: A string or integer representing the IPv6 network or the IP
              and prefix/netmask.
              '2001:4860::/128'
              '2001:4860:0000:0000:0000:0000:0000:0000/128'
              '2001:4860::'
              are all functionally the same in IPv6.  That is to say,
              failing to provide a subnetmask will create an object with
              a mask of /128.

              Additionally, an integer can be passed, so
              IPv6Network('2001:4860::') ==
                IPv6Network(42541956101370907050197289607612071936L).
              or, more generally
              IPv6Network(IPv6Network('2001:4860::')._ip) ==
                IPv6Network('2001:4860::')

            strict: A boolean. If true, ensure that we have been passed
              A true network address, eg, 192.168.1.0/24 and not an
              IP address on a network, eg, 192.168.1.1/24.

        Raises:
            AddressValueError: If address isn't a valid IPv6 address.
            NetmaskValueError: If the netmask isn't valid for
              an IPv6 address.
            ValueError: If strict was True and a network address was not
              supplied.

        """
        _BaseInterface.__init__(self, address)
        _BaseV6.__init__(self, address)

        # Efficient constructor from integer.
        if isinstance(address, (int, long)):
            self._ip = address
            self.ip = IPv6Address(self._ip)
            self._prefixlen = self._max_prefixlen
            self.netmask = IPv6Address(self._ALL_ONES)
            if address < 0 or address > self._ALL_ONES:
                raise AddressValueError(address)
            return

        # Constructing from a packed address
        if _compat_has_real_bytes:
            if isinstance(address, bytes) and len(address) == 16:
                tmp = struct.unpack('!QQ', address)
                self._ip = (tmp[0] << 64) | tmp[1]
                self.ip = IPv6Address(self._ip)
                self._prefixlen = self._max_prefixlen
                self.netmask = IPv6Address(self._ALL_ONES)
                return

        # Assume input argument to be string or any object representation
        # which converts into a formatted IP prefix string.
        addr = str(address).split('/')

        if len(addr) > 2:
            raise AddressValueError(address)

        self._ip = self._ip_int_from_string(addr[0])
        self.ip = IPv6Address(self._ip)

        if len(addr) == 2:
            if self._is_valid_netmask(addr[1]):
                self._prefixlen = int(addr[1])
            else:
                raise NetmaskValueError(addr[1])
        else:
            self._prefixlen = self._max_prefixlen

        self.netmask = IPv6Address(self._ip_int_from_prefix(self._prefixlen))
        if self._prefixlen == (self._max_prefixlen - 1):
            self.iterhosts = self.__iter__


    def _is_valid_netmask(self, prefixlen):
        """Verify that the netmask/prefixlen is valid.

        Args:
            prefixlen: A string, the netmask in prefix length format.

        Returns:
            A boolean, True if the prefix represents a valid IPv6
            netmask.

        """
        try:
            prefixlen = int(prefixlen)
        except ValueError:
            return False
        return 0 <= prefixlen <= self._max_prefixlen

    @property
    def with_netmask(self):
        return self.with_prefixlen


class IPv6Network(IPv6Interface):
    def __init__(self, address):
        IPv6Interface.__init__(self, address)

        if self.ip != self.network_address:
          raise ValueError('%s has host bits set' %
                           self.ip)
        del self.__dict__['ip']


    def __str__(self):
        return '%s/%d' % (str(self.network_address),
                          self.prefixlen)

    @property
    def with_prefixlen(self):
        return '%s/%d' % (str(self.network_address), self._prefixlen)

    @property
    def with_netmask(self):
        return '%s/%s' % (str(self.network_address), str(self.netmask))

    @property
    def with_hostmask(self):
        return '%s/%s' % (str(self.network_address), str(self.hostmask))
