import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class HostServiceCheckTests(unittest.TestCase):
    def test_agent_logs_and_systemd_use_private_host_files(self):
        config = json.loads((ROOT / "deploy/cloudwatch-agent.json").read_text())
        self.assertEqual(config["metrics"]["append_dimensions"], {"InstanceId": "${aws:InstanceId}"})
        self.assertEqual(config["metrics"]["metrics_collected"]["disk"]["resources"],
                         ["/", "/mnt/organicseoops"])
        logs = config["logs"]["logs_collected"]["files"]["collect_list"][0]
        self.assertEqual(logs["log_group_name"], "/organicseoops/production/backend")
        self.assertEqual(logs["retention_in_days"], 30)
        unit = (ROOT / "deploy/organicseoops-service-check@.service").read_text()
        self.assertIn("EnvironmentFile=/etc/organicseoops/monitoring.env", unit)
        self.assertIn("host-service-check.sh %i", unit)
        self.assertIn("OnCalendar=*:0/5", (ROOT / "deploy/organicseoops-service-check@.timer").read_text())
        probe = (ROOT / "deploy/host-service-check.sh").read_text()
        self.assertIn('handler="sync_search_console", enabled=True, next_run_at__lt=', probe)
        self.assertIn('timedelta(hours=2)', probe)
        self.assertNotIn('sync_ga4_landing', probe)

    def test_app_and_worker_liveness_are_distinct_fail_closed_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            docker = Path(tmp) / "docker"
            docker.write_text("#!/bin/sh\nprintf 'docker %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                              "if [ \"$1\" = ps ]; then\n"
                              "  if [ -n \"$FAIL_SERVICE\" ]; then\n"
                              "    case \" $* \" in *\"service=$FAIL_SERVICE\"*) exit 0 ;; esac\n"
                              "  fi\n"
                              "  case \" $* \" in *'service=beat'*) printf 'bbbbbbbbbbbb\\n' ;;"
                              " *) printf 'aaaaaaaaaaaa\\n' ;; esac\nfi\n"
                              "if [ \"$1\" = inspect ]; then\n"
                              "  if [ \"$4\" = bbbbbbbbbbbb ]; then printf 'none\\n';"
                              " else printf 'healthy\\n'; fi\nfi\n"
                              "if [ \"$1\" = exec ]; then printf '0\\n'; fi\n")
            docker.chmod(0o700)
            mountpoint = Path(tmp) / "mountpoint"
            mountpoint.write_text("#!/bin/sh\nexit 0\n")
            mountpoint.chmod(0o700)
            df = Path(tmp) / "df"
            df.write_text("#!/bin/sh\nprintf 'Use%%\\n 42%%\\n'\n")
            df.chmod(0o700)
            aws = Path(tmp) / "aws"
            aws.write_text("#!/bin/sh\nprintf 'aws %s\\n' \"$*\" >> \"$CALL_LOG\"\n")
            aws.chmod(0o700)
            log = Path(tmp) / "calls"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CALL_LOG": str(log),
                   "AWS_REGION": "eu-west-1"}

            def check(role):
                return subprocess.run(["bash", "deploy/host-service-check.sh", role], cwd=ROOT,
                                      env=env, capture_output=True, text=True, check=False)

            self.assertEqual(check("app").returncode, 0)
            calls = log.read_text().splitlines()
            health_call = next(call for call in calls if '"MetricName":"Healthy"' in call)
            self.assertIn('"HostRole","Value":"app"', health_call)
            self.assertIn('"Value":1', health_call)
            self.assertIn('"MetricName":"DiskUsedPercent"', health_call)
            self.assertIn('"Value":42', health_call)
            self.assertIn('"MetricName":"MemUsedPercent"', health_call)
            self.assertTrue(any('"MetricName":"OverdueSearchConsoleSchedules"' in call for call in calls))
            self.assertTrue(any("publish_ops_metrics" in call for call in calls))
            self.assertFalse(any("service=worker-default" in call for call in calls))
            log.unlink()
            self.assertEqual(check("feedback").returncode, 0)
            calls = log.read_text().splitlines()
            self.assertEqual(sum("docker ps" in call for call in calls), 1)
            self.assertFalse(any("publish_ops_metrics" in call for call in calls))
            self.assertIn("service=worker-default", calls[0])
            self.assertIn('"Value":1', calls[-1])
            log.unlink()
            env["FAIL_SERVICE"] = "worker-ai"
            self.assertEqual(check("app").returncode, 1)
            self.assertIn('"Value":0', log.read_text().splitlines()[-1])
            self.assertFalse(any("OverdueSearchConsoleSchedules" in call for call in log.read_text().splitlines()))
            alarms = json.loads((ROOT / "deploy/backup-alarms-stack.json").read_text())["Resources"]
            for alarm in ("MissedDailyBackup", "AppServiceDown", "FeedbackWorkerDown",
                          "AppDataDiskFull", "FeedbackRootDiskFull", "AppMemoryHigh", "FeedbackMemoryHigh"):
                self.assertEqual(alarms[alarm]["Properties"]["TreatMissingData"], "breaching")
                self.assertEqual(alarms[alarm]["Properties"]["AlarmActions"], [{"Ref": "AlarmTopicArn"}])
            self.assertEqual(alarms["AppDataDiskFull"]["Properties"]["Dimensions"],
                             [{"Name": "HostRole", "Value": "app"}])
            overdue_alarm = alarms["OverdueSearchConsoleSchedule"]["Properties"]
            self.assertEqual(overdue_alarm["MetricName"], "OverdueSearchConsoleSchedules")
            self.assertEqual(overdue_alarm["TreatMissingData"], "notBreaching")
            for name, metric in (("OverdueCustomerDeletion", "OverdueCustomerDeletionRuns"),
                                 ("ClosedTenantWithoutDeletionRun", "ClosedTenantsMissingDeletionRun")):
                row = alarms[name]["Properties"]
                self.assertEqual((row["Namespace"], row["MetricName"]), ("OrganicSEOOps/Jobs", metric))
                self.assertEqual(row["Dimensions"], [{"Name": "Environment", "Value": "production"}])
                self.assertEqual((row["Threshold"], row["TreatMissingData"]), (1, "breaching"))
                self.assertEqual(row["AlarmActions"], [{"Ref": "AlarmTopicArn"}])


if __name__ == "__main__":
    unittest.main()
