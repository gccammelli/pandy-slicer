"""Exercise request handling and the slicer/FTPS boundaries without a printer."""
import ftplib
import http.client
import io
import json
import os
import runpy
import ssl
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_server
from test_server import START, gcode, server, zip_of


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.Server(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.http.server_address, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, body=body, headers={"Authorization": "Bearer test", **(headers or {})})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def setUp(self):
        p = patch.multiple(server, TOKEN="test", VERSION="1.2.3", create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_get_routes_and_authentication(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"1.2.3", body)
        self.assertEqual({"ok": True, "version": "1.2.3"}, json.loads(self.request("GET", "/health")[2]))
        self.assertEqual(404, self.request("GET", "/missing")[0])
        for method, path in [("GET", "/"), ("GET", "/health"), ("POST", "/slice")]:
            self.assertEqual(401, self.request(method, path, headers={"Authorization": "wrong"})[0])
        self.assertEqual(404, self.request("POST", "/missing")[0])

    def test_invalid_requests_do_not_slice(self):
        with patch.object(server, "slice_3mf") as slicer:
            for path, body, headers in [
                ("/slice?plate=oops", b"PK", {}),
                ("/slice", b"PK", {"Content-Length": "oops"}),
                ("/slice", None, {}),
                ("/slice", b"PK", {"Content-Length": str(server.MAX_BYTES + 1)}),
                ("/slice", b"not zip", {}),
            ]:
                self.assertEqual(400, self.request("POST", path, body, headers)[0])
            slicer.assert_not_called()

    def test_download_contains_filename_and_summary(self):
        with patch.object(server, "slice_3mf", return_value=(b"sliced", {"plates": [1]})) as slicer:
            status, headers, body = self.request("POST", "/slice?plate=0&name=Cube.3mf&printer=X1&bed_type=hot_plate", b"PKproject")
        self.assertEqual((200, b"sliced"), (status, body))
        self.assertEqual({"plates": [1]}, json.loads(headers["X-Pandy-Result"]))
        self.assertIn('filename="Cube.gcode.3mf"', headers["Content-Disposition"])
        slicer.assert_called_once_with(b"PKproject", 0, "X1", "hot_plate", "", "")
        self.assertFalse(server.LOCK.locked())

    def test_slice_failures_release_the_lock(self):
        for error, status in [(subprocess.TimeoutExpired("bambu", 1), 504), (RuntimeError("unsafe"), 422), (zipfile.BadZipFile(), 422), (KeyError("settings"), 422)]:
            with self.subTest(error=error), patch.object(server, "slice_3mf", side_effect=error):
                self.assertEqual(status, self.request("POST", "/slice", b"PKproject")[0])
                self.assertFalse(server.LOCK.locked())

    def test_an_unexpected_failure_is_answered_not_dropped(self):
        # A dropped connection shows up as 502 behind Home Assistant's ingress; the caller should get the reason instead.
        with patch.object(server, "slice_3mf", side_effect=ValueError("odd preset")), patch("traceback.print_exc"):
            status, _, body = self.request("POST", "/slice", b"PKproject")
        self.assertEqual(500, status)
        self.assertIn("ValueError: odd preset", json.loads(body)["error"])
        self.assertFalse(server.LOCK.locked())

    def test_busy_rejects_before_slicing(self):
        with patch.object(server, "LOCK") as lock:
            lock.acquire.return_value = False
            self.assertEqual(503, self.request("POST", "/slice", b"PKproject")[0])
            lock.release.assert_not_called()

    def test_ingress_upload_success_missing_credentials_and_failure(self):
        headers = {"X-Printer-Ip": "192.0.2.1", "X-Printer-Serial": "SN", "X-Printer-Code": "code"}
        with patch.object(server.Handler, "_ingress", return_value=True), patch.object(server, "slice_3mf", return_value=(b"sliced", {"plates": []})), patch.object(server, "upload", return_value="cache/Cube.gcode.3mf") as upload:
            self.assertEqual(400, self.request("POST", "/slice?upload=1", b"PKproject")[0])
            upload.assert_not_called()
            status, _, body = self.request("POST", "/slice?upload=1&name=Cube", b"PKproject", headers)
            self.assertEqual(200, status)
            self.assertEqual({"path": "cache/Cube.gcode.3mf", "name": "Cube.gcode.3mf", "size": 6, "plates": []}, json.loads(body))
            upload.assert_called_once_with("192.0.2.1", "SN", "code", "Cube.gcode.3mf", b"sliced")
            upload.side_effect = OSError("disconnected")
            status, _, body = self.request("POST", "/slice?upload=1", b"PKproject", headers)
            self.assertEqual(502, status)
            self.assertIn("disconnected", json.loads(body)["error"])


class SliceTest(unittest.TestCase):
    def test_version_success_unknown_and_unavailable(self):
        for output, expected in [("BambuStudio-2.7.0.11", "2.7.0.11"), ("Bambu Studio", "unknown")]:
            with patch.object(server.subprocess, "run", return_value=SimpleNamespace(stdout=output)):
                self.assertEqual(expected, server.version())
        with patch.object(server.subprocess, "run", side_effect=OSError("missing")):
            self.assertIn("missing", server.version())

    def test_slice_reads_result_preserves_pictures_and_cleans_up(self):
        source = zip_of({"Metadata/project_settings.config": "{}", "Metadata/plate_1.png": b"picture"})
        workspaces = []

        def run(cmd, **kwargs):
            workspaces.append(kwargs["cwd"])
            out = Path(cmd[cmd.index("--outputdir") + 1])
            (out / "sliced.gcode.3mf").write_bytes(zip_of({"Metadata/plate_1.gcode": gcode(START)}))
            (out / "result.json").write_text('{"return_code":0}')
            return SimpleNamespace(returncode=0)

        with patch.object(server.subprocess, "run", side_effect=run), patch.object(server, "conversion", return_value=(["--load-settings", "preset"], "A1")):
            result, info = server.slice_3mf(source, 1, "X1")
        self.assertEqual("A1", info["converted_from"])
        self.assertEqual(b"picture", zipfile.ZipFile(io.BytesIO(result)).read("Metadata/plate_1.png"))
        self.assertTrue(all(not os.path.exists(p) for p in workspaces))

    def test_slice_reports_cli_error_and_cleans_up(self):
        workspaces = []

        def run(cmd, **kwargs):
            workspaces.append(kwargs["cwd"])
            return SimpleNamespace(returncode=1, stderr="invalid model", stdout="")

        with patch.object(server.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(RuntimeError, "invalid model"):
                server.slice_3mf(zip_of({"Metadata/project_settings.config": "{}"}), 1)
        self.assertTrue(all(not os.path.exists(p) for p in workspaces))

    def test_summary_contains_plate_filament_and_picture(self):
        sliced = zip_of({"Metadata/slice_info.config": '<plate><metadata key="index" value="2"/><metadata key="prediction" value="12.5"/><metadata key="weight" value="3.5"/><filament type="PLA" used_g="3.5"/></plate>', "Metadata/plate_2.png": b"png"})
        result = server.summary(sliced, {"return_code": 0, "ignored": 1})
        self.assertEqual({"return_code": 0}, result["bambu"])
        self.assertEqual({"index": 2, "seconds": 12, "grams": 3.5, "printer": "", "nozzle": "", "filaments": [{"type": "PLA", "used_g": "3.5"}], "has_picture": True}, result["plates"][0])

    def test_bed_override_changes_only_selected_plate_and_project(self):
        source = zip_of({"Metadata/model_settings.config": '<root><plate><metadata key="plater_id" value="1"/><metadata key="curr_bed_type" value="Old"/></plate><plate><metadata key="plater_id" value="2"/></plate></root>', "Metadata/project_settings.config": "{}", "3D/model": b"mesh"})
        result = zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 1, "textured_plate")))
        xml = result.read("Metadata/model_settings.config").decode()
        self.assertEqual(1, xml.count("Textured PEI Plate"))
        self.assertEqual("Textured PEI Plate", json.loads(result.read("Metadata/project_settings.config"))["curr_bed_type"])
        self.assertEqual(b"mesh", result.read("3D/model"))
        result = zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 0, "hot_plate")))
        self.assertEqual(2, result.read("Metadata/model_settings.config").decode().count("High Temp Plate"))
        self.assertEqual(source, server.set_bed_type(source, 3, "hot_plate"))
        self.assertEqual(source, server.set_bed_type(source, 1, "auto"))

    def test_bed_override_tolerates_missing_or_invalid_metadata(self):
        for source in [b"bad zip", zip_of({}), zip_of({"Metadata/model_settings.config": b"\xff"})]:
            self.assertEqual(source, server.set_bed_type(source, 1, "hot_plate"))
        for settings in ["bad json", "[]"]:
            source = zip_of({"Metadata/model_settings.config": '<plate><metadata key="plater_id" value="1"/></plate>', "Metadata/project_settings.config": settings})
            result = zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 1, "hot_plate")))
            self.assertIn(b"High Temp Plate", result.read("Metadata/model_settings.config"))
            self.assertEqual(settings.encode(), result.read("Metadata/project_settings.config"))
        source = zip_of({"Metadata/model_settings.config": "<plate></plate>"})
        self.assertEqual(source, server.set_bed_type(source, 0, "hot_plate"))

    def test_heal_leaves_missing_settings_unchanged(self):
        source = zip_of({})
        self.assertEqual(source, server.heal(source))

    def test_slice_without_conversion_or_pictures(self):
        source = zip_of({"Metadata/project_settings.config": "{}"})
        sliced = zip_of({"Metadata/plate_1.gcode": gcode(START)})

        def run(cmd, **kwargs):
            out = Path(cmd[cmd.index("--outputdir") + 1])
            (out / "sliced.gcode.3mf").write_bytes(sliced)
            return SimpleNamespace(returncode=0)

        with patch.object(server.subprocess, "run", side_effect=run):
            result, info = server.slice_3mf(source, 1)
        self.assertEqual(sliced, result)
        self.assertNotIn("converted_from", info)

    def test_missing_filament_presets_keep_original_filament(self):
        fixture = test_server.PresetsTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        source = fixture.project(printer_settings_id="A1", filament_settings_id=["Unknown @BBL A1"])
        args, _ = server.conversion(source, "Bambu Lab X1 Carbon 0.4 nozzle")
        self.assertNotIn("--load-filaments", args)
        Path(server.PROFILES, "broken.json").write_text("invalid")
        self.assertEqual({}, server.system_gcodes("broken"))


