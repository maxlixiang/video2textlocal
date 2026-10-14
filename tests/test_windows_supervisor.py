import unittest
from unittest.mock import Mock
from build_tools.windows_supervisor import Controller

class DesktopFollower(unittest.TestCase):
    def setUp(self):
        self.process=Mock();self.process.poll.return_value=None
        self.job=Mock();self.popen=Mock(return_value=self.process)
        self.control=Controller(['fixture'],Mock(),job_factory=Mock(return_value=self.job),popen=self.popen)
    def test_wait_until_desktop_and_services_ready(self):
        self.control.step(False,True,0);self.control.step(True,False,1);self.popen.assert_not_called()
        self.control.step(True,True,2);self.popen.assert_called_once()
    def test_backend_service_outage_does_not_stop_existing_worker(self):
        self.control.step(True,True,0);self.control.step(True,False,5)
        self.job.close.assert_not_called();self.popen.assert_called_once()
    def test_desktop_exit_stops_only_owned_job(self):
        self.control.step(True,True,0);self.process.poll.return_value=0
        self.control.step(False,False,5);self.job.close.assert_called_once()
        self.assertIsNone(self.control.process)
    def test_worker_failure_uses_backoff(self):
        self.control.step(True,True,0);self.process.poll.return_value=1
        self.control.step(True,True,1);self.assertEqual(self.control.state,'restart_backoff')
        self.popen.assert_called_once();self.control.step(True,True,2);self.popen.assert_called_once()
    def test_desktop_reopen_starts_again(self):
        self.control.step(True,True,0);self.process.poll.return_value=0
        self.control.step(False,False,5);self.process.poll.return_value=None
        self.control.step(True,True,10);self.assertEqual(self.popen.call_count,2)
