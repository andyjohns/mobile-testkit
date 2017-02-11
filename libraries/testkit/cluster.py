import os
import json
import time

from requests.exceptions import ConnectionError

from libraries.testkit.syncgateway import SyncGateway
from libraries.testkit.sgaccel import SgAccel
from libraries.testkit.server import Server
from libraries.testkit.admin import Admin
from libraries.testkit.config import Config
from libraries.provision.ansible_runner import AnsibleRunner

from keywords import couchbaseserver
import keywords.SyncGateway

from keywords import utils
import keywords.exceptions
from keywords.utils import log_info
from keywords.SyncGateway import load_sg_accel_config


class Cluster:
    """
    An older remnant of first pass of Python API

    Before using or extending this, check keywords/ClusterKeywords.py to see if it already
    has this functionality
    """

    def __init__(self, config):

        self._cluster_config = config

        if not os.path.isfile(self._cluster_config):
            log_info("Cluster config not found in 'resources/cluster_configs/'")
            raise IOError("Cluster config not found in 'resources/cluster_configs/'")

        log_info(self._cluster_config)

        # Load resources/cluster_configs/<cluster_config>.json
        with open("{}.json".format(config)) as f:
            cluster = json.loads(f.read())

        cbs = [{"name": cbs["name"], "ip": cbs["ip"]} for cbs in cluster["couchbase_servers"]]
        sgs = [{"name": sg["name"], "ip": sg["ip"]} for sg in cluster["sync_gateways"]]
        acs = [{"name": ac["name"], "ip": ac["ip"]} for ac in cluster["sg_accels"]]

        log_info("cbs: {}".format(cbs))
        log_info("sgs: {}".format(sgs))
        log_info("acs: {}".format(acs))

        self.sync_gateways = [SyncGateway(cluster_config=self._cluster_config, target=sg) for sg in sgs]
        self.sg_accels = [SgAccel(cluster_config=self._cluster_config, target=ac) for ac in acs]
        self.servers = [Server(cluster_config=self._cluster_config, target=cb) for cb in cbs]
        self.sync_gateway_config = None  # will be set to Config object when reset() called

        # for integrating keywords
        self.cb_server = couchbaseserver.CouchbaseServer(self.servers[0].url)
        self.sg = keywords.SyncGateway.SyncGateway(self.sync_gateways[0].url)
        if len(acs) > 0:
            self.sa = keywords.SyncGateway.SGAccel(self.sg_accels[0].url)

    def validate_cluster(self):
        # Validate sync gateways
        if len(self.sync_gateways) == 0:
            raise Exception("Functional tests require at least 1 index reader")

    def reset(self, sg_config_path):

        self.validate_cluster()

        ansible_runner = AnsibleRunner(self._cluster_config)
        # Parse config and grab bucket names
        config_path_full = os.path.abspath(sg_config_path)
        config = Config(config_path_full)
        mode = config.get_mode()
        bucket_name_set = config.get_bucket_name_set()

        # Stop sync_gateways
        log_info(">>> Stopping sync_gateway")
        status = self.sg.stop_sync_gateway(self._cluster_config, self.sync_gateways[0].url)
        assert status == 0, "Failed to stop sync gateway"

        if mode == "di":
            # Stop sg_accels
            log_info(">>> Stopping sg_accel")
            # status = ansible_runner.run_ansible_playbook("stop-sg-accel.yml")
            status = self.sa.stop_sg_accel(self._cluster_config, self.sg_accels[0].url)
            assert status == 0, "Failed to stop sg_accel"

            # Deleting sg_accel artifacts
            log_info(">>> Deleting sg_accel artifacts")
            status = ansible_runner.run_ansible_playbook("delete-sg-accel-artifacts.yml")
            assert status == 0, "Failed to delete sg_accel artifacts"

        # Deleting sync_gateway artifacts
        log_info(">>> Deleting sync_gateway artifacts")
        status = ansible_runner.run_ansible_playbook("delete-sync-gateway-artifacts.yml")
        assert status == 0, "Failed to delete sync_gateway artifacts"

        # Delete buckets
        log_info(">>> Deleting buckets on: {}".format(self.cb_server.url))
        self.cb_server.delete_buckets()

        self.sync_gateway_config = config

        log_info(">>> Creating buckets on: {}".format(self.cb_server.url))
        log_info(">>> Creating buckets {}".format(bucket_name_set))
        self.cb_server.create_buckets(bucket_name_set)

        # Wait for server to be in a warmup state to work around
        # https://github.com/couchbase/sync_gateway/issues/1745
        log_info(">>> Waiting for Server: {} to be in a healthy state".format(self.cb_server.url))
        self.cb_server.wait_for_ready_state()

        log_info(">>> Starting sync_gateway with configuration: {}".format(config_path_full))
        utils.dump_file_contents_to_logs(config_path_full)

        # Start sync-gateway
        status = self.sg.start_sync_gateway(self._cluster_config, self.sync_gateways[0].url, config_path_full)
        assert status == 0, "Failed to start to Sync Gateway"

        # HACK - only enable sg_accel for distributed index tests
        # revise this with https://github.com/couchbaselabs/sync-gateway-testcluster/issues/222
        # if mode == "di":
        #    # Start sg-accel
        #    status = ansible_runner.run_ansible_playbook(
        #        "start-sg-accel.yml",
        #        extra_vars={
        #            "sync_gateway_config_filepath": config_path_full
        #        }
        #    )

        # Validate CBGT
        if mode == "di":
            sa_config_path_data = load_sg_accel_config(config_path_full, self.cb_server.url)
            temp_di_conf = "/".join(config_path_full.split('/')[:-2]) + '/temp_conf_di.json'
            log_info("TEMP_DI_CONF: {}".format(temp_di_conf))

            with open(temp_di_conf, 'w') as fp:
                json.dump(sa_config_path_data, fp)

            status = self.sa.start_sg_accel(self._cluster_config, self.sg_accels[0].url, temp_di_conf)
            assert status == 0, "Failed to start sg_accel"
            os.remove(temp_di_conf)

            if not self.validate_cbgt_pindex_distribution_retry(len(self.sg_accels)):
                self.save_cbgt_diagnostics()
                raise Exception("Failed to validate CBGT Pindex distribution")
            log_info(">>> Detected valid CBGT Pindex distribution")
        else:
            log_info(">>> Running in channel cache")

        return mode

    def save_cbgt_diagnostics(self):

        # CBGT REST Admin API endpoint
        for sync_gateway_writer in self.sg_accels:

            adminApi = Admin(sync_gateway_writer)
            cbgt_diagnostics = adminApi.get_cbgt_diagnostics()
            adminApi.get_cbgt_config()

            # dump raw diagnostics
            pretty_print_json = json.dumps(cbgt_diagnostics, sort_keys=True, indent=4, separators=(',', ': '))
            log_info("SG {} CBGT diagnostic output: {}".format(sync_gateway_writer, pretty_print_json))

    def validate_cbgt_pindex_distribution_retry(self, num_running_sg_accels):
        """
        Validates the CBGT pindex distribution by looking for nodes that don't have
        any pindexes assigned to it
        """
        for i in xrange(10):
            is_valid = self.validate_cbgt_pindex_distribution(num_running_sg_accels)
            if is_valid:
                return True
            else:
                log_info("Could not validate CBGT Pindex distribution.  Will retry after sleeping ..")
                time.sleep(5)

        return False

    def validate_cbgt_pindex_distribution(self, num_running_sg_accels):

        if num_running_sg_accels < 1:
            raise keywords.exceptions.ClusterError("Need at least one sg_accel running to verify pindexes")

        # build a map of node -> num_pindexes
        node_defs_pindex_counts = {}

        # CBGT REST Admin API endpoint
        adminApi = Admin(self.sg_accels[0])
        cbgt_cfg = adminApi.get_cbgt_config()

        # loop over the planpindexes and update the count for the node where it lives
        # this will end up with a dictionary like:
        #  {'74c818f04b99b169': 32, '11886131c807a30e': 32}  (each node uuid has 32 pindexes)
        plan_pindexes = cbgt_cfg.p_indexes
        for data_bucket_key, data_bucket_val in plan_pindexes.iteritems():

            # get the nodes where this pindex lives
            nodes = data_bucket_val["nodes"]
            # it should only live on one node.  if not, abort.
            if len(nodes) > 1:
                raise Exception("Unexpected: a CBGT Pindex was assigned to more than one node")
            # loop over the nodes where this pindex lives and increment the count
            for node in nodes:

                # add a key for this node if we don't already have one
                if node not in node_defs_pindex_counts:
                    node_defs_pindex_counts[node] = 0

                current_pindex_count = node_defs_pindex_counts[node]
                current_pindex_count += 1
                node_defs_pindex_counts[node] = current_pindex_count

        log_info("CBGT node to pindex counts: {}".format(node_defs_pindex_counts))

        # make sure number of unique node uuids is equal to the number of sync gateway writers
        if len(node_defs_pindex_counts) != num_running_sg_accels:
            log_info("CBGT len(unique_node_uuids) != len(self.sync_gateway_writers) ({} != {})".format(
                len(node_defs_pindex_counts),
                num_running_sg_accels
            ))
            return False

        # make sure that all of the nodes have approx the same number of pindexes assigneed to them
        i = 0
        num_pindex_first_node = 0
        for node_def_uuid, num_pindexes in node_defs_pindex_counts.iteritems():

            if i == 0:
                # it's the first node we've looked at, just record number of pindexes and continue
                num_pindex_first_node = num_pindexes
                i += 1
                continue

            # ok, it's the 2nd+ node, make sure the delta with the first node is less than or equal to 1
            # (the reason we can't compare for equality is that sometimes the pindexes can't be
            # divided evenly across the cluster)
            delta = abs(num_pindex_first_node - num_pindexes)
            if delta > 1:
                log_info("CBGT Sync Gateway node {} has {} pindexes, but other node has {} pindexes.".format(
                    node_def_uuid,
                    num_pindexes,
                    num_pindex_first_node
                ))
                return False

        return True

    def verify_alive(self, mode):
        errors = []
        for sg in self.sync_gateways:
            try:
                info = sg.info()
                log_info("sync_gateway: {}, info: {}".format(sg.url, info))
            except ConnectionError as e:
                log_info("sync_gateway down: {}".format(e))
                errors.append((sg, e))

        if mode == "di":
            for sa in self.sg_accels:
                try:
                    info = sa.info()
                    log_info("sg_accel: {}, info: {}".format(sa.url, info))
                except ConnectionError as e:
                    log_info("sg_accel down: {}".format(e))
                    errors.append((sa, e))

        return errors

    def __repr__(self):
        s = "\n\n"
        s += "Sync Gateways\n"
        for sg in self.sync_gateways:
            s += str(sg)
        s += "\nSync Gateway Accels\n"
        for sgw in self.sg_accels:
            s += str(sgw)
        s += "\nCouchbase Servers\n"
        for server in self.servers:
            s += str(server)
        s += "\n"
        return s
