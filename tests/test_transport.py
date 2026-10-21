"""Transport mechanics are exercised with sockets and uploads fully mocked."""
import io
import unittest
from unittest.mock import Mock, patch

from test_server import server


class TransportTest(unittest.TestCase):
    def test_implicit_tls_wraps_control_and_resumes_protected_data_session(self):
        context = Mock()
        ftp = server.ImplicitFtps(context=context)
        raw = Mock()
        ftp.sock = raw
        context.wrap_socket.assert_called_once_with(raw)
        self.assertIs(context.wrap_socket.return_value, ftp.sock)
        ftp.host = "printer.test"
        ftp._prot_p = True
        context.reset_mock()
        conn = Mock()
        with patch.object(server.ftplib.FTP, "ntransfercmd", return_value=(conn, 42)) as transfer:
            protected, size = ftp.ntransfercmd("STOR /cache/model", 10)
        transfer.assert_called_once_with(ftp, "STOR /cache/model", 10)
        context.wrap_socket.assert_called_once_with(conn, server_hostname="printer.test", session=ftp.sock.session)
        self.assertIs(context.wrap_socket.return_value, protected)
        self.assertEqual(42, size)
        ftp._prot_p = False
        with patch.object(server.ftplib.FTP, "ntransfercmd", return_value=(conn, None)):
            self.assertEqual((conn, None), ftp.ntransfercmd("LIST"))
        ftp.sock = None
        self.assertIsNone(ftp.sock)

    def test_connection_cap_closes_excess_requests_without_starting_threads(self):
        instance = server.Server.__new__(server.Server)
        instance.slots = Mock()
        request, address = Mock(), ("127.0.0.1", 1)
        instance.shutdown_request = Mock()
        with patch.object(server.ThreadingHTTPServer, "process_request") as process:
            instance.slots.acquire.return_value = False
            instance.process_request(request, address)
            instance.shutdown_request.assert_called_once_with(request)
            process.assert_not_called()
            instance.slots.acquire.return_value = True
            instance.process_request(request, address)
            process.assert_called_once_with(request, address)

    def test_connection_slot_is_released_even_after_worker_failure(self):
        instance = server.Server.__new__(server.Server)
        instance.slots = Mock()
        with patch.object(server.ThreadingHTTPServer, "process_request_thread", side_effect=OSError("closed")):
            with self.assertRaises(OSError):
                instance.process_request_thread(Mock(), ("127.0.0.1", 1))
        instance.slots.release.assert_called_once()

    def test_binary_response_has_exact_length_type_and_custom_headers(self):
        h = server.Handler.__new__(server.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = Mock(), Mock(), Mock()
        h._send(200, b"\x00\xff", "application/octet-stream", {"X-Pandy-Result": "{}"})
        h.send_response.assert_called_once_with(200)
        self.assertEqual(b"\x00\xff", h.wfile.getvalue())
        self.assertIn(unittest.mock.call("Content-Length", "2"), h.send_header.call_args_list)
        self.assertIn(unittest.mock.call("Content-Type", "application/octet-stream"), h.send_header.call_args_list)
        self.assertIn(unittest.mock.call("X-Pandy-Result", "{}"), h.send_header.call_args_list)
        h._json(400, {"error": "bad request"})
        self.assertTrue(h.wfile.getvalue().endswith(b'{"error": "bad request"}'))
