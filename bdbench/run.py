#!/bin/python
__author__ = "www.haow.ca"

# require: ansible
# Todo: refactor with ansible python lib
# Todo: cleanup ansible processes when exceptional interrupt

import os
import sys
import signal
import subprocess
from argparse import ArgumentParser
import time
import datetime

BASE_DIR = "~/monitor/"
MASTER = "ec2-54-224-95-250.compute-1.amazonaws.com"


def parse_args():
    parser = ArgumentParser(usage="run.py [options]")

    parser.add_argument("--node", dest="node", type=str, default="all",  
                        help="collect results from which host (default: all)")
    parser.add_argument("-q", "--query-num", default="1a", 
                        help="Which query to run in benchmark")
    parser.add_argument("-n", "--trial-num", default="1", 
                        help="Repeat times of executing query")
    parser.add_argument("--hosts", dest="hosts", type=str, 
                        default="./conf/hosts", 
                        help=("host list, format: 10.2.3.4 hao-spark-1"))

    opts = parser.parse_args()

    if opts.hosts is None:
        print opts.print_help()

    return opts


def execute(command):
    return subprocess.check_call(command, shell=True)


def ansible_exe(host, command):
    # os.setsid creates a new process session
    # all descendant processes will be added into this session
    # then we could kill them all by process group id
    return subprocess.Popen("ansible %s -m shell -a  \"%s\"" % (
        host, command), shell=True, preexec_fn=os.setsid)


def pre_run(opts, prefix):
    try:
        # create local monitor directory
        print "####Create local monitor directory####"
        execute("mkdir -p " + BASE_DIR + prefix)
        # create remote monitor directory
        print "####Create remote monitor directory####"
        p = ansible_exe(opts.node, "mkdir -p %s/{{inventory_hostname}}" % (
            BASE_DIR + prefix))
        p.wait()
    except subprocess.CalledProcessError as e:
        return e.returncode


def post_run(opts, prefix):
    # create a tar package to include results of this time
    print "####Build packge of remote results####"
    cmd = "tar -cf %s/%s/{{inventory_hostname}}.tar " % (BASE_DIR, prefix) \
        + "-C %s/ {{inventory_hostname}}" % (BASE_DIR + prefix)
    p = ansible_exe(opts.node, cmd)
    p.wait()

    # remote fetch
    print "####Fetch remote reulst packges####"
    cmd = "src=%s%s/{{inventory_hostname}}.tar dest=%s%s/ " % (
        BASE_DIR, prefix, BASE_DIR, prefix) + "flat=yes validate_checksum=no"
    p = subprocess.Popen("ansible %s -m fetch -a \"%s\"" % (
        opts.node, cmd), shell=True)
    p.wait()

    # local tar package extract
    print "####Extract reulst packges####"
    cmd = "cat %s/*.tar | tar -xf - -i -C %s/" % (
        BASE_DIR + prefix, BASE_DIR + prefix)
    execute(cmd)

    # copy spark.log to direcotry
    print "####Move spark.log to monitoring directory####"
    execute("mv ~/spark-1.6.1/logs/spark.log " + BASE_DIR + prefix + "/")

    # delete all tar packages
    print "####Remote reulst tar packges####"
    cmd = "rm %s/*.tar" % (BASE_DIR + prefix)
    execute(cmd)


def run(opts):
    prefix = str(time.time()).split(".")[0]
    pre_run(opts, prefix)

    monitor_proc = []

    # Todo: remove hardcode

    run_monitor = [
        # run_disk_monitor
        "iostat -x 1 > %s/{{inventory_hostname}}/disk-query-%s.log &" % ( \
            BASE_DIR + prefix, opts.query_num),
        # run_net_monitor
        ("export JAVA_HOME=/usr/lib/jvm/java-8-oracle/;"
         "./jvmtop/jvmtop.sh > %s/{{inventory_hostname}}/jvmtop-query-%s.log &") %
        (BASE_DIR + prefix, opts.query_num),
        # Todo: hardcode eth0
        # run_disk_monitor
        "sudo iftop -t > %s/{{inventory_hostname}}/iftop-query-%s.log &" % ( \
            BASE_DIR + prefix, opts.query_num),
        # run_jvm_monitor
        "sudo nethogs eth0 -t > %s/{{inventory_hostname}}/net-query-%s.log &" % ( \
            BASE_DIR + prefix, opts.query_num)
    ]

    for cmd in run_monitor:
        print "Executing: \"%s\"" % cmd
        monitor_proc.append(ansible_exe(opts.node, cmd))
        #time.sleep(1)
    monitor_proc[-1].wait()

    print "####Waiting for monitor processes...####"
    time.sleep(20)

    run_query = ("python run_query.py --spark-master %s:7077" \
                 " -q %s --num-trials %s") % (MASTER, \
                         opts.query_num, opts.trial_num)
    print "####Run Spark SQL query %s####" % opts.query_num

    query_p = subprocess.Popen(run_query, shell=True)

    query_p.wait()

    print "####Finish Spark SQL query####"
    for p in monitor_proc:
        print "Killing: \"%s\"" % run_monitor[monitor_proc.index(p)]
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)

    post_run(opts, prefix)


def main():
    opts = parse_args()
    try:
        run(opts)
    except KeyboardInterrupt:
        print "Ctrl-C interrupt, kill all monitoring processes"
        ansible_exe(opts.node, "sudo killall iostat nethogs jvmtop.sh")


if __name__ == "__main__":
    main()
