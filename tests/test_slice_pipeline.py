"""Exercise slicing and HTTP errors with synthetic projects and no printer access."""
import io
import json
import os
import subprocess
import unittest
import zipfile
from unittest.mock import Mock, patch

from test_server import START, gcode, server, zip_of


class SlicePipelineTest(unittest.TestCase):
    def test_version_handles_missing_and_unrecognised_studio(self):
        for text, expected in (("BambuStudio-2.3.1.50", "2.3.1.50"), ("other", "unknown")):
            with self.subTest(text=text), patch.object(server.subprocess, "run", return_value=Mock(stdout=text)):
                self.assertEqual(expected, server.version())
        with patch.object(server.subprocess, "run", side_effect=OSError("not installed")):
            self.assertIn("not installed", server.version())

    def test_bed_override_only_changes_selected_plate_and_preserves_other_files(self):
        source = zip_of({
            "Metadata/model_settings.config": '<config><plate><metadata key="plater_id" value="1"/><metadata key="curr_bed_type" value="Cool Plate"/></plate><plate><metadata key="plater_id" value="2"/></plate></config>',
            "Metadata/project_settings.config": '{"name":"test"}',
            "3D/model": b"original",
        })
        with zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 1, "textured_plate"))) as z:
            model = z.read("Metadata/model_settings.config").decode()
            self.assertEqual(1, model.count("Textured PEI Plate"))
            self.assertEqual("Textured PEI Plate", json.loads(z.read("Metadata/project_settings.config"))["curr_bed_type"])
            self.assertEqual(b"original", z.read("3D/model"))
        with zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 0, "hot_plate"))) as z:
            self.assertEqual(2, z.read("Metadata/model_settings.config").count(b"High Temp Plate"))
        self.assertEqual(source, server.set_bed_type(source, 9, "cool_plate"))
        self.assertEqual(source, server.set_bed_type(source, 1, "unknown"))
        for broken in (b"not zip", zip_of({}), zip_of({"Metadata/model_settings.config": b"\xff"})):
            self.assertEqual(broken, server.set_bed_type(broken, 1, "cool_plate"))

    def test_bed_override_survives_invalid_or_absent_project_settings(self):
        for cfg in (b"invalid json", b"[]", b"\xff"):
            source = zip_of({"Metadata/model_settings.config": '<plate><metadata key="plater_id" value="1"/></plate>', "Metadata/project_settings.config": cfg})
            with zipfile.ZipFile(io.BytesIO(server.set_bed_type(source, 1, "cool_plate"))) as z:
                self.assertIn(b"Cool Plate", z.read("Metadata/model_settings.config"))
                self.assertEqual(cfg, z.read("Metadata/project_settings.config"))

    def test_successful_slice_preserves_pictures_summarises_and_cleans_workspace(self):
        source = zip_of({"Metadata/project_settings.config": "{}", "Metadata/plate_1.png": b"picture"})
        workspaces = []

        def studio(cmd, **kwargs):
            workspaces.append(kwargs["cwd"])
            out = cmd[cmd.index("--outputdir") + 1]
            with open(os.path.join(out, "sliced.gcode.3mf"), "wb") as f:
                f.write(zip_of({"Metadata/plate_1.gcode": gcode(START), "Metadata/slice_info.config": '<config><plate><metadata key="index" value="1"/><metadata key="prediction" value="42.5"/><metadata key="weight" value="3.2"/><filament id="1" type="PLA"/></plate></config>'}))
            with open(os.path.join(out, "result.json"), "w") as f:
                json.dump({"return_code": 0}, f)
            return Mock(returncode=0)

        with patch.object(server.subprocess, "run", side_effect=studio), patch.object(server, "conversion", return_value=(["--load-settings", "preset"], "old printer")):
            sliced, info = server.slice_3mf(source, 1, "new printer")
        self.assertEqual("old printer", info["converted_from"])
        self.assertEqual(42, info["plates"][0]["seconds"])
        self.assertEqual(3.2, info["plates"][0]["grams"])
        self.assertTrue(info["plates"][0]["has_picture"])
        self.assertEqual("PLA", info["plates"][0]["filaments"][0]["type"])
        with zipfile.ZipFile(io.BytesIO(sliced)) as z:
            self.assertEqual(b"picture", z.read("Metadata/plate_1.png"))
        self.assertTrue(all(not os.path.exists(w) for w in workspaces))

    def test_failed_slice_reports_studio_error_and_cleans_workspace(self):
        source = zip_of({"Metadata/project_settings.config": "{}"})
        workspaces = []

        def studio(cmd, **kwargs):
            workspaces.append(kwargs["cwd"])
            return Mock(returncode=1, stderr="bad geometry", stdout="")

        with patch.object(server.subprocess, "run", side_effect=studio):
            with self.assertRaisesRegex(RuntimeError, "bad geometry"):
                server.slice_3mf(source, 1)
        self.assertFalse(os.path.exists(workspaces[0]))

    def test_summary_and_picture_fallbacks(self):
        self.assertEqual({"plates": [], "bambu": {"return_code": 1}}, server.summary(b"broken", {"return_code": 1, "secret": "omit"}))
        sliced = zip_of({"Metadata/plate_1.png": b"existing"})
        self.assertEqual(sliced, server.keep_pictures(zip_of({"Metadata/plate_1.png": b"source"}), sliced))
        with patch.object(server, "MAX_ENTRIES", 1), self.assertRaises(RuntimeError):
            server.check_zip(zip_of({"one": "a", "two": "b"}))


