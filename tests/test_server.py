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
        finally:
            server.TOKEN = old



class NotAProjectTest(unittest.TestCase):
    def test_a_plain_3mf_is_refused_with_a_reason(self):
        h = server.Handler.__new__(server.Handler)
        body = zip_of({"3D/3dmodel.model": "<model/>"})
        h.path, h.client_address, h.sent = "/slice?plate=1&printer=Bambu+Lab+X1+Carbon+0.4+nozzle", (server.INGRESS_PROXY, 1), []
        h.headers, h.rfile = {"Content-Length": str(len(body))}, io.BytesIO(body)
        h._json = lambda code, obj: h.sent.append((code, obj))
        h.do_POST()
        self.assertEqual(422, h.sent[0][0])
        self.assertIn("Bambu Studio project", h.sent[0][1]["error"])

if __name__ == "__main__":
    unittest.main()

