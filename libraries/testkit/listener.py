import subprocess
import requests
import os
import time
import json

from testkit.debug import *

from testkit import settings
import logging
log = logging.getLogger(settings.LOGGER)


# For use with any listener based application (Android only)
class Listener:
    def __init__(self, target, local_port, apk_path, activity, reinstall):

        self.target = target
        self.local_port = local_port

        self.url = ""
        self.install_and_launch_app(target, local_port, apk_path, activity, reinstall)

        if self.is_emulator(target):
            self.url = "http://{}:{}".format(self.get_host_ip(), local_port)
        else:
            self.url = "http://{}:{}".format(self.get_device_ip(target), 5984)

        log.info("Listener running at {} ...".format(self.url))

    def install_and_launch_app(self, target, local_port, apk_path, activity, reinstall):

        # Build monkeyrunner install cmd
        cmd_args = [
            "monkeyrunner",
            "/Users/sethrosetter/Code/sync-gateway-testcluster/utilities/monkeyrunner.py",
            "--target={}".format(target),
            "--apk-path={}".format(apk_path),
            "--activity={}".format(activity),
        ]

        if self.is_emulator(target):
            cmd_args.append("--local-port={}".format(local_port))

        if reinstall:
            cmd_args.append("--reinstall")

        # Execute monkeyrunner install
        monkey_output = subprocess.check_output(cmd_args)
        log.info("OUTPUT: {}".format(monkey_output))

    def is_emulator(self, target):
        return target.startswith("emulator") or target.startswith("192.168")

    def get_host_ip(self):
        cmd_output = subprocess.check_output("ifconfig")
        en0_section = cmd_output.split("\n")[11]
        full_ip = en0_section.split()[1]
        ip = full_ip.split("/")[0]
        return ip

    def get_device_ip(self, target):
        log.info("Getting Device ip ...")
        result = subprocess.check_output(["adb", "-s", "{}".format(target), "shell", "netcfg"])
        log.info("RESULT: {}".format(result))
        ip_line = result.split('\n')[0]
        ip = ip_line.split()[2]
        ip = ip.split("/")[0]
        return ip



    def kill_port_forwarding(self):
        log.info("Killing forwarding rule for {} on port: {}".format(self.target, self.local_port))
        subprocess.call(['adb', '-s', self.target, 'forward', '--remove', 'tcp:{}'.format(self.local_port)])

    def setup_port_forwarding(self):
        log.info("Setup forwarding rule for {} on port: {}".format(self.target, self.local_port))
        subprocess.call(['adb', '-s', self.target, 'forward', 'tcp:{}'.format(self.local_port), 'tcp:5984'])



