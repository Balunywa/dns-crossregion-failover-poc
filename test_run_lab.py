import subprocess

import unittest

from unittest.mock import patch



import run_lab





class SubscriptionContextTests(unittest.TestCase):

    def setUp(self):

        self.subscription = run_lab.SUBSCRIPTION

        self.resource_group = run_lab.RG



    def tearDown(self):

        run_lab.SUBSCRIPTION = self.subscription

        run_lab.RG = self.resource_group



    @patch.object(run_lab, "AZ", "az")

    @patch.object(run_lab.subprocess, "run")

    def test_current_subscription_is_resolved_then_pinned(self, execute):

        execute.return_value = subprocess.CompletedProcess([], 0, '{"id":"caller-subscription"}', "")

        run_lab.configure_context(None, "callers-lab")

        self.assertNotIn("--subscription", execute.call_args.args[0])

        self.assertEqual(run_lab.SUBSCRIPTION, "caller-subscription")

        self.assertEqual(run_lab.RG, "callers-lab")

        run_lab.az("group", "show", "-n", run_lab.RG)

        command = execute.call_args.args[0]

        self.assertEqual(command[command.index("--subscription") + 1], "caller-subscription")



    @patch.object(run_lab, "AZ", "az")

    @patch.object(run_lab.subprocess, "run")

    def test_explicit_subscription_name_resolves_to_id(self, execute):

        execute.return_value = subprocess.CompletedProcess([], 0, '{"id":"resolved-subscription-id"}', "")

        run_lab.configure_context("My Subscription", "custom-rg")

        command = execute.call_args.args[0]

        self.assertEqual(command[command.index("--subscription") + 1], "My Subscription")

        self.assertEqual(run_lab.SUBSCRIPTION, "resolved-subscription-id")



    @patch.object(run_lab, "AZ", "az")

    @patch.object(run_lab.subprocess, "run")

    def test_cli_failures_are_not_successful_defaults(self, execute):

        execute.return_value = subprocess.CompletedProcess([], 1, "", "Not authenticated")

        with self.assertRaisesRegex(RuntimeError, "Not authenticated"):

            run_lab.configure_context(None, "custom-rg")



    @patch.object(run_lab, "AZ", "az")

    @patch.object(run_lab.subprocess, "run")

    def test_missing_subscription_is_explicit_error(self, execute):

        execute.return_value = subprocess.CompletedProcess([], 0, "{}", "")

        with self.assertRaisesRegex(RuntimeError, "did not return a subscription"):

            run_lab.configure_context(None, "custom-rg")





if __name__ == "__main__":

    unittest.main()

