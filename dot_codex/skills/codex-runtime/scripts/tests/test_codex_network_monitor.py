from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
from pathlib import Path
import plistlib
import socket
import sys
import subprocess
import tempfile
from threading import Thread
from typing import ClassVar
import unittest
from unittest.mock import patch

_MONITOR_PATH = Path(__file__).resolve().parent.parent / "codex-network-monitor"
_MONITOR_LOADER = importlib.machinery.SourceFileLoader("monitor", str(_MONITOR_PATH))
_MONITOR_SPEC = importlib.util.spec_from_loader(_MONITOR_LOADER.name, _MONITOR_LOADER)
if _MONITOR_SPEC is None:
    raise ImportError(f"Cannot load network monitor from {_MONITOR_PATH}")
monitor = importlib.util.module_from_spec(_MONITOR_SPEC)
sys.modules[_MONITOR_SPEC.name] = monitor
_MONITOR_LOADER.exec_module(monitor)


class HeadOnlyHandler(BaseHTTPRequestHandler):
    last_path: ClassVar[str] = ""
    received_sensitive_header: ClassVar[bool] = False

    def do_HEAD(self) -> None:
        type(self).last_path = self.path
        type(self).received_sensitive_header = any(
            name.lower() in ("authorization", "proxy-authorization", "cookie")
            for name in self.headers
        )
        self.send_response(405)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class ClassificationTests(unittest.TestCase):
    def test_default_logs_use_shared_google_drive(self) -> None:
        self.assertEqual(
            monitor.DEFAULT_LOG_DIR,
            Path.home()
            / "Google Drive"
            / "My Drive"
            / "Codex"
            / "runtime"
            / "network-monitor",
        )

    def test_reachable_http_unauthorized_is_healthy(self) -> None:
        probes = (
            monitor.Probe("github.com", "ok", 3, http_status=403),
            monitor.Probe("chatgpt.com", "ok", 4, http_status=401),
        )
        self.assertEqual(monitor.classify(probes, monitor.Route("10.0.0.1", "en0", "active", None)), "healthy")

    def test_codex_authentication_statuses_prove_transport_reachability(self) -> None:
        route = monitor.Route("10.0.0.1", "en0", "active", None)
        for status in (401, 403, 405):
            with self.subTest(status=status):
                probes = (
                    monitor.Probe("chatgpt.com", "ok", 3, http_status=200),
                    monitor.Probe(
                        "chatgpt.com",
                        "ok",
                        4,
                        http_status=status,
                        path=monitor.CODEX_TRANSPORT_PATH,
                    ),
                )
                self.assertEqual(monitor.classify(probes, route), "healthy")

    def test_codex_transport_failure_is_not_a_total_network_outage(self) -> None:
        probes = (
            monitor.Probe("chatgpt.com", "ok", 3, http_status=200),
            monitor.Probe(
                "chatgpt.com",
                "tls",
                4,
                error="SSLError",
                path=monitor.CODEX_TRANSPORT_PATH,
            ),
            monitor.Probe("github.com", "ok", 5, http_status=200),
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        self.assertEqual(monitor.classify(probes, route), "codex_transport_failure")

    def test_codex_server_error_is_distinct_from_connectivity_failure(self) -> None:
        probes = (
            monitor.Probe("chatgpt.com", "ok", 3, http_status=200),
            monitor.Probe(
                "chatgpt.com",
                "ok",
                4,
                http_status=503,
                path=monitor.CODEX_TRANSPORT_PATH,
            ),
        )
        route = monitor.Route("10.0.0.1", "en0", "active", None)
        self.assertEqual(monitor.classify(probes, route), "codex_transport_http_error")

    def test_proxied_codex_success_rules_out_total_direct_dns_failure(self) -> None:
        probes = tuple(
            monitor.Probe(host, "dns", 2, error="resolver_timeout")
            for host in monitor.DEFAULT_HOSTS
        ) + (
            monitor.Probe(
                "chatgpt.com",
                "ok",
                4,
                http_status=405,
                path=monitor.CODEX_TRANSPORT_PATH,
                via_proxy=True,
            ),
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        self.assertEqual(monitor.classify(probes, route), "partial_dns_failure")

    def test_all_dns_failures_with_reachable_gateway_identify_resolver(self) -> None:
        probes = (
            monitor.Probe("github.com", "dns", 2, error="resolver_failed"),
            monitor.Probe("chatgpt.com", "dns", 2, error="resolver_failed"),
        )
        route = monitor.Route("10.0.0.1", "en0", "active", True)
        self.assertEqual(monitor.classify(probes, route), "dns_resolver_failure")

    def test_failed_gateway_is_not_misattributed_to_dns(self) -> None:
        probes = (monitor.Probe("github.com", "dns", 2, error="resolver_failed"),)
        route = monitor.Route("10.0.0.1", "en0", "active", False)
        self.assertEqual(monitor.classify(probes, route), "local_gateway_unreachable")

    def test_missing_default_route_is_local_failure(self) -> None:
        probes = (monitor.Probe("github.com", "tcp", 2, error="TimeoutError"),)
        self.assertEqual(monitor.classify(probes, monitor.Route(None, None, None, None)), "local_route_or_interface")

    def test_one_failed_provider_is_not_internet_outage(self) -> None:
        probes = (
            monitor.Probe("github.com", "tcp", 2, error="TimeoutError"),
            monitor.Probe("chatgpt.com", "ok", 3, http_status=200),
        )
        route = monitor.Route("10.0.0.1", "en0", "active", True)
        self.assertEqual(monitor.classify(probes, route), "provider_specific_failure")

    def test_unresponsive_vpn_gateway_cannot_override_successful_upstreams(self) -> None:
        probes = (
            monitor.Probe("github.com", "dns", 2, error="resolver_timeout"),
            monitor.Probe("api.github.com", "ok", 3, http_status=200),
            monitor.Probe("chatgpt.com", "ok", 4, http_status=403),
            monitor.Probe("service.example", "ok", 5, http_status=302),
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        self.assertEqual(monitor.classify(probes, route), "partial_dns_failure")

    def test_vpn_gateway_icmp_failure_does_not_disguise_resolver_failure(self) -> None:
        probes = (
            monitor.Probe("github.com", "dns", 2, error="resolver_timeout"),
            monitor.Probe("chatgpt.com", "dns", 2, error="resolver_timeout"),
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        self.assertEqual(monitor.classify(probes, route), "dns_resolver_failure")

    def test_one_success_still_rules_out_a_total_vpn_outage(self) -> None:
        probes = (
            monitor.Probe("github.com", "dns", 2, error="resolver_timeout"),
            monitor.Probe("api.github.com", "dns", 3, error="resolver_timeout"),
            monitor.Probe("chatgpt.com", "dns", 4, error="resolver_timeout"),
            monitor.Probe("service.example", "ok", 5, http_status=302),
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        self.assertEqual(monitor.classify(probes, route), "partial_dns_failure")

    def test_common_redirect_identifies_possible_captive_portal(self) -> None:
        probes = (
            monitor.Probe("github.com", "ok", 2, http_status=302, redirect_host="captive.example"),
            monitor.Probe("chatgpt.com", "ok", 2, http_status=302, redirect_host="captive.example"),
        )
        self.assertEqual(monitor.classify(probes, monitor.Route("10.0.0.1", "en0", "active", None)), "possible_captive_portal")

    def test_distinct_provider_redirects_are_not_a_captive_portal(self) -> None:
        probes = (
            monitor.Probe(
                "github.com", "ok", 2, http_status=302, redirect_host="github.example"
            ),
            monitor.Probe(
                "service.example",
                "ok",
                3,
                http_status=302,
                redirect_host="service.enterprise.example",
            ),
        )
        route = monitor.Route("10.0.0.1", "en0", "active", None)
        self.assertEqual(monitor.classify(probes, route), "healthy")


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)
        launch_agents = patch.object(monitor, "ROOT", self.path / "LaunchAgents")
        launch_agents.start()
        self.addCleanup(launch_agents.stop)

    def tearDown(self) -> None:
        logger = logging.getLogger("codex.network")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        self.directory.cleanup()

    @staticmethod
    def observation(classification: str, monotonic: float) -> dict[str, object]:
        return {
            "at": "2026-07-27T00:00:00.000+00:00",
            "monotonic": monotonic,
            "classification": classification,
            "route": {
                "gateway": "10.0.0.1",
                "interface": "en0",
                "interface_status": "active",
                "gateway_reachable": classification != "local_gateway_unreachable",
            },
            "probes": [],
        }

    def test_outage_and_recovery_are_both_recorded(self) -> None:
        subject = monitor.NetworkMonitor(("github.com",), 15, 2, self.path)
        subject.record(self.observation("healthy", 10))
        subject.record(self.observation("dns_resolver_failure", 20))
        subject.record(self.observation("healthy", 30))

        lines = (self.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        self.assertEqual([event["classification"] for event in events], ["healthy", "dns_resolver_failure", "healthy"])
        self.assertEqual(events[1]["outage_id"], events[2]["outage_id"])
        self.assertTrue(events[1]["preceding_samples"])
        status = json.loads((self.path / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["classification"], "healthy")

    def test_steady_state_does_not_write_every_probe(self) -> None:
        subject = monitor.NetworkMonitor(("github.com",), 15, 2, self.path)
        subject.record(self.observation("healthy", 10))
        subject.record(self.observation("healthy", 25))
        subject.record(self.observation("healthy", 310))
        lines = (self.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_logs_are_bounded_by_rotation(self) -> None:
        with patch.object(monitor, "MAX_LOG_BYTES", 256):
            subject = monitor.NetworkMonitor(("github.com",), 15, 2, self.path)
            for index in range(30):
                classification = "healthy" if index % 2 else "dns_resolver_failure"
                subject.record(self.observation(classification, float(index)))
        event_files = list(self.path.glob("events.jsonl*"))
        self.assertLessEqual(len(event_files), monitor.LOG_BACKUPS + 1)
        self.assertLessEqual(sum(item.stat().st_size for item in event_files), 256 * (monitor.LOG_BACKUPS + 1))

    def test_resolver_timeout_is_distinguished(self) -> None:
        with patch.object(monitor, "command", return_value=(-1, "timeout")):
            resolved, error = monitor.resolve("github.com", 0.1)
        self.assertIsNone(resolved)
        self.assertEqual(error, "resolver_timeout")

    def test_codex_probe_sends_only_an_unauthenticated_head(self) -> None:
        address: monitor.SocketAddress = ("192.0.2.1", 443)
        with (
            patch.object(
                monitor,
                "resolve",
                return_value=((socket.AF_INET, address), None),
            ),
            patch.object(monitor.socket, "socket") as socket_factory,
            patch.object(monitor.ssl, "create_default_context") as context_factory,
        ):
            secured = context_factory.return_value.wrap_socket.return_value
            secured.recv.return_value = b"HTTP/1.1 401 Unauthorized\r\n\r\n"
            result = monitor.probe(
                monitor.CODEX_HOST, 2, path=monitor.CODEX_TRANSPORT_PATH
            )
            self.assertEqual(result.phase, "ok")
            self.assertEqual(result.http_status, 401)
            self.assertEqual(result.path, monitor.CODEX_TRANSPORT_PATH)
            socket_factory.return_value.connect.assert_called_once_with(address)
            call = secured.sendall.call_args
            self.assertIsNotNone(call)
            if call is not None:
                request = call.args[0]
                self.assertEqual(
                    request,
                    b"HEAD /backend-api/codex/responses HTTP/1.1\r\n"
                    b"Host: chatgpt.com\r\n"
                    b"User-Agent: codex-network-monitor/1\r\n"
                    b"Connection: close\r\n\r\n",
                )

    def test_codex_transport_is_probed_when_all_direct_dns_lookups_fail(self) -> None:
        direct_probes = [
            monitor.Probe(host, "dns", 2, error="resolver_timeout")
            for host in monitor.DEFAULT_HOSTS
        ]
        codex_transport = monitor.Probe(
            monitor.CODEX_HOST,
            "ok",
            4,
            http_status=405,
            path=monitor.CODEX_TRANSPORT_PATH,
            via_proxy=True,
        )
        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        with (
            patch.object(monitor, "probe", side_effect=direct_probes) as probe_mock,
            patch.object(
                monitor, "probe_codex_transport", return_value=codex_transport
            ) as transport_mock,
            patch.object(monitor, "route_snapshot", return_value=route),
            patch.object(monitor, "resolver_snapshot", return_value={"available": True}),
        ):
            observation = monitor.build_observation(monitor.DEFAULT_HOSTS, 2)
        self.assertEqual(probe_mock.call_count, len(monitor.DEFAULT_HOSTS))
        transport_mock.assert_called_once_with(2)
        self.assertEqual(observation["classification"], "partial_dns_failure")
        probes = observation["probes"]
        self.assertEqual(len(probes), len(monitor.DEFAULT_HOSTS) + 1)
        self.assertEqual(probes[-1]["path"], monitor.CODEX_TRANSPORT_PATH)
        self.assertTrue(probes[-1]["via_proxy"])

    def test_codex_proxy_is_checked_before_direct_dns_probes(self) -> None:
        observed_order: list[str] = []

        def codex_transport(_timeout: float) -> monitor.Probe:
            observed_order.append("codex_transport")
            return monitor.Probe(
                monitor.CODEX_HOST,
                "ok",
                1,
                http_status=405,
                path=monitor.CODEX_TRANSPORT_PATH,
                via_proxy=True,
            )

        def direct_probe(host: str, _timeout: float) -> monitor.Probe:
            observed_order.append(host)
            return monitor.Probe(host, "dns", 1, error="resolver_timeout")

        route = monitor.Route("172.28.2.90", "utun5", "present", False)
        with (
            patch.object(monitor, "probe_codex_transport", side_effect=codex_transport),
            patch.object(monitor, "probe", side_effect=direct_probe),
            patch.object(monitor, "route_snapshot", return_value=route),
            patch.object(monitor, "resolver_snapshot", return_value={"available": True}),
        ):
            observation = monitor.build_observation(monitor.DEFAULT_HOSTS, 2)
        self.assertEqual(observed_order, ["codex_transport", *monitor.DEFAULT_HOSTS])
        self.assertEqual(observation["classification"], "partial_dns_failure")

    def test_transport_helper_uses_credential_free_bounded_head(self) -> None:
        HeadOnlyHandler.last_path = ""
        HeadOnlyHandler.received_sensitive_header = False
        with HTTPServer(("127.0.0.1", 0), HeadOnlyHandler) as server:
            thread = Thread(target=server.handle_request, daemon=True)
            thread.start()
            url = (
                "http://127.0.0.1:"
                + str(server.server_port)
                + monitor.CODEX_TRANSPORT_PATH
            )
            code, output = monitor.command(
                (
                    "/usr/bin/python3",
                    "-c",
                    monitor.CODEX_TRANSPORT_HELPER,
                    url,
                    "1",
                ),
                2,
            )
            thread.join(timeout=1)
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output),
            {"http_status": 405, "phase": "ok", "via_proxy": False},
        )
        self.assertEqual(HeadOnlyHandler.last_path, monitor.CODEX_TRANSPORT_PATH)
        self.assertFalse(HeadOnlyHandler.received_sensitive_header)

    def test_transport_helper_timeout_is_hard_bounded(self) -> None:
        with patch.object(
            monitor, "command", return_value=(-1, "timeout")
        ) as run:
            result = monitor.probe_codex_transport(0.1)
        self.assertEqual(result.phase, "tcp")
        self.assertEqual(result.error, "transport_timeout")
        self.assertEqual(result.path, monitor.CODEX_TRANSPORT_PATH)
        self.assertEqual(
            run.call_args.args[1], 0.1 + monitor.CODEX_TRANSPORT_TIMEOUT_MARGIN
        )

    def test_launch_agent_inherits_only_standard_private_proxy_settings(self) -> None:
        environment = {
            "HTTPS_PROXY": "http://127.0.0.1:12345",
            "NO_PROXY": "localhost,127.0.0.1",
            "UNRELATED_SECRET": "must-not-enter-launch-agent",
        }
        path = monitor.configured_launch_plist(environment, self.path)
        with path.open("rb") as handle:
            configuration = plistlib.load(handle)
        self.assertEqual(
            configuration["EnvironmentVariables"],
            {
                "HTTPS_PROXY": "http://127.0.0.1:12345",
                "NO_PROXY": "localhost,127.0.0.1",
            },
        )
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"must-not-enter-launch-agent", path.read_bytes())

    def test_launch_agent_without_proxy_uses_canonical_template(self) -> None:
        path = monitor.configured_launch_plist({}, self.path)
        self.assertEqual(path, monitor.ROOT / (monitor.LABEL + ".plist"))

    def test_launch_agent_rejects_remote_or_credentialed_proxy_settings(self) -> None:
        for proxy in (
            "http://proxy.example:8080",
            "http://user:private-password@127.0.0.1:12345",
        ):
            with self.subTest(proxy=proxy):
                path = monitor.configured_launch_plist(
                    {"HTTPS_PROXY": proxy, "NO_PROXY": "localhost"}, self.path
                )
                self.assertEqual(path, monitor.ROOT / (monitor.LABEL + ".plist"))

    def test_proxyless_reinstall_does_not_remove_the_running_launch_agent(self) -> None:
        outcomes: list[subprocess.CompletedProcess[str]] = [
            subprocess.CompletedProcess(["plutil"], 0),
            subprocess.CompletedProcess(["launchctl", "print"], 0),
            subprocess.CompletedProcess(["launchctl", "kickstart"], 0),
        ]
        with (
            patch.dict(monitor.os.environ, {}, clear=True),
            patch.object(monitor.subprocess, "run", side_effect=outcomes) as run,
        ):
            self.assertEqual(monitor.install(), 0)
        commands = [invocation.args[0] for invocation in run.call_args_list]
        self.assertEqual(commands[-1][1], "kickstart")
        self.assertFalse(any("bootout" in command for command in commands))


class LaunchPortabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_fresh_machine_generates_a_portable_private_launch_agent(self) -> None:
        launch_agents = self.path / "LaunchAgents"
        with patch.object(monitor, "ROOT", launch_agents):
            path = monitor.ensure_launch_template()

        self.assertEqual(path, launch_agents / (monitor.LABEL + ".plist"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with path.open("rb") as source:
            configuration = plistlib.load(source)
        self.assertEqual(
            configuration["ProgramArguments"],
            ["/usr/bin/python3", str(_MONITOR_PATH), "monitor"],
        )
        self.assertEqual(configuration["WorkingDirectory"], str(Path.home()))
        self.assertNotIn("EnvironmentVariables", configuration)
        self.assertNotIn(b"/.local/", path.read_bytes())

    def test_fresh_machine_launch_agent_generation_is_idempotent(self) -> None:
        launch_agents = self.path / "LaunchAgents"
        with patch.object(monitor, "ROOT", launch_agents):
            first = monitor.ensure_launch_template()
            original = first.read_bytes()
            second = monitor.ensure_launch_template()

        self.assertEqual(first, second)
        self.assertEqual(second.read_bytes(), original)

    def test_fresh_machine_proxy_configuration_excludes_unrelated_secrets(self) -> None:
        launch_agents = self.path / "LaunchAgents"
        logs = self.path / "runtime"
        environment = {
            "HTTPS_PROXY": "http://127.0.0.1:12345",
            "NO_PROXY": "localhost,127.0.0.1",
            "UNRELATED_SECRET": "must-not-enter-launch-agent",
        }
        with patch.object(monitor, "ROOT", launch_agents):
            path = monitor.configured_launch_plist(environment, logs)

        with path.open("rb") as source:
            configuration = plistlib.load(source)
        self.assertEqual(
            configuration["EnvironmentVariables"],
            {
                "HTTPS_PROXY": "http://127.0.0.1:12345",
                "NO_PROXY": "localhost,127.0.0.1",
            },
        )
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"must-not-enter-launch-agent", path.read_bytes())


class PrivateHostConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_missing_private_configuration_uses_public_defaults(self) -> None:
        self.assertEqual(monitor.configured_hosts(self.path), monitor.DEFAULT_HOSTS)

    def test_private_configuration_provides_company_hosts(self) -> None:
        (self.path / "config.json").write_text(
            json.dumps({"hosts": ["github.com", "service.example"]}),
            encoding="utf-8",
        )
        self.assertEqual(
            monitor.configured_hosts(self.path), ("github.com", "service.example")
        )

    def test_malformed_private_configuration_fails_closed(self) -> None:
        (self.path / "config.json").write_text(
            json.dumps({"hosts": ["https://service.example/private"]}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            monitor.configured_hosts(self.path)

    def test_status_is_readable_only_by_its_owner(self) -> None:
        path = self.path / "status.json"
        monitor.write_status(path, {"classification": "healthy"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_event_log_is_readable_only_by_its_owner(self) -> None:
        logger = monitor.logger_for(self.path)
        self.addCleanup(logger.handlers[0].close)
        self.assertEqual((self.path / "events.jsonl").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
