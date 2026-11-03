"""Advanced settings are validated and checked against the sliced result."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from test_server import START, gcode, server, zip_of


class AdvancedSettingsTest(unittest.TestCase):
    def test_schema_and_values(self):
        self.assertEqual(len(server.SETTINGS), len(server.SETTINGS_BY_KEY))
        self.assertEqual({"layer_height": "0.12", "sparse_infill_density": "30", "enable_support": "0"},
                         server.parse_settings('{"layer_height":"0.12","sparse_infill_density":"30","enable_support":"0"}'))
        self.assertEqual({}, server.parse_settings(""))
        for invalid in ('[]', '{', '{"machine_start_gcode":"G28"}', '{"layer_height":"nan"}',
                        '{"layer_height":"0.0001"}', '{"wall_loops":"1.5"}', '{"wall_loops":4}',
                        '{"sparse_infill_density":"101"}', '{"brim_type":"bogus"}', '{"enable_support":"true"}',
                        '{"layer_height":"0.2 --no-check"}', '{"wall_loops":"٤"}', " " * 4097):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                server.parse_settings(invalid)

    def test_rejects_conflicting_object_settings_and_incompatible_nozzles(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "Printer.json"), "w") as out:
                json.dump({"nozzle_diameter": ["0.4", "0.2"], "min_layer_height": ["0.08", "0.06"],
                           "max_layer_height": ["0.28", "0.14"]}, out)
            with open(os.path.join(folder, "Template.json"), "w") as out:
                json.dump({"nozzle_diameter": ["0.4"], "min_layer_height": ["0.08"], "max_layer_height": ["0.28"]}, out)
            with open(os.path.join(folder, "Included.json"), "w") as out:
                json.dump({"include": ["Template"]}, out)
            def project(model="<config/>", config='{"printer_settings_id":"Printer"}', **extra):
                return zip_of({"Metadata/project_settings.config": config,
                               "Metadata/model_settings.config": model, **extra})
            with patch.object(server, "PROFILES", folder):
                server.check_setting_scope(project(), {"layer_height": "0.12"}, "Printer")
                server.check_setting_scope(project(), {"layer_height": "0.2"}, "Included")
                with self.assertRaisesRegex(RuntimeError, "between 0.08 and 0.14"):
                    server.check_setting_scope(project(), {"layer_height": "0.2"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "between 0.08 and 0.14"):
                    server.check_setting_scope(project(), {"initial_layer_print_height": "0.05"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "nozzle"):
                    server.check_setting_scope(project(), {"layer_height": "0.1"}, "Missing")
                saved = '{"printer_settings_id":"Missing","nozzle_diameter":["0.4"],"min_layer_height":["0.08"],"max_layer_height":["0.28"]}'
                server.check_setting_scope(project(config=saved), {"layer_height": "0.2"}, "Missing")
                with self.assertRaisesRegex(RuntimeError, "nozzle"):
                    server.check_setting_scope(project(config=saved), {"layer_height": "0.2"}, "Different")
                model = '<config><object id="1"><part><metadata key="wall_loops" value="8"/></part></object></config>'
                with self.assertRaisesRegex(RuntimeError, "Wall loops"):
                    server.check_setting_scope(project(model), {"wall_loops": "3"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "Layer height"):
                    server.check_setting_scope(project(**{"Metadata/layer_heights_profile.txt": "1"}),
                                               {"layer_height": "0.1"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "Wall loops"):
                    server.check_setting_scope(project(**{"Metadata/layer_config_ranges.xml": '<objects><object><range><option opt_key="wall_loops">5</option></range></object></objects>'}),
                                               {"wall_loops": "3"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "per-object"):
                    server.check_setting_scope(project("<broken"), {"wall_loops": "3"}, "Printer")
                with self.assertRaisesRegex(RuntimeError, "third-party object settings"):
                    server.check_setting_scope(project(**{"Metadata/Slic3r_PE_model.config": "<config/>"}),
                                               {"wall_loops": "3"}, "Printer")

    def test_applied_values_are_verified_including_per_nozzle_lists(self):
        settings = {"layer_height": "0.12", "sparse_infill_density": "30", "outer_wall_speed": "80", "enable_support": "1"}
        cfg = {"layer_height": "0.120", "sparse_infill_density": "30%", "outer_wall_speed": ["80", "80.0"], "enable_support": "1"}
        def result(values):
            return zip_of({"Metadata/project_settings.config": json.dumps(values)})
        server.check_applied_settings(result(cfg), settings)
        for changed in ({"outer_wall_speed": ["80", "90"]}, {"enable_support": "0"},
                        {"layer_height": None}, {"sparse_infill_density": "broken"}):
            with self.subTest(changed=changed), self.assertRaisesRegex(RuntimeError, "did not apply"):
                server.check_applied_settings(result({**cfg, **changed}), settings)
        with self.assertRaisesRegex(RuntimeError, "did not apply"):
            server.check_applied_settings(zip_of({}), settings)

    def test_pipeline_passes_validated_options_and_reports_only_verified_values(self):
        source = zip_of({"Metadata/project_settings.config": "{}"})
        settings = {"wall_loops": "4", "sparse_infill_density": "30", "enable_support": "0"}
        observed = []
        def studio(cmd, **kwargs):
            observed.extend(cmd)
            out = cmd[cmd.index("--outputdir") + 1]
            with open(os.path.join(out, "sliced.gcode.3mf"), "wb") as f:
                f.write(zip_of({"Metadata/plate_1.gcode": gcode(START),
                                "Metadata/project_settings.config": '{"wall_loops":"4","sparse_infill_density":"30%","enable_support":"0"}'}))
            return Mock(returncode=0)
        with patch.object(server.subprocess, "run", side_effect=studio):
            _, info = server.slice_3mf(source, 1, settings=settings)
        self.assertIn("--wall-loops=4", observed)
        self.assertIn("--sparse-infill-density=30%", observed)
        self.assertIn("--enable-support=0", observed)
        self.assertEqual(settings, info["applied_settings"])

    def test_settings_endpoint_and_invalid_requests(self):
        def handler(path, headers=None):
            h = server.Handler.__new__(server.Handler)
            h.path, h.client_address = path, (server.INGRESS_PROXY, 1)
            h.headers = {"Content-Length": "2", **(headers or {})}
            h.rfile, h.sent = io.BytesIO(b"PK"), []
            h._json = lambda status, data: h.sent.append((status, data))
            h._send = lambda *args: h.sent.append(args)
            return h
        h = handler("/settings")
        h.do_GET()
        self.assertEqual(1, h.sent[0][1]["version"])
        self.assertEqual(server.SETTINGS, h.sent[0][1]["settings"])
        h = handler("/slice", {"X-Pandy-Slicer-Settings": '{"wall_loops":"-1"}'})
        with patch.object(server, "slice_3mf") as slicer:
            h.do_POST()
            self.assertEqual(400, h.sent[0][0])
            slicer.assert_not_called()
            self.assertEqual(b"PK", h.rfile.read())
        settings = {"wall_loops": "4"}
        h = handler("/slice", {"X-Pandy-Slicer-Settings": json.dumps(settings)})
        with patch.object(server, "slice_3mf", return_value=(b"sliced", {"applied_settings": settings})) as slicer:
            h.do_POST()
            self.assertEqual(settings, slicer.call_args.kwargs["settings"])
            self.assertEqual(settings, json.loads(h.sent[0][3]["X-Pandy-Result"])["applied_settings"])


if __name__ == "__main__":
    unittest.main()
