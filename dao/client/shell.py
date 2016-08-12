# Copyright 2016 Symantec, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import argparse
import getpass
import json
import netaddr
import os
import pprint
import sys

from dao.common import config

config.setup('client')

# Must be imported after config is initialized.
import requests
from dao.common import log
from dao.common import exceptions


opts = [
    config.StrOpt('client', 'master_url', default='http://localhost:5000/v1.0',
                  help='Full URL for DAO Master agent.'),
    config.StrOpt('client', 'location_var', default='DAO_LOCATION',
                  help='Name of the OS variable to use as location'),
    config.StrOpt('client', 'location', default=None,
                  help='Backward compatibility. Location can be configured.'),
]
config.register(opts)
CONF = config.get_config()

log.setup('client')
logger = log.getLogger(__name__)

HANDLERS = dict()


def cli_argument(*args, **kwargs):
    """Function create a decorator that add named attributes to the function"""

    def wrap(func):
        """Decorator internal wrapper"""

        if not hasattr(func, 'cli_args'):
            func.cli_args = list()
        func.cli_args.append((args, kwargs))
        return func

    return wrap


def cli_usage(usage):
    """Decorator to provide usage examples"""

    def wrap(func):
        """Decorator internal wrapper"""

        if not hasattr(func, 'cli_args'):
            func.cli_args = list()
        func.cli_usage = usage
        return func

    return wrap


def cli_command(func):
    """Decorator that adds function to list of available commands"""
    HANDLERS[func.func_name.replace('_', '-')] = func
    return func


