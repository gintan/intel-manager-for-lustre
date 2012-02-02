
from tests.unit.configure.helper import JobTestCaseWithHost, MockAgent


class TestTransitionsWithCommands(JobTestCaseWithHost):
    def test_onejob(self):
        # Our self.host is initially lnet_up
        from configure.models import ManagedHost
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_up')

        from configure.models import Command

        # This tests a state transition which is done by a single job
        command_id = Command.set_state(self.host, 'lnet_down').id
        self.assertEqual(Command.objects.get(pk = command_id).jobs_created, True)
        self.assertEqual(Command.objects.get(pk = command_id).complete, True)
        self.assertEqual(Command.objects.get(pk = command_id).jobs.count(), 1)

        command_id = Command.set_state(self.host, 'lnet_down').id
        self.assertEqual(Command.objects.get(pk = command_id).jobs_created, True)
        self.assertEqual(Command.objects.get(pk = command_id).complete, True)
        self.assertEqual(Command.objects.get(pk = command_id).jobs.count(), 0)

    def test_2steps(self):
        from configure.models import ManagedHost
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_up')

        # This tests a state transition which requires two jobs acting on the same object
        from configure.models import Command
        command_id = Command.set_state(self.host, 'lnet_unloaded').id
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_unloaded')
        self.assertEqual(Command.objects.get(pk = command_id).jobs_created, True)
        self.assertEqual(Command.objects.get(pk = command_id).complete, True)
        self.assertEqual(Command.objects.get(pk = command_id).jobs.count(), 2)


class TestStateManager(JobTestCaseWithHost):
    def test_opportunistic_execution(self):
        # Set up an MGS, leave it offline
        from hydraapi.filesystem import create_fs
        from hydraapi.target import create_target
        from configure.models import ManagedMgs, ManagedMdt, ManagedOst
        mgt = create_target(self._test_lun(self.host).id, ManagedMgs, name = "MGS")
        fs = create_fs(mgt.pk, "testfs", {})
        create_target(self._test_lun(self.host).id, ManagedMdt, filesystem = fs)
        create_target(self._test_lun(self.host).id, ManagedOst, filesystem = fs)

        from configure.lib.state_manager import StateManager
        StateManager.set_state(ManagedMgs.objects.get(pk = mgt.pk), 'unmounted')
        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).state, 'unmounted')
        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version, 0)
        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version_applied, 0)

        try:
            # Make it so that an MGS start operation will fail
            MockAgent.succeed = False

            import configure.lib.conf_param
            configure.lib.conf_param.set_conf_param(fs, "llite.max_cached_mb", "32")

            self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version, 1)
            self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version_applied, 0)
        finally:
            MockAgent.succeed = True

        StateManager.set_state(mgt, 'mounted')
        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).state, 'mounted')

        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version, 1)
        self.assertEqual(ManagedMgs.objects.get(pk = mgt.pk).conf_param_version_applied, 1)

    def test_invalid_state(self):
        from configure.lib.state_manager import StateManager
        with self.assertRaisesRegexp(RuntimeError, "is invalid for"):
            StateManager.set_state(self.host, 'lnet_rhubarb')

    def test_1step(self):
        # Should be a simple one-step operation
        from configure.lib.state_manager import StateManager
        from configure.models import ManagedHost
        # Our self.host is initially lnet_up
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_up')

        # This tests a state transition which is done by a single job
        StateManager.set_state(self.host, 'lnet_down')
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_down')

    def test_2steps(self):
        from configure.lib.state_manager import StateManager
        from configure.models import ManagedHost
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_up')

        # This tests a state transition which requires two jobs acting on the same object
        StateManager.set_state(self.host, 'lnet_unloaded')
        self.assertEqual(ManagedHost.objects.get(pk = self.host.pk).state, 'lnet_unloaded')
