import paramiko
import re
import time

from django.utils.unittest import TestCase

from testconfig import config

from tests.integration.core.constants import TEST_TIMEOUT


class ChromaIntegrationTestCase(TestCase):

    def reset_cluster(self, chroma_manager):
        response = chroma_manager.get(
            '/api/filesystem/',
            params = {'limit': 0}
        )
        filesystems = response.json['objects']

        if len(filesystems) > 0:
            # Unmount filesystems
            for client in config['lustre_clients'].keys():
                for filesystem in filesystems:
                    self.unmount_filesystem(client, filesystem['name'])

            # Remove filesystems
            remove_filesystem_command_ids = []
            for filesystem in filesystems:
                response = chroma_manager.delete(filesystem['resource_uri'])
                self.assertTrue(response.successful, response.text)
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_filesystem_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_filesystem_command_ids)

        # Remove MGT
        response = chroma_manager.get(
            '/api/target/',
            params = {'kind': 'MGT', 'limit': 0}
        )
        mgts = response.json['objects']

        if len(mgts) > 0:
            remove_mgt_command_ids = []
            for mgt in mgts:
                response = chroma_manager.delete(mgt['resource_uri'])
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_mgt_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_mgt_command_ids)

        # Remove hosts
        response = chroma_manager.get(
            '/api/host/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']

        if len(hosts) > 0:
            remove_host_command_ids = []
            for host in hosts:
                response = chroma_manager.delete(host['resource_uri'])
                self.assertTrue(response.successful, response.text)
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_host_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_host_command_ids)

        self.verify_cluster_not_configured(chroma_manager, hosts)

    def verify_cluster_not_configured(self, chroma_manager, lustre_servers):
        """
        Checks that the database and the hosts specified in the config
        do not have (unremoved) targets for the filesystems specified.
        """
        # Verify there are zero filesystems
        response = chroma_manager.get(
            '/api/filesystem/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        filesystems = response.json['objects']
        self.assertEqual(0, len(filesystems))

        # Verify there are zero mgts
        response = chroma_manager.get(
            '/api/target/',
            params = {'kind': 'MGT'}
        )
        self.assertTrue(response.successful, response.text)
        mgts = response.json['objects']
        self.assertEqual(0, len(mgts))

        # Verify there are now zero hosts in the database.
        response = chroma_manager.get(
            '/api/host/',
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']
        self.assertEqual(0, len(hosts))

        for host in lustre_servers:
            # Verify mgs and fs targets not in pacemaker config for hosts
            # TODO: sort out host address and host nodename
            stdin, stdout, stderr = self.remote_command(
                host['address'],
                'crm configure show'
            )
            configuration = stdout.read()
            self.assertNotRegexpMatches(
                configuration,
                "location [^\n]* %s\n" % host['nodename']
            )

    def wait_for_command(self, chroma_manager, command_id, timeout=TEST_TIMEOUT, verify_successful=True):
        # TODO: More elegant timeout?
        running_time = 0
        command_complete = False
        while running_time < timeout and not command_complete:
            response = chroma_manager.get(
                '/api/command/%s/' % command_id,
            )
            self.assertTrue(response.successful, response.text)
            command = response.json
            command_complete = command['complete']
            if not command_complete:
                time.sleep(1)
                running_time += 1

        self.assertTrue(command_complete, command)
        if verify_successful and (command['errored'] or command['cancelled']):
            print "COMMAND %s FAILED:" % command['id']
            print "-----------------------------------------------------------"
            print command
            print ''

            for job_uri in command['jobs']:
                response = chroma_manager.get(job_uri)
                self.assertTrue(response.successful, response.text)
                job = response.json
                if job['errored']:
                    print "Job %s Errored:" % job['id']
                    print job
                    print ''
                    for step_uri in job['steps']:
                        response = chroma_manager.get(step_uri)
                        self.assertTrue(response.successful, response.text)
                        step = response.json
                        if step['exception'] and not step['exception'] == 'None':
                            print "Step %s Errored:" % step['id']
                            print step['console']
                            print step['exception']
                            print step['backtrace']
                            print ''

            self.assertFalse(command['errored'] or command['cancelled'], command)

    def wait_for_commands(self, chroma_manager, command_ids, timeout=TEST_TIMEOUT):
        for command_id in command_ids:
            self.wait_for_command(chroma_manager, command_id, timeout)

    def remote_command(self, server, command, expected_return_code=0):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server, **{'username': 'root'})
        transport = ssh.get_transport()
        transport.set_keepalive(20)
        channel = transport.open_session()
        channel.settimeout(TEST_TIMEOUT)
        channel.exec_command(command)
        stdin = channel.makefile('wb')
        stdout = channel.makefile('rb')
        stderr = channel.makefile_stderr()
        if expected_return_code is not None:
            exit_status = channel.recv_exit_status()
            self.assertEqual(exit_status, expected_return_code, stderr.read())
        return stdin, stdout, stderr

    def verify_usable_luns_valid(self, usable_luns, num_luns_needed):

        # Assert meets the minimum number of devices needed for this test.
        self.assertGreaterEqual(len(usable_luns), num_luns_needed)

        # Verify no extra devices not in the config visible.
        response = self.chroma_manager.get(
            '/api/volume_node/'
        )
        self.assertTrue(response.successful, response.text)
        lun_nodes = response.json['objects']

        response = self.chroma_manager.get(
            '/api/host/',
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']

        host_id_to_address = dict((h['id'], h['address']) for h in hosts)
        usable_luns_ids = [l['id'] for l in usable_luns]

        for lun_node in lun_nodes:
            if lun_node['volume_id'] in usable_luns_ids:

                # Create a list of usable device paths for the host of the
                # current lun node as listed in the config.
                host_id = lun_node['host_id']
                host_address = host_id_to_address[host_id]
                host_config = [l for l in config['lustre_servers'] if l['address'] == host_address]
                self.assertEqual(1, len(host_config))
                host_config = host_config[0]
                config_device_paths = host_config['device_paths']
                config_paths = [str(p) for p in config_device_paths]

                self.assertTrue(lun_node['path'] in config_paths,
                    "Path: %s Config Paths: %s" % (
                        lun_node['path'], config_device_paths)
                )

    def set_volume_mounts(self, volume, primary_host_id, secondary_host_id):
        for node in volume['volume_nodes']:
            if node['host_id'] == int(primary_host_id):
                primary_volume_node_id = node['id']
            elif node['host_id'] == int(secondary_host_id):
                secondary_volume_node_id = node['id']

        response = self.chroma_manager.put(
            "/api/volume/%s/" % volume['id'],
            body = {
                "id": volume['id'],
                "nodes": [
                    {
                        "id": secondary_volume_node_id,
                        "primary": False,
                        "use": True,
                    },
                    {
                        "id": primary_volume_node_id,
                        "primary": True,
                        "use": True,
                    }
                ]
            }
        )
        self.assertTrue(response.successful, response.text)

    def verify_volume_mounts(self, volume, expected_primary_host_id, expected_secondary_host_id):
        for node in volume['volume_nodes']:
            if node['primary']:
                self.assertEqual(node['host_id'], int(expected_primary_host_id))
            elif node['use']:
                self.assertEqual(node['host_id'], int(expected_secondary_host_id))

    def create_filesystem(self, name, mgt_volume_id, mdt_volume_id, ost_volume_ids, conf_params = {}, verify_successful = True):
        args = {}
        args['name'] = name
        args['mgt'] = {'volume_id': mgt_volume_id}
        args['mdt'] = {'volume_id': mdt_volume_id}
        args['osts'] = [{'volume_id': id} for id in ost_volume_ids]
        args['conf_params'] = conf_params

        response = self.chroma_manager.post(
            '/api/filesystem/',
            body = args
        )

        self.assertTrue(response.successful, response.text)
        filesystem_id = response.json['filesystem']['id']
        command_id = response.json['command']['id']

        self.wait_for_command(self.chroma_manager, command_id,
            verify_successful=verify_successful)

        response = self.chroma_manager.get(
            '/api/host/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']

        # Verify mgs and fs targets in pacemaker config for hosts
        for host in hosts:
            stdin, stdout, stderr = self.remote_command(
                host['address'],
                'crm configure show'
            )
            configuration = stdout.read()
            self.assertRegexpMatches(
                configuration,
                "location [^\n]* %s\n" % host['nodename']
            )
            self.assertRegexpMatches(
                configuration,
                "primitive %s-" % args['name']
            )
            self.assertRegexpMatches(
                configuration,
                "id=\"%s-" % args['name']
            )

        return filesystem_id

    def mount_filesystem(self, client, filesystem_name, mount_command, expected_return_code=0):
        self.remote_command(
            client,
            "mkdir -p /mnt/%s" % filesystem_name,
            expected_return_code = None  # May fail if already exists. Keep going.
        )

        self.remote_command(
            client,
            mount_command
        )

        stdin, stdout, stderr = self.remote_command(
            client,
            'mount'
        )
        self.assertRegexpMatches(
            stdout.read(),
            " on /mnt/%s " % filesystem_name
        )

    def unmount_filesystem(self, client, filesystem_name):
        stdin, stdout, stderr = self.remote_command(
            client,
            'mount'
        )
        if re.search(" on /mnt/%s " % filesystem_name, stdout.read()):
            self.remote_command(
                client,
                "umount /mnt/%s" % filesystem_name,
            )
            stdin, stdout, stderr = self.remote_command(
                client,
                'mount'
            )
            self.assertNotRegexpMatches(
                stdout.read(),
                " on /mtn/%s " % filesystem_name
            )

    def exercise_filesystem(self, client, filesystem_name):
        # TODO: Expand on this. Perhaps use existing lustre client tests.
        # TODO: read back the size of the filesystem first and don't exceed its size
        self.remote_command(
            client,
            "dd if=/dev/zero of=/mnt/%s/test.dat bs=1K count=100K" % filesystem_name
        )

    def _check_targets_for_volumes_started_on_expected_hosts(self, filesystem_id, volumes_to_expected_hosts, assert_true):
        response = self.chroma_manager.get(
            '/api/target/',
            params = {
                'filesystem_id': filesystem_id,
            }
        )
        self.assertTrue(response.successful, response.text)
        targets = response.json['objects']

        for target in targets:
            target_volume_url = target['volume']
            response = self.chroma_manager.get(target_volume_url)
            self.assertTrue(response.successful, response.text)
            target_volume_id = response.json['id']
            if target_volume_id in volumes_to_expected_hosts:
                expected_host = volumes_to_expected_hosts[target_volume_id]
                if assert_true:
                    self.assertEqual(expected_host, target['active_host_name'])
                else:
                    if not expected_host == target['active_host_name']:
                        return False

        return True

    def targets_for_volumes_started_on_expected_hosts(self, filesystem_id, volumes_to_expected_hosts):
        return self._check_targets_for_volumes_started_on_expected_hosts(filesystem_id, volumes_to_expected_hosts, assert_true = False)

    def verify_targets_for_volumes_started_on_expected_hosts(self, filesystem_id, volumes_to_expected_hosts):
        return self._check_targets_for_volumes_started_on_expected_hosts(filesystem_id, volumes_to_expected_hosts, assert_true = True)
