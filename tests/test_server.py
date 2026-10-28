"""Tests for Pandy Slicer's own logic (no Bambu Studio needed): python3 -m unittest discover tests"""
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("server", os.path.join(HERE, "..", "pandy_slicer", "server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

START = "G28\nM1002 gcode_claim_action : 2\nG29\n"


def zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body if isinstance(body, bytes) else body.encode())
    return buf.getvalue()


def gcode(start: str) -> str:
    return start + "; CHANGE_LAYER\nG1 X1 E1\n"


class SafetyTest(unittest.TestCase):
    def test_refuses_a_file_without_the_start_sequence(self):
        placeholder = zip_of({"Metadata/plate_1.gcode": gcode("G28 ; home all axes\nG1 Z5 F5000\n")})
        with self.assertRaises(RuntimeError):
            server.check_safe(placeholder)

    def test_accepts_bambus_start_sequence(self):
        server.check_safe(zip_of({"Metadata/plate_1.gcode": gcode(START)}))

    def test_refuses_temperatures_beyond_the_printers_limits(self):
        with self.assertRaises(RuntimeError):
            server.check_safe(zip_of({"Metadata/plate_1.gcode": gcode(START + "M104 S999\n")}))
        with self.assertRaises(RuntimeError):
            server.check_safe(zip_of({"Metadata/plate_1.gcode": gcode(START) + "M190 S150\n"}))
        server.check_safe(zip_of({"Metadata/plate_1.gcode": gcode(START + "M104 S220\nM140 S55\nM1002 S999\n; M104 S999\n")}))

    def test_refuses_a_zip_that_unpacks_too_large(self):
        old, server.MAX_UNZIPPED = server.MAX_UNZIPPED, 10
        try:
            with self.assertRaises(RuntimeError):
                server.check_zip(zip_of({"a": "x" * 100}))
        finally:
            server.MAX_UNZIPPED = old

    def test_names_are_safe(self):
        self.assertEqual("Cube + Sphere.gcode.3mf", server.safe_name("../Cube + Sphere.3mf"))
        self.assertEqual("a_b.gcode.3mf", server.safe_name("a;b.gcode.3mf"))


class PresetsTest(unittest.TestCase):
    """A tiny copy of Bambu Studio's profile folders: an X1C preset with its start G-code in an included template."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bbl = self.tmp.name
        for d in ("machine", "process", "filament"):
            os.makedirs(os.path.join(bbl, d))
        def write(path, obj):
            with open(os.path.join(bbl, path), "w") as f:
                json.dump(obj, f)
        write("machine/Bambu Lab X1 Carbon 0.4 nozzle.json", {"name": "Bambu Lab X1 Carbon 0.4 nozzle", "inherits": "base",
              "include": ["X1C start"], "default_print_profile": "0.20mm Standard @BBL X1C"})
        write("machine/X1C start.json", {"name": "X1C start", "machine_start_gcode": START * 10})
        write("process/0.20mm Standard @BBL X1C.json", {"name": "0.20mm Standard @BBL X1C"})
        write("filament/Bambu PLA Basic @BBL X1C.json", {"name": "Bambu PLA Basic @BBL X1C"})
        self.saved = (server.BBL, server.PROFILES)
        server.BBL, server.PROFILES = bbl, os.path.join(bbl, "machine")

    def tearDown(self):
        server.BBL, server.PROFILES = self.saved
        self.tmp.cleanup()

    def project(self, **cfg):
        return zip_of({"Metadata/project_settings.config": json.dumps(cfg)})

    def test_fills_in_missing_start_gcode(self):
        healed = server.heal(self.project(printer_settings_id="Bambu Lab X1 Carbon 0.4 nozzle", machine_start_gcode="G28"))
        cfg = json.loads(zipfile.ZipFile(io.BytesIO(healed)).read("Metadata/project_settings.config"))
        self.assertIn("M1002", cfg["machine_start_gcode"])

    def test_converts_a_profile_keeping_the_designers_settings(self):
        p = self.project(printer_settings_id="Bambu Lab A1 0.4 nozzle", print_settings_id="0.20mm Standard @BBL A1",
                         filament_settings_id=["Bambu PLA Basic @BBL A1"], enable_support="1",
                         different_settings_to_system=["enable_support", "", ""])
        args, source = server.conversion(p, "Bambu Lab X1 Carbon 0.4 nozzle")
        self.assertEqual("Bambu Lab A1 0.4 nozzle", source)
        machine_file, process_file = args[1].split(";")
        with open(machine_file) as f:
            self.assertIn("M1002", json.load(f)["machine_start_gcode"])  # templates merged in
        with open(process_file) as f:
            process = json.load(f)
        self.assertEqual("0.20mm Standard @BBL X1C", process["inherits"])
        self.assertEqual("1", process["enable_support"])
        self.assertEqual(["Bambu Lab X1 Carbon 0.4 nozzle"], process["compatible_printers"])
        self.assertIn("--load-filaments", args)

    def test_replaces_the_projects_own_printer_gcode(self):
        healed = server.heal(self.project(printer_settings_id="Bambu Lab X1 Carbon 0.4 nozzle", machine_start_gcode="M104 S999\n" * 50))
        cfg = json.loads(zipfile.ZipFile(io.BytesIO(healed)).read("Metadata/project_settings.config"))
        self.assertNotIn("S999", cfg["machine_start_gcode"])

    def test_preset_names_cannot_leave_the_profiles_folder(self):
        with open(os.path.join(self.tmp.name, "secret.json"), "w") as f:
            json.dump({"machine_start_gcode": "leak"}, f)
        for name in ("../secret", "/etc/passwd", "..", ".hidden", ""):
            self.assertIsNone(server.preset_path(server.PROFILES, name))
        self.assertEqual({}, server.system_gcodes("../secret"))
        with self.assertRaises(RuntimeError):
            server.conversion(self.project(printer_settings_id="Bambu Lab A1 0.4 nozzle"), "../secret")

    def test_it_prints_in_the_printers_basic_pla(self):
        args, source = server.conversion(server.as_project(zip_of({"3D/3dmodel.model": "<model/>"})), "Bambu Lab X1 Carbon 0.4 nozzle")
        self.assertEqual("", source)
        self.assertIn("--load-filaments", args)
        self.assertIn("Bambu PLA Basic @", args[args.index("--load-filaments") + 1])

    def test_same_printer_needs_no_conversion(self):
        self.assertEqual(([], None), server.conversion(self.project(printer_settings_id="Bambu Lab X1 Carbon 0.4 nozzle"),
                                                       "Bambu Lab X1 Carbon 0.4 nozzle"))


class PicturesTest(unittest.TestCase):
    def test_keeps_the_projects_plate_pictures(self):
        source = zip_of({"Metadata/plate_1.png": b"png", "Metadata/pick_1.png": b"pick", "3D/model": "x"})
        sliced = zip_of({"Metadata/plate_1.gcode": gcode(START)})
        names = zipfile.ZipFile(io.BytesIO(server.keep_pictures(source, sliced))).namelist()
        self.assertIn("Metadata/plate_1.png", names)
        self.assertIn("Metadata/pick_1.png", names)
        self.assertNotIn("3D/model", names)



class TokenTest(unittest.TestCase):
    def authorized(self, ip, header=""):
        h = server.Handler.__new__(server.Handler)
        h.client_address, h.headers, h.sent = (ip, 1), {"Authorization": header}, []
        h._json = lambda code, obj: h.sent.append(code)
        return h._authorized()

    def test_token_is_required_directly_but_not_through_home_assistant(self):
        old, server.TOKEN = server.TOKEN, "secret"
        try:
            self.assertFalse(self.authorized("203.0.113.9"))
            self.assertTrue(self.authorized("203.0.113.9", "Bearer secret"))
            self.assertTrue(self.authorized(server.INGRESS_PROXY))
            self.assertFalse(self.authorized("203.0.113.9", "Bearer secreT"))
        finally:
            server.TOKEN = old

    def test_without_a_token_only_home_assistant_is_let_in(self):
        old, server.TOKEN = server.TOKEN, ""
        try:
            self.assertFalse(self.authorized("10.20.30.40"))
            self.assertFalse(self.authorized("10.20.30.40", "Bearer "))
            self.assertTrue(self.authorized(server.INGRESS_PROXY))
        finally:
            server.TOKEN = old



class PlainModelTest(unittest.TestCase):
    """A plain 3MF (an STL wrapped by Pandy, or a Thingiverse/Printables 3MF) has no settings of its own."""
    MODEL = {"3D/3dmodel.model": "<model/>"}

    def test_a_plain_3mf_needs_a_printer_to_slice_for(self):
        h = server.Handler.__new__(server.Handler)
        body = zip_of(self.MODEL)
        h.path, h.client_address, h.sent = "/slice?plate=1", (server.INGRESS_PROXY, 1), []
        h.headers, h.rfile = {"Content-Length": str(len(body))}, io.BytesIO(body)
        h._json = lambda code, obj: h.sent.append((code, obj))
        h.do_POST()
        self.assertEqual(422, h.sent[0][0])
        self.assertIn("Choose a printer", h.sent[0][1]["error"])

    def test_it_gets_empty_project_settings_and_is_arranged_on_the_bed(self):
        self.assertTrue(server.bare_model(zip_of(self.MODEL)))
        project = server.as_project(zip_of(self.MODEL))
        self.assertFalse(server.bare_model(project))
        cfg = json.loads(zipfile.ZipFile(io.BytesIO(project)).read("Metadata/project_settings.config"))
        self.assertEqual({"printer_settings_id": "", "print_settings_id": "", "filament_settings_id": []}, cfg)
        self.assertFalse(server.bare_model(zip_of({"Metadata/project_settings.config": "{}"})))
        seen = []
        real = (server.subprocess.run, server.conversion, server.check_safe)
        server.conversion = lambda data, target: (["--load-settings", "x"], "")
        server.check_safe = lambda sliced: None
        def fake(cmd, **kw):
            seen.append(cmd)
            out = os.path.join(cmd[cmd.index("--outputdir") + 1], "sliced.gcode.3mf")
            with open(out, "wb") as f:
                f.write(zip_of({"Metadata/plate_1.gcode": gcode(START)}))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        server.subprocess.run = fake
        try:
            server.slice_3mf(zip_of(self.MODEL), 1, "Bambu Lab X1 Carbon 0.4 nozzle")
            server.slice_3mf(zip_of({"Metadata/project_settings.config": "{}"}), 1, "Bambu Lab X1 Carbon 0.4 nozzle")
        finally:
            server.subprocess.run, server.conversion, server.check_safe = real
        self.assertIn("--arrange", seen[0])
        self.assertNotIn("--arrange", seen[1])


class UploadTest(unittest.TestCase):
    def test_printer_upload_is_refused_outside_home_assistant(self):
        old, server.TOKEN = server.TOKEN, "secret"
        try:
            h = server.Handler.__new__(server.Handler)
            h.path, h.client_address, h.sent = "/slice?plate=1&upload=1", ("10.20.30.40", 1), []
            h.headers = {"Authorization": "Bearer secret", "Content-Length": "4", "X-Printer-Code": "12345678"}
            h.rfile = io.BytesIO(b"PK..")
            h._json = lambda code, obj: h.sent.append((code, obj))
            h.do_POST()
            self.assertEqual(400, h.sent[0][0])
            self.assertEqual(b"PK..", h.rfile.read())  # refused before reading the body
        finally:
            server.TOKEN = old


if __name__ == "__main__":
    unittest.main()

