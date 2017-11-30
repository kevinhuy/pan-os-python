#!/usr/bin/env python

# Copyright (c) 2014, Palo Alto Networks
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.


"""Panorama and all Panorama related objects"""

# import modules
import logging
import xml.etree.ElementTree as ET
from copy import deepcopy

# import other parts of this pandevice package
import pandevice
from pandevice import getlogger, yesno
from pandevice import base, firewall, policies
import pandevice.errors as err
from pandevice.base import VarPath as Var
from pandevice.base import PanObject, Root, MEMBER, ENTRY
from pandevice.base import VersionedPanObject, VersionedParamPath

import pan.commit

logger = getlogger(__name__)


class DeviceGroup(VersionedPanObject):
    """Panorama Device-group

    This class and the :class:`pandevice.panorama.Panorama` classes are the only objects that can
    have a :class:`pandevice.firewall.Firewall` child object. In addition to a Firewall, a
    DeviceGroup can have the same children objects as a :class:`pandevice.firewall.Firewall`
    or :class:`pandevice.device.Vsys`.

    See also :ref:`classtree`

    Args:
        name (str): Name of the device-group
        tag (list): Tags as strings

    """
    ROOT = Root.DEVICE
    SUFFIX = ENTRY
    CHILDTYPES = (
        "firewall.Firewall",
        "objects.AddressObject",
        "objects.AddressGroup",
        "policies.PreRulebase",
        "policies.PostRulebase",
        "objects.ServiceObject",
        "objects.ServiceGroup",
        "objects.ApplicationObject",
        "objects.ApplicationGroup",
        "objects.ApplicationFilter",
    )

    def _setup(self):
        # xpaths
        self._xpaths.add_profile(value='/device-group')

        # params
        params = []

        params.append(VersionedParamPath(
            'tag', vartype='entry'))

        self._params = tuple(params)

    def devicegroup(self):
        return self

    def xpath_vsys(self):
        if self.name == "shared" or self.name is None:
            return "/config/shared"
        else:
            return "/config/devices/entry[@name='localhost.localdomain']/device-group/entry[@name='%s']" % self.name

    def _build_xpath(self, root, vsys):
        if (self.name == "shared" or self.name is None) and root == Root.VSYS:
            # This is a Vsys object in shared Panorama scope, so proceed normally
            return super(DeviceGroup, self)._build_xpath(root,
                self.name or 'shared')
        else:
            # This is a member of the device-group, so override to use DeviceGroup root
            return super(DeviceGroup, self)._build_xpath(self.ROOT, self.name)


