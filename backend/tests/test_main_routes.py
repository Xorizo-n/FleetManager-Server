import unittest

from main import app


class MainRouteTests(unittest.TestCase):
    def test_installers_router_is_registered(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/installers", paths)
        self.assertIn("/installers/{name}", paths)
        self.assertIn("/installers/{name}/download", paths)

    def test_host_diagnostic_route_is_registered(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/hosts/{host_id}/diagnostics", paths)


if __name__ == "__main__":
    unittest.main()
