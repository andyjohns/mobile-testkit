import os.path
import shutil
import time
import logging
import lib.settings

log = logging.getLogger(lib.settings.LOGGER)

from provision.ansible_runner import run_ansible_playbook


def fetch_sync_gateway_logs(prefix):

    log.info("Pulling logs")
    # fetch logs from sync_gateway instances
    run_ansible_playbook("fetch-sync-gateway-logs.yml")

    # zip logs and timestamp
    if os.path.isdir("/tmp/sg_logs"):

        date_time = time.strftime("%Y-%m-%d-%H-%M-%S")
        name = "/tmp/{}-{}-sglogs".format(prefix, date_time)

        shutil.make_archive(name, "zip", "/tmp/sg_logs")

        shutil.rmtree("/tmp/sg_logs")
        log.info("sync_gateway logs copied here {}\n".format(name))


if __name__ == "__main__":
    fetch_sync_gateway_logs(prefix="snapshot")
