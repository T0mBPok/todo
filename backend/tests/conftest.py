import os
# Unit/API tests use mocked providers; never start an external background exchange.
os.environ['GOOGLE_SYNC_WORKER']='0'
