from __future__ import annotations

import unittest
from unittest.mock import patch

from app.shared import env as shared_env


class SharedEnvTests(unittest.TestCase):
    @patch("app.shared.env.os.path.exists")
    @patch("app.shared.env.find_repo_root")
    def test_load_repo_dotenv_allows_env_local_to_override_env(self, mock_find_repo_root, mock_exists) -> None:
        mock_find_repo_root.return_value = "/repo"
        mock_exists.return_value = True
        calls: list[tuple[str, bool]] = []

        def fake_load_dotenv(path: str, override: bool = False):
            calls.append((path, bool(override)))
            return True

        with patch("dotenv.load_dotenv", side_effect=fake_load_dotenv):
            last = shared_env.load_repo_dotenv("/repo/subdir", override=False)

        self.assertEqual(last, "/repo/.env.local")
        self.assertEqual(
            calls,
            [
                ("/repo/.env", False),
                ("/repo/.env.local", True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
