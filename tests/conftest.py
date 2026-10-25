import os

# Must be set before `app.config` is first imported by any test module.
os.environ.update(APP_TOKEN="test-token", DB_PATH="/tmp/test_inv.db", ALLOWED_NAMESPACES="demo")
