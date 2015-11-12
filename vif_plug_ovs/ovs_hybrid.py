#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from os_vif import plugin
from os_vif import objects

from vif_plug_ovs import processutils
from vif_plug_ovs import linux_net

PLUGIN_NAME = 'ovs_hybrid'


class OvsHybridPlugin(plugin.PluginBase):
    """
    An OVS VIF type that uses a pair of devices in order to allow
    security group rules to be applied to traffic coming in or out of
    a virtual machine.
    """
    
    def __init__(self, **config):
        processutils.configure(**config)
        linux_net.configure(**config)
        self.network_device_mtu = config.get('network_device_mtu', 1500)

    def get_supported_vifs(self):
        return set([objects.PluginVIFSupport(PLUGIN_NAME, '1.0', '1.0')])

    def plug(self, instance, vif):
        """Plug using hybrid strategy

        Create a per-VIF linux bridge, then link that bridge to the OVS
        integration bridge via a veth device, setting up the other end
        of the veth device just like a normal OVS port. Then boot the
        VIF on the linux bridge using standard libvirt mechanisms.
        """
        iface_id = vif.ovs_interfaceid
        br_name = vif.br_name
        v1_name, v2_name = vif.veth_pair_names

        if not linux_net.device_exists(br_name):
            processutils.execute('brctl', 'addbr', br_name,
                                 run_as_root=True)
            processutils.execute('brctl', 'setfd', br_name, 0,
                                 run_as_root=True)
            processutils.execute('brctl', 'stp', br_name, 'off',
                                 run_as_root=True)
            syspath = '/sys/class/net/%s/bridge/multicast_snooping'
            syspath = syspath % br_name
            processutils.execute('tee', syspath, process_input='0',
                                 check_exit_code=[0, 1],
                                 run_as_root=True)

        if not linux_net.device_exists(v2_name):
            linux_net.create_veth_pair(v1_name, v2_name, self.network_device_mtu)
            processutils.execute('ip', 'link', 'set', br_name, 'up',
                                 run_as_root=True)
            processutils.execute('brctl', 'addif', br_name, v1_name,
                                 run_as_root=True)
            linux_net.create_ovs_vif_port(vif.bridge_name,
                                          v2_name, iface_id,
                                          vif.address, instance.uuid)

    def unplug(self, vif):
        """UnPlug using hybrid strategy

        Unhook port from OVS, unhook port from bridge, delete
        bridge, and delete both veth devices.
        """
        br_name = vif.br_name
        v1_name, v2_name = vif.veth_pair_names

        if linux_net.device_exists(br_name):
            processutils.execute('brctl', 'delif', br_name, v1_name,
                                 run_as_root=True)
            processutils.execute('ip', 'link', 'set', br_name, 'down',
                                 run_as_root=True)
            processutils.execute('brctl', 'delbr', br_name,
                                 run_as_root=True)

        linux_net.delete_ovs_vif_port(vif.bridge_name, v2_name)