class RequestTest(unittest.TestCase):
    def handler(self, path="/slice", body=b"PKtest", headers=None):
        h = server.Handler.__new__(server.Handler)
        h.path = path
        h.client_address = (server.INGRESS_PROXY, 1)
        h.headers = {"Content-Length": str(len(body)), **(headers or {})}
        h.rfile = io.BytesIO(body)
        h.sent = []
        h._json = lambda status, data: h.sent.append((status, data))
        h._send = lambda *args: h.sent.append(args)
        return h

    def test_get_routes(self):
        with patch.object(server, "VERSION", "2.3.1.50", create=True):
            for path, status in (("/", 200), ("/health", 200), ("/missing", 404)):
                h = self.handler(path)
                h.do_GET()
                self.assertEqual(status, h.sent[0][0])
            self.assertIn(b"2.3.1.50", self.handler_response_root())

    def handler_response_root(self):
        h = self.handler("/")
        h.do_GET()
        return h.sent[0][1]

    def test_bad_requests_are_rejected_before_slicing(self):
        for path, body, headers, status in (
            ("/missing", b"PK", {}, 404),
            ("/slice?plate=x", b"PK", {}, 400),
            ("/slice", b"PK", {"Content-Length": "no"}, 400),
            ("/slice", b"", {}, 400),
            ("/slice", b"no zip", {}, 400),
        ):
            with self.subTest(path=path, headers=headers), patch.object(server, "slice_3mf") as slicer:
                h = self.handler(path, body, headers)
                h.do_POST()
                self.assertEqual(status, h.sent[0][0])
                slicer.assert_not_called()

    def test_busy_request_does_not_consume_body(self):
        with patch.object(server, "LOCK") as lock:
            lock.acquire.return_value = False
            h = self.handler()
            h.do_POST()
            self.assertEqual(503, h.sent[0][0])
            self.assertEqual(b"PKtest", h.rfile.read())
            lock.release.assert_not_called()

    def test_slice_errors_release_lock_and_map_to_http_status(self):
        for error, status in ((subprocess.TimeoutExpired("studio", 1), 504), (RuntimeError("unsafe"), 422), (zipfile.BadZipFile(), 422), (KeyError("settings"), 422)):
            with self.subTest(error=error), patch.object(server, "slice_3mf", side_effect=error), patch.object(server, "LOCK") as lock:
                h = self.handler()
                h.do_POST()
                self.assertEqual(status, h.sent[0][0])
                lock.release.assert_called_once()

    def test_download_returns_binary_and_metadata(self):
        with patch.object(server, "slice_3mf", return_value=(b"sliced", {"plates": []})) as slicer:
            h = self.handler("/slice?plate=2&printer=X1C&bed_type=hot_plate&name=Cube.3mf")
            h.do_POST()
            slicer.assert_called_once_with(b"PKtest", 2, "X1C", "hot_plate")
            self.assertEqual((200, b"sliced", "application/octet-stream"), h.sent[0][:3])
            self.assertIn("Cube.gcode.3mf", h.sent[0][3]["Content-Disposition"])
            self.assertEqual({"plates": []}, json.loads(h.sent[0][3]["X-Pandy-Result"]))

    def test_upload_headers_success_and_failure(self):
        with patch.object(server, "slice_3mf", return_value=(b"sliced", {"plates": []})):
            h = self.handler("/slice?upload=1")
            h.do_POST()
            self.assertEqual(400, h.sent[0][0])
            headers = {"X-Printer-Ip": "192.0.2.1", "X-Printer-Serial": "serial", "X-Printer-Code": "code"}
            with patch.object(server, "upload", return_value="cache/model.gcode.3mf") as upload:
                h = self.handler("/slice?upload=1", headers=headers)
                h.do_POST()
                self.assertEqual(200, h.sent[0][0])
                self.assertEqual(6, h.sent[0][1]["size"])
                upload.assert_called_once_with("192.0.2.1", "serial", "code", "model.gcode.3mf", b"sliced")
            with patch.object(server, "upload", side_effect=OSError("offline")):
                h = self.handler("/slice?upload=1", headers=headers)
                h.do_POST()
                self.assertEqual(502, h.sent[0][0])
                self.assertIn("offline", h.sent[0][1]["error"])

    def test_upload_checks_certificate_before_sending_credentials(self):
        with patch.object(server, "ImplicitFtps") as ftps:
            ftp = ftps.return_value
            ftp.sock.getpeercert.return_value = {"subject": ((("commonName", "SERIAL"),),)}
            self.assertEqual("cache/model.gcode.3mf", server.upload("192.0.2.1", "serial", "code", "model.gcode.3mf", b"data"))
            ftp.login.assert_called_once_with("bblp", "code")
            self.assertEqual("STOR /cache/model.gcode.3mf", ftp.storbinary.call_args.args[0])
            ftp.quit.assert_called_once()
            ftp.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "not OTHER"):
                server.upload("192.0.2.1", "OTHER", "code", "model.gcode.3mf", b"data")
            ftp.login.assert_not_called()
