# Scratch Radicale for Task Manager development (spec §8).
# Version-pinned to match production (3.7.4). This instance is disposable and
# isolated: its own port (5233), its own storage volume, its own test user.
# It must NEVER be pointed at ~/radicale/collections.
FROM python:3.13-slim

# bcrypt/passlib included so the scratch box can mirror production auth if needed;
# the default scratch config uses plaintext htpasswd for simplicity.
RUN pip install --no-cache-dir radicale==3.7.4 bcrypt passlib

# Radicale writes here; the compose file bind-mounts a host dir over it so the
# collection tree can be inspected and the .Radicale.cache can be deleted to
# exercise the invalid-sync-token path (spec invariant #6).
RUN mkdir -p /data/collections

EXPOSE 5232
CMD ["python", "-m", "radicale", "--config", "/config/config"]