class FtpsTest(unittest.TestCase):
    def test_upload_verifies_serial_before_sending_credentials(self):
        with patch.object(server, "ImplicitFtps") as cls:
            ftp = cls.return_value
            ftp.sock.getpeercert.return_value = {"subject": ((('commonName', 'sn'),),)}
            self.assertEqual("cache/test.3mf", server.upload("192.0.2.1", "SN", "secret", "test.3mf", b"data"))
            ftp.connect.assert_called_once_with("192.0.2.1", 990, timeout=20)
            ftp.login.assert_called_once_with("bblp", "secret")
            args = ftp.storbinary.call_args.args
            self.assertEqual("STOR /cache/test.3mf", args[0])
            self.assertEqual(b"data", args[1].read())
            ftp.prot_p.assert_called_once()
            ftp.quit.assert_called_once()
            ftp.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "not WRONG"):
                server.upload("192.0.2.1", "WRONG", "secret", "test.3mf", b"data")
            ftp.login.assert_not_called()

    def test_data_connection_reuses_control_tls_session(self):
        context = Mock(spec=ssl.SSLContext)
        ftp = server.ImplicitFtps(context=context)
        ftp.host = "printer"
        ftp.sock = Mock()
        self.assertIs(ftp.sock, context.wrap_socket.return_value)
        for protected in [False, True]:
            ftp._prot_p = protected
            raw = Mock()
            with patch.object(ftplib.FTP, "ntransfercmd", return_value=(raw, 12)):
                conn, size = ftp.ntransfercmd("STOR test")
            self.assertEqual(12, size)
            self.assertIs(context.wrap_socket.return_value if protected else raw, conn)
        self.assertEqual(ftp.sock.session, context.wrap_socket.call_args.kwargs["session"])
        ftp.sock = None
        self.assertIsNone(ftp.sock)


