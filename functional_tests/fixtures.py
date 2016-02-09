import pytest
import base64

import lib.settings

from lib.cluster import Cluster
from utilities.fetch_sg_logs import fetch_sync_gateway_logs

import settings

from subprocess import Popen, PIPE
import os.path

import logging
import lib.settings
from lib.constants import SGMode

log = logging.getLogger(lib.settings.LOGGER)


class RunOptions:

    valid_modes = [SGMode.distributed_index, SGMode.channel_cache]

    def __init__(self, id, mode, reset_data):
        self.id = id,

        assert(mode in self.valid_modes)
        self.mode = mode

        self.reset_data = reset_data


@pytest.fixture
def cluster(request):

    def fetch_logs():

        # Fetch logs if a test fails
        if request.node.rep_call.failed:

            log.error("\n!!!!!!!!!! TEST FAILURE !!!!!!!!!!")
            log.error(request.node.nodeid)

            # example nodeid: tests/test_single_user_multiple_channels.py::test_1
            remove_slash = request.node.nodeid.replace("/", "-")
            test_id_elements = remove_slash.split("::")
            log_zip_prefix = "{0}-{1}".format(test_id_elements[0], test_id_elements[1])

            zip_file_path = fetch_sync_gateway_logs(log_zip_prefix)

            if detected_data_races(zip_file_path):
                log.error("Detected data races in logs: {}".format(zip_file_path))

            if detected_panics(zip_file_path):
                log.error("Detected panics in logs: {}".format(zip_file_path))

    if settings.CAPTURE_SYNC_GATEWAY_LOGS_ON_FAIL:
        request.addfinalizer(fetch_logs)

    log.info("\n--------- TEST -----------")
    log.info(request.node.nodeid)

    # Create cluster
    c = Cluster()
    log.info(c)

    return c


@pytest.fixture
def run_opts(request):
    # Create test id
    log.info("\n--------- IDENTIFIER -----------")

    # Follow the pattern {test-name}-{id}
    random = base64.urlsafe_b64encode(os.urandom(6))
    test_id = "{}{}".format(request.node.nodeid, random)
    test_id = test_id.split("::")[1]
    test_id = test_id.replace("[", "-").replace("]", "-")

    # Set reset parameters
    log.info("--mode: {}".format(request.config.getoption("--mode")))
    log.info("--reset-data: {}".format(request.config.getoption("--reset-data")))

    options = RunOptions(
        id=test_id,
        mode=request.config.getoption("--mode"),
        reset_data=request.config.getoption("--reset-data")
    )

    return options


def detected_data_races(zip_file_path):
    return detected_pattern("DATA RACE", zip_file_path)


def detected_panics(zip_file_path):
    return detected_pattern("panic", zip_file_path)


def detected_pattern(pattern, zip_file_path):

    if not os.path.isfile(zip_file_path):
        log.error("Can't run zipgrep, cannot find zipfile: {}".format(zip_file_path))
        return False

    process = Popen(["zipgrep", pattern, zip_file_path], stdout=PIPE)
    (output, err) = process.communicate()
    exit_code = process.wait()
    if exit_code == 0:
        log.info("Detected pattern {}: {}".format(pattern, output))
    return exit_code == 0