class DAOClient(object):
    """
    Class implements general logic to call dao manager and print result
    """
    def __init__(self, print_format, user, location, parser):
        self.print_format = print_format
        self.parser = parser
        self.user = user
        # Canonic name format for location is all-caps.
        self.location = location.upper()

    def _call(self, func, *args, **kwargs):
        data = dict(func=func,
                    args=(self.user, self.location) + args,
                    kwargs=kwargs)
        r = requests.post(requests.compat.urljoin(CONF.client.master_url,
                                                  'tasks'),
                          data=json.dumps(data),
                          headers={'Content-Type': 'application/json'})
        if 200 <= r.status_code < 300:
            return r.json()['result']
        print r.text
        sys.exit(1)

    @cli_command
    def get_master_config(self, args):
        """Show master environment"""
        self._print_result(args, self._call('get_env'))

    @cli_command
    def worker_list(self, args):
        """List registered workers. Can be used to get worker ID
        for dao rack-update command"""
        self._print_result(args, self._call('worker_list'))

    @cli_command
    @cli_argument('rack_name', help='Rack name to update DHCP leases')
    def dhcp_rack_update(self, args):
        """Update networks list on the DHCP host"""
        self._print_result(args,
                           self._call('dhcp_rack_update', args.rack_name))

    @cli_command
    @cli_argument('worker_name', help='Worker name')
    def health_check(self, args):
        result = self._call('health_check', worker=args.worker_name)
        self._print_result(args, result)

    @cli_command
    @cli_argument('ip', help='IP address of the ToR')
    @cli_argument('switch', help='Switch name trr<index>-<rack>.<dc>. '
                                 'Example: <trr1-e2.ash2>. Workaround.')
    @cli_argument('worker', help='Worker name')
    @cli_argument('--create', action='store_true', default=False,
                  help='Create rack/network/devices if not exists')
    def rack_discover(self, args):
        result = self._call('rack_discover', args.worker,
                                   args.switch, args.ip, args.create)
        self._print_result(args, result)

    @cli_command
    @cli_argument('--type', required=True,
                  help='Class name Server, Subnet, etc.')
    @cli_argument('--key', required=True,
                  help='Object key_field=key_value')
    @cli_argument('--set', action='append',
                  help='Can be repeated, name=value')
    @cli_argument('--json', action='store_true', default=False,
                  help='Parameter is a json field')
    def object_update(self, args):
        """Update any DB object."""
        args_dict = dict(item.split('=') for item in args.set)
        key, key_value = args.key.split('=')
        if args.json:
            args_dict = dict((k, json.loads(v)) for k, v in args_dict.items())
        self._print_result(args,
                           self._call('object_update', args.type,
                                      key, key_value, args_dict))

    @cli_command
    @cli_argument('--type', required=True,
                  help='Class name Server, Subnet, etc.')
    @cli_argument('--join', action='append', default=[],
                  help='DB class name to join')
    @cli_argument('--loads', action='append', default=[],
                  help='DB relationship to load')
    @cli_argument('--key', action='append', default=[],
                  help='Object key_field=key_value')
    def object_list(self, args):
        result = self._call('objects_list',
                            cls=args.type,
                            joins=args.join,
                            loads=args.loads,
                            **dict(key.split('=') for key in args.key))
        self._print_result(args, result)

    @cli_command
    @cli_argument('--name', required=True, help='network map name')
    @cli_argument('--port2number', required=True,
                  help='Lambda function to convert MGMT port number to '
                       'server number')
    @cli_argument('--number2unit', required=True,
                  help='Lambda function to convert server number to rack unit')
    @cli_argument('--pxe', required=True,
                  help='name of the pxe nic (is used to request mac using '
                       'ipmi tools)')
    @cli_argument('--network', required=True,
                  help='json description of the network topology')
    def network_map_create(self, args):
        """Create new network map. Map name should be unique"""
        try:
            eval(args.port2number)
        except SyntaxError:
            raise exceptions.DAOException('--port2number is not a valid eval')
        try:
            eval(args.number2unit)
        except SyntaxError:
            raise exceptions.DAOException('--number2unit is not a valid eval')
        try:
            json.loads(args.network)
        except SyntaxError:
            raise exceptions.DAOException('--network is not a valid json')
        self._print_result(args,
                           self._call('network_map_create',
                                      name=args.name,
                                      port2number=args.port2number,
                                      number2unit=args.number2unit,
                                      pxe_nic=args.pxe,
                                      network=args.network))

    @cli_command
    @cli_argument('--key', action='append', default=[],
                  help='Filtering argument. key=value. Repeatable.')
    def network_map_list(self, args):
        """List cluster (only for current location)."""
        kwargs = dict(k.split('=') for k in args.key)
        self._print_result(args, self._call('network_map_list', **kwargs))

    @cli_command
    @cli_argument('rack', help='rack name to use')
    @cli_argument('--net-map', default=None,
                  help='Networking map name. Use dao network-map-list to get'
                       'available mappings')
    @cli_argument('--gw',
                  help='Optional argument. Default gateway address per rack.')
    @cli_argument('--env',
                  help='Optional argument. Rack environment (prod, dvt, etc.)')
    @cli_argument('--meta', action='append', default=[],
                  help='Optional repeatable argument key=value. Set rack meta.'
                       'Meaning values: hook_cls, naming_version.')
    @cli_argument('--worker',
                  help='Optional argument. Define which worker rack belongs to'
                       ' (which worker is responsible for validation and '
                       'provisioning).')
    @cli_argument('--reset-worker', action='store_true', default=False,
                  help='Optional argument. Reset worker control over the rack')
    def rack_update(self, args):
        """Update rack record in the DB"""
        gateway = str(netaddr.IPAddress(args.gw)) if args.gw else None
        self._print_result(
            args, self._call('rack_update',
                             rack_name=args.rack,
                             env=args.env,
                             gw=gateway,
                             net_map=args.net_map,
                             worker_name=args.worker,
                             reset_worker=args.reset_worker,
                             meta=dict(i.split('=') for i in args.meta)))

    @cli_command
    @cli_argument('--fake', action='store_true',
                  help='Optional. Renumber hosts in a fake way.')
    @cli_argument('rack', help='rack name renumber')
    def rack_renumber(self, args):
        """Renumber servers in rack"""
        self._print_result(args,
                           self._call('rack_renumber', rack_name=args.rack,
                                      fake=args.fake))

    @cli_command
    @cli_argument('--key', action='append', default=[],
                  help='Filtering argument. key=value. Repeatable.')
    @cli_argument('--detailed', action='store_true',
                  help='Optional. Extend output with rack network information')
    def rack_list(self, args):
        """List racks, optionally by pattern"""
        kwargs = dict(k.split('=') for k in args.key)
        self._print_result(args,
                           self._call('rack_list',
                                      detailed=args.detailed,
                                      **kwargs))

    @cli_command
    @cli_argument('rack',
                  help='Filtering argument. Required. Define the rack for '
                       'which rest of attributes are applied.')
    @cli_argument('--set-cluster', default=None,
                  help='Modification argument. Set the server cluster field. '
                       'Just a string, does not check to anything. '
                       'Is required for S1->S2 state transition.')
    @cli_argument('--set-role', default=None,
                  help='Modification argument. Set the server role. '
                       'Just a string, does not check to anything. '
                       'Is required for S1->S2 state transition. '
                       'Important: it is part of the FQDN so server name can '
                       'be changed during S0->S1->S2.')
    @cli_argument('--set-hdd-type', default='RAID10',
                  help='Raid configuration. Workaround')
    @cli_argument('--set-target-status', default='',
                  choices=['S0', 'S1', 'S2'],
                  help='Modification argument. Set "target_status" field for '
                       'all servers that pass filters')
    @cli_argument('--serial', action='append', default=[],
                  help='Filtering argument. Defines filter by server serial '
                       'number. Repeatable..')
    @cli_argument('--name', action='append', default=[],
                  help='Filtering argument. Defines filter by server name. '
                       'Repeatable.')
    @cli_argument('--status', action='append', default=[],
                  choices=['S0', 'S0S1', 'S1', 'S1S2', 'S2'],
                  help='Filtering argument. Defines filter by current server '
                       'status. Repeatable.')
    @cli_argument('--set-status', default='', choices=['S0', 'S1', 'S2'],
                  help='Modification argument. Set "status" field for all '
                       'servers that pass filters.')
    @cli_argument('--set-os-name', default='',
                  help='Modification argument. Set the operation system used '
                       'for provisioning. Is required for S1->S2 state '
                       'transition. List of available OS can be get using '
                       'dao os-list <rack_name> command.')
    @cli_argument('--set-os-media', default='',
                  help='Modification argument. Set the media used during '
                       'S1->S2 transition. Optional.')
    @cli_argument('--set-os-partition', default='',
                  help='Modification argument. Set the partition used '
                       'during S1->S2 transition. Optional.')
    @cli_argument('--set-os-root_pass', default='',
                  help='Modification argument. '
                       'Set the password used by provisioning tool. '
                       'Can be ignored.')
    def rack_trigger(self, args):
        """Start validation (S0->S1) or/and provisioning (S1->S2)
        process on per rack/server basis."""
        from2status = {'S0': ('Unmanaged', 'Unknown', 'ValidatedWithErrors'),
                       'S0S1': ('Validating',),
                       'S1': ('Validated', 'ProvisionedWithErrors'),
                       'S1S2': ('Provisioning',),
                       'S2': ('Provisioned',)}
        sx2status = {'S0': 'Unmanaged', 'S1': 'Validated',
                     'S2': 'Provisioned', '': None}
        from_status = []
        for status in args.status:
            from_status.extend(from2status[status.upper()])
        set_status = sx2status[args.set_status.upper()]
        target_status = sx2status[args.set_target_status.upper()]

        if args.set_os_name:
            os_args = dict(os_name=args.set_os_name,
                           media=args.set_os_media,
                           partition=args.set_os_partition)
        else:
            os_args = dict()

        result = self._call('rack_trigger',
                            rack_name=args.rack,
                            cluster_name=args.set_cluster,
                            role=args.set_role,
                            hdd_type=args.set_hdd_type,
                            serial=args.serial,
                            names=args.name,
                            from_status=from_status,
                            set_status=set_status,
                            target_status=target_status,
                            os_args=os_args)
        if isinstance(result, Exception):
            result = 'dao rack_trigger: error: {0:s}'.format(result)
        self._print_result(args, result)

    @cli_command
    @cli_argument('--serial', required=True,
                  help='Serial number to be marked as protected/unprotected. '
                       'Case sensitive.')
    @cli_argument('--rack', required=True,
                  help='Required argument. Is required in order to create '
                       'asset correctly if not exists.')
    @cli_argument('--reset', action='store_true', default=False,
                  help='Optional argument. "protected" field is cleared if '
                       'this "--reset" argument is set.')
    @cli_usage('This field can be used to protect server from being auto '
               'discovered or from being validated/provision by DAO '
               'automatization. If asset for pointed serial number does not '
               'exists, new asset is created.')
    def asset_protect(self, args):
        """Set/clear 'protected' field for asset."""
        asset = self._call('asset_protect',
                           serial=args.serial,
                           rack_name=args.rack,
                           set_protected=(not args.reset))
        self._print_result(args, asset)

    @cli_command
    @cli_argument('--rack', help='Filter output assets by rack name these '
                                 'assets belongs to.')
    @cli_argument('--protected', action='store_true', default=False,
                  help='Show only protected assets')
    @cli_argument('--name', action='append', default=[],
                  help='Repeatable argument. Filter output by asset names. '
                       'Asset name is equal to serial number.')
    @cli_argument('--serial', action='append', default=[],
                  help='Repeatable argument. Filter output by asset names. '
                       'Asset name is equal to serial number.')
    @cli_argument('--type', default=None,
                  help='Filter output by asset type.')
    def asset_list(self, args):
        """List assets using provided filters"""
        assets = self._call('assets_list',
                            rack_name=args.rack,
                            protected=args.protected,
                            names=args.name,
                            serials=args.serial,
                            type_=args.type)
        # way to fix unicode
        if isinstance(assets, dict):
            assets = json.loads(json.dumps(assets))
        self._print_result(args, assets)

    @cli_command
    @cli_argument('--rack',
                  help='Filter output by server rack name. An example: '
                       'dao server-list --rack PHX2-A1')
    @cli_argument('--sku',
                  help='Filter output by server sku name. An example: '
                       'dao server-list --sku Red')
    @cli_argument('--cluster',
                  help='Filter output by server cluster. An example: '
                       'dao server-list --cluster infra')
    @cli_argument('--serial', action='append', default=[],
                  help='Filter output by serial numbers. Repeatable parameter.'
                       ' An example: '
                       'dao server-list --serial D81PW12 --serial G6PNW12')
    @cli_argument('--ip', action='append', default=[],
                  help='Filter output by ip address. Repeatable parameter.'
                       ' An example: '
                       'dao server-list --ip 10.0.0.2 --ip 10.0.1.20')
    @cli_argument('--mac', action='append', default=[],
                  help='Filter output by mac address. Repeatable parameter.'
                       ' An example: '
                       'dao server-list --mac 11:22:33:44:55:66')
    @cli_argument('--name', action='append', default=[],
                  help='Filter output by server names. Repeatable parameter. '
                       'An example: '
                       'dao server-list --name b-t1-r01g4-prod '
                       '--name b-t1-r03f3-prod')
    @cli_argument('--status', action='append', default=[],
                  help='Filter output by server statuses. Repeatable '
                       'parameter. An example: '
                       'dao server-list --status Validating '
                       '--status ValidatedWithErrors')

    @cli_argument('--detailed', action='store_true',
                  help='Extended output, including server network interfaces')
    @cli_usage([
        'Example:',
        'dao server-list --rack PHX2-A1 --status Validating --detailed'])
    def server_list(self, args):
        """List servers, using provided filters."""
        servers = self._call('servers_list',
                             rack_name=args.rack,
                             cluster_name=args.cluster,
                             serials=args.serial,
                             macs=args.mac,
                             ips=args.ip,
                             names=args.name,
                             from_status=args.status,
                             sku_name=args.sku,
                             detailed=args.detailed)
        # way to fix unicode
        if isinstance(servers, dict):
            servers = json.loads(json.dumps(servers))
        for s in servers.values():
            interfaces = s.pop('interfaces', [])
            if interfaces:
                for iface in interfaces:
                    # for backward comp-ty there are more code then is required
                    if args.filter:
                        name = iface['name'].lower().replace(' ', '')
                    else:
                        name = 'interface:%s' % iface['name']
                        if args.format == 'print':
                            iface = str(iface)
                    s[name] = iface
        self._print_result(args, servers)

    @cli_command
    @cli_argument('serial')
    @cli_argument('name')
    @cli_argument('id')
    def server_delete(self, args):
        """Delete server."""
        result = self._call('server_delete',
                            sid=args.id,
                            serial=args.serial,
                            name=args.name)
        self._print_result(args, result)

    @cli_command
    @cli_argument('--name', action='append', default=[],
                  help='Filtering argument. Defines filter by server name. '
                       'Repeatable.')
    @cli_argument('--rack',
                  help='Filtering parameter. Specify rack name to be used as '
                       'a filter.')
    @cli_argument('--request-id',
                  help='Filtering argument. ID of the transaction to stop. '
                       'Can be got using dao server-list command, field '
                       '"lock_id". Remember that one transaction can include '
                       'more then one server.')
    @cli_argument('--force', action='store_true', default=False,
                  help='This option allows using server-stop command without '
                       'request-id option.')
    @cli_usage(['Two requirements for arguments used with this command:',
                ' At least one filtering argument should be used',
                ' Argument --request-id is to be used unless --force is used'])
    def server_stop(self, args):
        """Stop S0->S1->S2 state transition."""
        if not args.force:
            if args.request_id is None:
                self.parser.error('--request_id is required except --force is '
                                  'used')
        servers = self._call('server_stop',
                             request_id=args.request_id,
                             names=args.name,
                             rack_name=args.rack,
                             force=args.force)
        # way to fix unicode
        if isinstance(servers, dict):
            servers = json.loads(json.dumps(servers))
        self._print_result(args, servers)

    @cli_command
    @cli_argument('--type', required=True,
                  help='DB object type. Sku, Worker, Rack, Subnet, Asset, '
                       'SwitchInterface, Cluster, NetworkDevice, Server')
    @cli_argument('--key', help='Identifier in a format of key_name=key_value.'
                                ' Key should represent some unique field.')
    @cli_usage(['Examples:'
                ' dao history --type Server',
                ' dao history --type Rack --key name=PHX2-A1'])
    def history(self, args):
        """List history of updates to DB that was done using DAO.
        """
        key_name, key_value = args.key.split('=') if args.key else (None, None)
        result = self._call('history', args.type,
                            key=key_name, value=key_value)
        self._print_result(args, result)

    @cli_command
    @cli_argument('mac',
                  help='Server BMC MAC address in format XX:XX:XX:XX:XX:XX')
    @cli_argument('ip', help='Server BMC IP address')
    @cli_argument('worker', help='Target worker')
    @cli_argument('--force', action='store_true', default=False,
                  help='ignore discovery-disable option')
    def discover(self, args):
        """Manually trigger server auto discovery"""
        result = self._call('dhcp_hook', mac=args.mac, ip=args.ip,
                            worker_name=args.worker, force=args.force)
        self._print_result(args, result)

    @cli_command
    @cli_argument('--mac', default=None,
                  help='Server BMC MAC address in format XX:XX:XX:XX:XX:XX')
    @cli_argument('worker', help='Target worker')
    def discovery_cache_reset(self, args):
        """Manually reset discovery cache"""
        result = self._call('discovery_cache_reset',
                            worker_name=args.worker,
                            mac=args.mac)
        self._print_result(args, result)

    @cli_command
    @cli_argument('--key', action='append', default=[],
                  help='Filtering argument. key=value. Repeatable.')
    @cli_argument('--detailed', action='store_true',
                  help='Show detailed output')
    def cluster_list(self, args):
        """List cluster (only for current location)."""
        kwargs = dict(k.split('=') for k in args.key)
        self._print_result(args, self._call('cluster_list', args.detailed,
                                            **kwargs))

    @cli_command
    @cli_argument('--name', required=True, help='cluster name')
    @cli_argument('--type', required=True, help='Show detailed output')
    def cluster_create(self, args):
        """Create new cluster record. Cluster name should be unique per
         location"""
        self._print_result(args, self._call('cluster_create',
                                            args.name,
                                            args.type))

    @cli_command
    def sku_list(self, args):
        """Create new cluster record. Cluster name should be unique per
         location"""
        self._print_result(args, self._call('sku_list'))

    @cli_command
    @cli_argument('--name', required=True, help='sku name')
    @cli_argument('--cpu', required=True,
                  help='CPU description. Example: '
                       '2 x Intel(R) Xeon(R) CPU E5-2670 0 @ 2.60GHz 8C')
    @cli_argument('--ram', required=True,
                  help='RAM description. Example: 128GB')
    @cli_argument('--hdd', required=True,
                  help='HDD description. Example: '
                       '*2 x 600GB 0K RPM SAS *12 x 4TB 0K RPM SAS')
    @cli_argument('--description', required=True,
                  help='Plain text sku description')
    def sku_create(self, args):
        """Create new cluster record. Cluster name should be unique per
         location"""
        self._print_result(args, self._call('sku_create',
                                            args.name,
                                            args.cpu,
                                            args.ram,
                                            args.hdd,
                                            args.description))

    @cli_command
    @cli_argument('--os-name', default='',
                  help='OS name to narrow output')
    @cli_argument('--worker', default='',
                  help='Worker name to pull OS from')
    @cli_usage('Worker is auto detected if there is only one worker '
               'for location')
    def os_list(self, args):
        """List OS available for using on the worker."""
        oss = self._call('os_list',
                         worker_name=args.worker,
                         os_name=args.os_name)
        self._print_result(args, oss)

    def _print_result(self, args, result):
        """Print result in a format defined by self.print_format"""
        if result is None:
            result = 'Accepted'
        if args.filter:
            fields = args.filter.split(',')
            #apply interfaces normalization, to make it user friendly
            if isinstance(result, dict):
                result = dict((k, self._filter(fields, v)[1])
                              for k, v in result.items())
            elif isinstance(result, list):
                result = list(self._filter(fields, v)[1] for v in result)
        if self.print_format == 'print':
            pprint.pprint(result)
        elif self.print_format == 'json':
            print json.dumps(result)

    def _filter(self, fields, result, starter=''):
        affected = False
        if isinstance(result, dict):
            new = dict()
            for k, v in result.items():
                istarter = k if not starter else '.'.join([starter, k])
                if istarter in fields:
                    add = True
                else:
                    add, v = self._filter(fields, v, istarter)
                if add:
                    affected = True
                    new[k] = v
            return affected, new
        elif isinstance(result, list):
            new = list()
            istarter = starter + '.'
            for v in result:
                if istarter in fields:
                    add = True
                else:
                    add, v = self._filter(fields, v, istarter)
                if add:
                    affected = True
                    new.append(v)
            return affected, new
        else:
            return False, result