class Panorama(base.PanDevice):
    """Panorama device

    This is the only object in the configuration tree that cannot have a parent. If it is in the configuration
    tree, then it is the root of the tree.

    Args:
        hostname: Hostname or IP of device for API connections
        api_username: Username of administrator to access API
        api_password: Password of administrator to access API
        api_key: The API Key for connecting to the device's API
        port: Port of device for API connections
        timeout: The timeout for asynchronous jobs
        interval: The interval to check asynchronous jobs

    """
    FIREWALL_CLASS = firewall.Firewall
    NAME = "hostname"
    CHILDTYPES = (
        "device.Administrator",
        "device.PasswordProfile",
        "firewall.Firewall",
        "panorama.DeviceGroup",
    )

    def __init__(self,
                 hostname,
                 api_username=None,
                 api_password=None,
                 api_key=None,
                 port=443,
                 *args,
                 **kwargs
                 ):
        super(Panorama, self).__init__(hostname, api_username, api_password, api_key, port, *args, **kwargs)
        # create a class logger
        self._logger = logging.getLogger(__name__ + "." + self.__class__.__name__)

    def op(self, cmd=None, vsys=None, xml=False, cmd_xml=True, extra_qs=None, retry_on_peer=False):
        """Perform operational command on this Panorama

        Args:
            cmd (str): The operational command to execute
            vsys (str): Ignored for Panorama
            xml (bool): Return value should be a string (Default: False)
            cmd_xml (bool): True: cmd is not XML, False: cmd is XML (Default: True)
            extra_qs: Extra parameters for API call
            retry_on_peer (bool): Try on active Firewall first, then try on passive Firewall

        Returns:
            xml.etree.ElementTree: The result of the operational command. May also return a string of XML if xml=True

        """
        # TODO: Support device-group and template scope
        return super(Panorama, self).op(cmd, vsys=None, xml=xml, cmd_xml=cmd_xml, extra_qs=extra_qs, retry_on_peer=retry_on_peer)

    def xpath_vsys(self):
        return "/config/shared"

    def xpath_panorama(self):
        return "/config/panorama"

    def panorama(self):
        return self

    def commit_all(self, sync=False, sync_all=True, exception=False, devicegroup=None, serials=(), cmd=None):
        """Trigger a commit-all (commit to devices) on Panorama

        Args:
            sync (bool): Block until the Panorama commit is finished (Default: False)
            sync_all (bool): Block until every Firewall commit is finished, requires sync=True (Default: False)
            exception (bool): Create an exception on commit errors (Default: False)
            devicegroup (str): Limit commit-all to a single device-group
            serials (list): Limit commit-all to these serial numbers
            cmd (str): Commit options in XML format

        Returns:
            dict: Commit results

        """
        self._logger.debug("Commit-all initiated on device: %s" % (self.id,))

        if cmd is None:
            # XXX: This only works on PAN-OS 7.0+
            e = ET.Element("commit-all")
            if devicegroup is not None and cmd is None:
                sp = ET.SubElement(e, "shared-policy")
                dg = ET.SubElement(sp, "device-group")
                dg_e = ET.SubElement(dg, "entry", {"name": devicegroup})
                if serials:
                    d = ET.SubElement(dg_e, "devices")
                    for serial in serials:
                        ET.SubElement(d, "entry", {"name": serial})
            cmd = ET.tostring(e)
        elif isinstance(cmd, pan.commit.PanCommit):
            cmd = cmd.cmd()
        elif isinstance(cmd, ET.Element):
            cmd = ET.tostring(cmd)

        result = self._commit(sync=sync,
                              sync_all=sync_all,
                              commit_all=True,
                              exception=exception,
                              cmd=cmd)
        return result

    def refresh_devices(self, devices=(), only_connected=False, expand_vsys=True, include_device_groups=True, add=False, running_config=False):
        """Refresh device groups and devices using config and operational commands

        Uses operational command in addition to configuration to gather as much information
        as possible about Panorama connected devices. The operational commands used are
        'show devices all/connected' and 'show devicegroups'.

        Information gathered about each device includes:

        - management IP address (can be different from hostname)
        - serial
        - version
        - high availability peer releationships
        - panorama connection status
        - device-group sync status

        Args:
            devices (list): Limit refresh to these serial numbers
            only_connected (bool): Ignore devices that are not 'connected' to Panorama (Default: False)
            expand_vsys (bool): Instantiate a Firewall object for every Vsys (Default: True)
            include_device_groups (bool): Instantiate :class:`pandevice.panorama.DeviceGroup` objects with Firewall
                objects added to them.
            add (bool): Add the new tree of instantiated DeviceGroup and Firewall objects to the Panorama config tree.
                Warning: This removes all current DeviceGroup and Firewall objects from the configuration tree, and all
                their children, so it is typically done before building a configuration tree. (Default: False)
            running_config (bool): Refresh devices from the running configuration (Default: False)

        Returns:
            list: If 'include_device_groups' is True, returns a list containing new DeviceGroup instances which
            contain new Firewall instances. Any Firewall that is not in a device-group is in the list with the
            DeviceGroup instances.
            If 'include_device_groups' is False, returns a list containing new Firewall instances.

        """
        logger.debug(self.id + ": refresh_devices called")
        try:
            # Test if devices is iterable
            test_iterable = iter(devices)
        except TypeError:
            # This probably means a single device was passed in, not an iterable.
            # Convert to an iterable with a single item.
            devices = (devices,)
        # Remove None from list of devices
        devices = [x for x in devices if x is not None]
        # Get the list of managed devices
        if only_connected:
            cmd = "show devices connected"
        else:
            cmd = "show devices all"
        devices_xml = self.op(cmd)
        devices_xml = devices_xml.find("result/devices")

        # Filter to only requested devices
        if devices:
            filtered_devices_xml = ET.Element("devices")
            for device in devices:
                serial = str(device)
                if serial is None:
                    continue
                entry = devices_xml.find("entry[@name='%s']" % serial)
                if entry is None:
                    if only_connected:
                        raise err.PanNotConnectedOnPanorama("Can't find device with serial %s attached and connected"
                                                 " to Panorama at %s" % (serial, self.id))
                    else:
                        raise err.PanNotAttachedOnPanorama("Can't find device with serial %s attached to Panorama at %s" %
                                                 (serial, self.id))
                multi_vsys = yesno(entry.findtext("multi-vsys"))
                try:
                    vsys = device.vsys
                except AttributeError:
                    continue
                # Create entry if needed
                if filtered_devices_xml.find("entry[@name='%s']" % serial) is None:
                    entry_copy = deepcopy(entry)
                    # If looking for specific vsys, erase all vsys in filtered entry
                    if vsys != "shared" and vsys is not None:
                        entry_copy.remove(entry_copy.find("vsys"))
                        ET.SubElement(entry_copy, "vsys")
                    filtered_devices_xml.append(entry_copy)
                # Get specific vsys
                if vsys != "shared" and vsys is not None:
                    vsys_entry = entry.find("vsys/entry[@name='%s']" % vsys)
                    if vsys_entry is None:
                        raise err.PanNotAttachedOnPanorama("Can't find device with serial %s and"
                                                           " vsys %s attached to Panorama at %s" %
                                                           (serial, vsys, self.id))
                    vsys_section = filtered_devices_xml.find("entry[@name='%s']/vsys" % serial)
                    vsys_section.append(vsys_entry)
            devices_xml = filtered_devices_xml

        # Manipulate devices_xml so each vsys is a separate device
        if expand_vsys:
            original_devices_xml = deepcopy(devices_xml)
            devices_xml = ET.Element("devices")
            for entry in original_devices_xml:
                serial = entry.findtext("serial")
                for vsys_entry in entry.findall("vsys/entry"):
                    new_vsys_device = deepcopy(entry)
                    new_vsys_device.set("name", serial)
                    ET.SubElement(new_vsys_device, "vsys_id").text = vsys_entry.get("name")
                    ET.SubElement(new_vsys_device, "vsys_name").text = vsys_entry.findtext("display-name")
                    devices_xml.append(new_vsys_device)

        # Create firewall instances
        tmp_fw = self.FIREWALL_CLASS()
        firewall_instances = tmp_fw.refreshall_from_xml(
            devices_xml, refresh_children=not expand_vsys)

        if not include_device_groups:
            if add:
                self.removeall(self.FIREWALL_CLASS)
                self.extend(firewall_instances)
            return firewall_instances

        # Create device-groups

        # Get the list of device groups from configuration XML
        api_action = self.xapi.show if running_config else self.xapi.get
        devicegroup_configxml = api_action("/config/devices/entry[@name='localhost.localdomain']/device-group")
        devicegroup_configxml = devicegroup_configxml.find("result/device-group")

        # Get the list of device groups from operational commands
        devicegroup_opxml = self.op("show devicegroups")
        devicegroup_opxml = devicegroup_opxml.find("result/devicegroups")

        # Combine the config XML and operational command XML to get a complete picture
        # of the device groups
        if devicegroup_configxml is not None:
            for dg_entry in devicegroup_configxml:
                if dg_entry.find('devices') is None:
                    continue
                for fw_entry in dg_entry.find('devices'):
                    fw_entry_op = devicegroup_opxml.find("entry/devices/entry[@name='%s']" % fw_entry.get("name"))
                    if fw_entry_op is not None:
                        pandevice.xml_combine(fw_entry, fw_entry_op)

        dg = DeviceGroup()
        dg.parent = self
        devicegroup_instances = dg.refreshall_from_xml(
            devicegroup_configxml, refresh_children=False)

        for dg in devicegroup_instances:
            dg_serials = [entry.get("name") for entry in devicegroup_configxml.findall("entry[@name='%s']/devices/entry" % dg.name)]
            # Find firewall with each serial
            for dg_serial in dg_serials:
                # Skip devices not requested
                if devices and dg_serial not in [str(f) for f in devices]:
                    continue
                all_dg_vsys = [entry.get("name") for entry in devicegroup_configxml.findall(
                    "entry[@name='%s']/devices/entry[@name='%s']/vsys/entry" % (dg.name, dg_serial))]
                # Collect the firewall serial entry to get current status information
                fw_entry = devicegroup_configxml.find("entry[@name='%s']/devices/entry[@name='%s']" % (dg.name, dg_serial))
                if not all_dg_vsys:
                    # This is a single-context firewall, assume vsys1
                    all_dg_vsys = ["vsys1"]
                for dg_vsys in all_dg_vsys:
                    # Check if this is a requested vsys in devices argument
                    if devices:
                        try:
                            requested_vsys = [f.vsys for f in devices]
                        except AttributeError:
                            # Passed in string serials, no vsys, so get all vsys
                            pass
                        else:
                            if "shared" not in requested_vsys and None not in requested_vsys and dg_vsys not in requested_vsys:
                                # A specific vsys was requested, and this isn't it, skip
                                continue
                    fw = next((x for x in firewall_instances if x.serial == dg_serial and x.vsys == dg_vsys), None)
                    if fw is None:
                        # It's possible for device-groups to reference a serial/vsys that doesn't exist
                        # In this case, create the FW instance
                        if not only_connected:
                            fw = self.FIREWALL_CLASS(serial=dg_serial, vsys=dg_vsys)
                            dg.add(fw)
                    else:
                        # Move the firewall to the device-group
                        dg.add(fw)
                        firewall_instances.remove(fw)
                        shared_policy_status = fw_entry.findtext("shared-policy-status")
                        if shared_policy_status is None:
                            shared_policy_status = fw_entry.findtext("vsys/entry[@name='%s']/shared-policy-status" % dg_vsys)
                        fw.state.set_shared_policy_synced(shared_policy_status)

        if add:
            for dg in devicegroup_instances:
                found_dg = self.find(dg.name, DeviceGroup)
                if found_dg is not None:
                    # Move the firewalls to the existing devicegroup
                    found_dg.removeall(self.FIREWALL_CLASS)
                    found_dg.extend(dg.children)
                else:
                    # Devicegroup doesn't exist, add it
                    self.add(dg)
            # Add firewalls that are not in devicegroups
            self.removeall(self.FIREWALL_CLASS)
            self.extend(firewall_instances)

        return firewall_instances + devicegroup_instances
