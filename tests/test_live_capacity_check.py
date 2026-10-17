"""Resource monitoring must tolerate creation/removal of its browser container."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import run_live_capacity_check as check


class CapacityMonitorTests(unittest.TestCase):
    def row(self,name):
        return json.dumps(dict(Name=name,CPUPerc='52.00%',MemPerc='12.00%',
            MemUsage='245MiB / 2GiB',PIDs='168',NetIO='20MB / 1MB'))+'\n'

    def test_browser_creation_race_keeps_service_monitoring(self):
        results=[subprocess.CompletedProcess([],1,stdout='',stderr='No such container'),
                 subprocess.CompletedProcess([],0,stdout=self.row(check.SERVICE),stderr='')]
        with patch.object(check.subprocess,'run',side_effect=results) as run:
            values=check.container_resources('new-browser')
        self.assertEqual(list(values),[check.SERVICE])
        self.assertEqual(values[check.SERVICE]['cpu_percent'],52)
        self.assertEqual(run.call_count,2)
        self.assertNotIn('new-browser',run.call_args.args[0])

    def test_running_browser_and_service_are_both_measured(self):
        result=subprocess.CompletedProcess([],0,stdout=self.row(check.SERVICE)+self.row('browser'),stderr='')
        with patch.object(check.subprocess,'run',return_value=result) as run:
            values=check.container_resources('browser')
        self.assertEqual(set(values),{check.SERVICE,'browser'})
        self.assertEqual(values['browser']['pids'],168)
        run.assert_called_once()