def check_user():
    user = getpass.getuser()
    if user == 'root':
        logger.warning('You are trying to run dao using root account. '
                       'Use your local user instead.')
        sys.exit(1)
    return user


class DAOParser(argparse.ArgumentParser):
    def get_subparsers(self, name):
        result = [action for action in self._actions if action.dest == name]
        if result:
            return result[0]
        else:
            raise RuntimeError('Unable to locate subparser')


def get_parser():
    parser = DAOParser()
    parser.add_argument('--format', default='print',
                        help='Output format. json|cvs|print')
    parser.add_argument('--filter', default='',
                        help='Filter the result fields. Coma separated.'
                             'An example: asset.serial,pxe_ip')
    parser.add_argument('--debug', default=False, action='store_true',
                        help='Provide an extended error output')
    parser.add_argument('--location', default=None,
                        help='Location. Can be set in client.cfg'.
                        format(CONF.client.location_var))
    subparsers = parser.add_subparsers(dest='command', help='sub-command help')
    for name, func in HANDLERS.items():
        sub_parser = subparsers.add_parser(name, help=func.func_doc)
        for args, kwargs in getattr(func, 'cli_args', []):
            sub_parser.add_argument(*args, **kwargs)
        usage = getattr(func, 'cli_usage', None)
        if usage:
            if isinstance(usage, list):
                usage = '\n\r'.join(usage)
            sub_parser.description = usage
    return parser


def run():
    """Entry point for CLI. Parse arguments, locate function and call it"""
    user = check_user()
    parser = get_parser()
    args = parser.parse_args()
    # Ensure environment is set
    dao_location = args.location or os.getenv(CONF.client.location_var)
    dao_location = dao_location or CONF.client.location
    if not dao_location:
        parser.error('Either --location or {0} should be specified'.
                     format(CONF.client.location_var))
    argparse.ArgumentTypeError('Value has to be between 0 and 1' )
    sub_parser = parser.get_subparsers('command').choices[args.command]
    cli = DAOClient(args.format, user, dao_location, sub_parser)
    try:
        HANDLERS[args.command](cli, args)
    except exceptions.DAOTimeout:
        msg = 'DAO Master at {ip} could not be reached: timeout'.format(
            ip=CONF.client.master_url)
        logger.error(msg)


if __name__ == '__main__':
    run()