class ServerTest(unittest.TestCase):
    def test_connection_limit_and_slots_returned_on_handler_error(self):
        http = server.Server(("127.0.0.1", 0), server.Handler)
        self.addCleanup(http.server_close)
        http.slots = threading.BoundedSemaphore(1)
        http.slots.acquire()
        with patch.object(http, "shutdown_request") as close:
            http.process_request("socket", ("127.0.0.1", 1))
            close.assert_called_once_with("socket")
        http.slots.release()
        with patch.object(server.ThreadingHTTPServer, "process_request_thread", side_effect=RuntimeError("handler")):
            http.slots.acquire()
            with self.assertRaisesRegex(RuntimeError, "handler"):
                http.process_request_thread("socket", ("127.0.0.1", 1))
            self.assertTrue(http.slots.acquire(blocking=False))
            http.slots.release()

    def test_startup_loads_addon_options_and_starts_server(self):
        for content in ['{"token":" addon "}', "invalid"]:
            with self.subTest(content=content), patch("os.path.exists", return_value=True), patch("builtins.open", unittest.mock.mock_open(read_data=content)), patch("subprocess.run", return_value=SimpleNamespace(stdout="BambuStudio-2.7.0.11")), patch("http.server.ThreadingHTTPServer.__init__", return_value=None), patch("http.server.ThreadingHTTPServer.serve_forever") as serve:
                namespace = runpy.run_path(server.__file__, run_name="__main__")
                serve.assert_called_once()
                if content.startswith("{"):
                    self.assertEqual("addon", namespace["TOKEN"])
