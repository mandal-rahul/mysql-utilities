#!/usr/bin/env python
#
# Copyright (c) 2010, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
#

"""
This file contains the MySQL Utilities Test facility for running system
tests on the MySQL Utilities.
"""

import commands
import csv
import datetime
import optparse
import os
import re
import string
import subprocess
import sys
import time
import MySQLdb
from mysql.utilities.common.server import Server
from mysql.utilities.common.tools import get_tool_path
from mysql.utilities.common.options import parse_connection
from mysql.utilities.exception import MUTException, MySQLUtilError
from test import Server_list

# Constants
NAME = "MySQL Utilities Test - mut "
VERSION = "1.0.0 alpha"
DESCRIPTION = "mut - run tests on the MySQL Utilities"
USAGE = "%prog --server=user:passwd@host:port:socket test1 test2"

# Default settings
TEST_PATH = "./test"
UTIL_PATH = "../scripts"
PRINT_WIDTH = 75
BOLD_ON = ''
BOLD_OFF = ''
if os.name == "posix":
    BOLD_ON = '\033[1m'
    BOLD_OFF = '\033[0m'
START_PORT = 3310

# See if there are any orphan servers
def _check_for_running_servers(start_port):
    """Check to see if there are any servers running from the test
    directory.
    
    start_port[in]      The starting port number for spawned servers

    This method uses ps for posix systems and netstat for Windows machines
    to determine the list of running servers.
    
    For posix, it matches on the datadir and if datadir is the path for the
    test directory, the server will be added to the list.
    
    For nt, it matches on the port in the range starting_port,
    starting_port + 10.
    
    Returns list - tuples of the form: (process_id, [datadir|port])
    """
    datadir = os.getcwd()
    processes = []
    if os.name == "posix":
        output = commands.getoutput("ps -f|grep mysqld")
        lines = output.splitlines()
        for line in lines:
            proginfo = string.split(line)
            # look for datadir
            for arg in proginfo[8:]:
                if arg.find(datadir) >= 0:
                    processes.append((proginfo[1], arg[10:]))
                    break
    elif os.name == "nt":
        f_out = open("portlist", 'w+')
        proc = subprocess.Popen("netstat -anop tcp", shell=True,
                                stdout=f_out, stderr=f_out)
        res = proc.wait()
        f_out.close()
        f_out = open("portlist", 'r')
        for line in f_out.readlines():
            proginfo = string.split(line)
            if proginfo:
                port = proginfo[1][proginfo[1].find(":")+1:]
                if proginfo[1][0] == '0' and port.isdigit():
                    # look for port
                    if int(port) >= start_port and \
                       int(port) <= start_port + 10:
                        processes.append((proginfo[4], port))
        f_out.close()
        os.unlink("portlist")
    return processes

# Shutdown any servers that are running
def _shutdown_running_servers(server_list, processes, basedir):
    """Shutdown any running servers.

    processes[in]       The list of processes to shutdown with the form:
                        (process_id, [datadir|port])
    basedir[in]         The starting path to search for mysqladmin tool

    Returns bool - True - servers shutdown attempted
                   False - no servers to shutdown
    """
    
    if len(processes) < 1:
        return False
    for process in processes:        
        datadir = os.getcwd()
        connection = {
            "user"   : "root",
            "passwd" : "root",
            "host"   : "localhost",
            "port"   : None,
            "unix_socket" : None
        }
        if os.name == "posix":
            connection["unix_socket"] = os.path.join(process[1], "mysql.sock")
        elif os.name == "nt":
            connection["port"] = process[1]

        # 1) connect to the server.
        svr = Server(connection)
        ok_to_shutdown = True
        try:
            svr.connect()
        except:  # if we cannot connect, don't try to shut it down.
            ok_to_shutdown = False
            
        # 2) if nt, verify datadirectory
        if os.name == "nt":
            res = svr.show_server_variable("datadir")
            server_datadir = res[0][1]
            ok_to_shudown = (server_datadir.find(datadir) >= 0)

        # 3) call shutdown method from mutlib Server_list class
        if ok_to_shutdown and svr:
            if os.name == "posix":
                print "  Process id: %6d, Data path: %s" % \
                       (int(process[0]), process[1])
            elif os.name == "nt":
                print "  Process id: %6d, Port: %s" % \
                       (int(process[0]), process[1])            
            try:
                server_list.stop_server(svr)
            except:
                print "    Warning: Shutdown failed!"
    return True

# Utility function
def _print_elapsed_time(start_test):
    """ Print the elapsed time to stdout (screen)
    
    start_test[in]      The starting time of the test
    """
    stop_test = time.time()
    display_time = int((stop_test - start_test) * 100)
    if display_time == 0:
        display_time = 1
    sys.stdout.write(" %6d\n" % display_time)

# Utility function
def _report_error(message, test_name, mode, start_test, error=True):
    """ Print an error message to stdout (screen)
    
    message[in]         Error message to print
    test_name[in]       The name of the current test
    mode[in]            Event mode (PASS, FAIL, WARN, etc)
    start_test[in]      The starting time of the test
    error[in]           If True, print 'ERROR' else print 'WARNING'
    """
    linelen = opt.width - (len(test_name) + 13)
    sys.stdout.write(' ' * linelen)
    sys.stdout.write("[%s%s%s]" % (BOLD_ON, mode, BOLD_OFF))
    stop_test = time.time()
    _print_elapsed_time(start_test)
    if error:   
        fishy = "ERROR"
    else:
        fishy = "WARNING"
    print "\n%s%s%s: %s\n" % (BOLD_ON, fishy, BOLD_OFF, message)
    failed_tests.append(test)    

# Helper method to manage exception handling
def _exec_and_report(procedure, default_message, test_name, action,
                    start_test_time, exception_procedure=None):
    extra_message = None
    try:
        res = procedure()
        if res:
            return True
    except MUTException, e:
        extra_message = e.errmsg
    _report_error(default_message, test_name, action, start_test_time)
    # print the error if raised from the test.
    if extra_message is not None:
        print "%s\n" % extra_message
    # if there is an exit strategy, execute it
    if exception_procedure is not None:
        exception_procedure()
    return False

# Helper method to read CSV file
def _read_disabled_tests():
    disabled_tests = []
    file = open("disabled")
    csv_reader = csv.reader(file)
    for row in csv_reader:
        if row[0] != '#':
            disabled_tests.append(row)
    file.close()
    return disabled_tests

# Begin 'main' code
parser = optparse.OptionParser(version=VERSION, description=DESCRIPTION,
                               usage=USAGE, add_help_option=False)
parser.add_option("--help", action="help")

# Add server option
parser.add_option("--server", action="append", dest="servers",
                  help="connection information for a server to be used " \
                  "in the tests in the form: user:passwd@host:port:socket " \
                  "- list option multiple times for multiple servers to use")

# Add test wildcard option
parser.add_option("--do-tests", action="store", dest="wildcard",
                  type = "string", help="execute all tests that begin " \
                         "with this string")

# Add suite list option
parser.add_option("--suite", action="append", dest="suites",
                  type = "string", help="test suite to execute - list "
                  "option multiple times for multiple suites")

# Add skip-test list option
parser.add_option("--skip-test", action="append", dest="skip_test",
                  type = "string", help="exclude a test - list "
                  "option multiple times for multiple tests")

# Add skip-test list option
parser.add_option("--skip-tests", action="store", dest="skip_tests",
                  type = "string", help="exclude tests that begin with "
                  "this string")

# Add start-test list option
parser.add_option("--start-test", action="store", dest="start_test",
                  type = "string", help="start executing tests that begin "
                  "with this string", default=None)

# Add skip-long tests option
parser.add_option("--skip-long", action="store_true", dest="skip_long",
                  default=False, help="exclude tests that require "
                  "greater resources or take a long time to run")

# Add skip-suite list option
parser.add_option("--skip-suite", action="append", dest="skip_suites",
                  type = "string", help="exclude suite - list "
                  "option multiple times for multiple suites")

# Add test directory option
parser.add_option("--testdir", action="store", dest="testdir",
                  type = "string", help="path to test directory",
                  default=TEST_PATH)

# Add starting port
parser.add_option("--start-port", action="store", dest="start_port",
                  type = "string", help="starting port for spawned servers",
                  default=START_PORT)

# Add record option
parser.add_option("--record", action="store_true", dest="record",
                  help="record output of specified test if successful")

# Add record option
parser.add_option("--sorted", action="store_true", dest="sorted",
                  default=True, help="execute tests sorted by suite.name")

# Add utility directory option
parser.add_option("--utildir", action="store", dest="utildir",
                  type = "string", help="path to utility directory",
                  default=UTIL_PATH)

# Add display width option
parser.add_option("--width", action="store", dest="width",
                  type = "int", help="display width",
                  default=PRINT_WIDTH)

# Verbose mode
parser.add_option("--verbose", "-v", action="store_true", dest="verbose",
                  help="display additional information during operation")

# Force mode
parser.add_option("-f", "--force", action="store_true", dest="force",
                  help="do not abort when a test fails")

# Debug mode
parser.add_option("--debug", "-d", action="store_true", dest="debug",
                  help="display actual results of test cases to screen "
                       "and ignore result processing - used to diagnose "
                       "test execution problems")

# Now we process the rest of the arguments.
opt, args = parser.parse_args()

# Cannot use --do-test= with listing tests.
if opt.wildcard and len(args) > 0:
    parser.error("Cannot mix --do-test= and a list of tests.")

# Cannot use --debug with listing tests.
if opt.debug and len(args) > 1:
    parser.error("Cannot mix --debug and a list of tests.")

# Must use --record with a specific test
if opt.record and len(args) != 1:
    parser.error("Must specify a single test when using record.")
    
# Append default paths if options not specified
sys.path.append(opt.testdir)
sys.path.append(opt.utildir)
    
# Process the server connections

# Print preamble
print "\nMySQL Utilities Testing - MUT\n"
print "Parameters used: "
print "  Display Width       = %d" % (opt.width)
print "  Sorted              = %s" % (opt.sorted is not None)
print "  Force               = %s" % (opt.force is not None)
print "  Test directory      = '%s'" % (opt.testdir)
print "  Utilities directory = '%s'" % (opt.utildir)
print "  Starting port       = %d" % int(opt.start_port)

# Check for suite list
if opt.suites:
    sys.stdout.write("  Include only suites = ")
    for suite in opt.suites:
        sys.stdout.write("%s " % (suite))
    print 

# Check to see if we're skipping suites
if opt.skip_suites:
    sys.stdout.write("  Exclude suites      = ")
    for suite in opt.skip_suites:
        sys.stdout.write("%s " % (suite))
    print 
    
# Is there a --do-test?
if opt.wildcard:
    print "  Test wildcard       = '%s%%'" % opt.wildcard

# Check to see if we're skipping tests
if opt.skip_test:
    sys.stdout.write("  Skipping tests      = ")
    for test in opt.skip_test:
        sys.stdout.write("%s " % (test))
    print
    
if opt.skip_tests:
    print "  Skip wildcard       = '%s%%'" % opt.skip_tests
     
if opt.start_test:
    print "  Start test sequence = '%s%%'" % opt.start_test
    start_sequence = True
else:
    start_sequence = False
     
server_list = Server_list([], opt.start_port, opt.utildir, opt.verbose)
basedir = None

# Print status of connections
print "\nServers:"
if not opt.servers:
    print "  No servers specified."
else:
    i = 0
    for server in opt.servers:
        try:
            conn_val = parse_connection(server)
        except:
            parser.error("Problem parsing server connection '%s'" % server)

        i += 1   
        # Fail if port and socket are both None
        if conn_val["port"] is None and conn_val["unix_socket"] is None:
            parser.error("You must specify either a port or a socket " \
                  "in the server string: \n       %s" % server)

        sys.stdout.write("  Connecting to %s as user %s on port %s: " % 
                         (conn_val["host"], conn_val["user"],
                          conn_val["port"]))
        sys.stdout.flush()

        if conn_val["port"] is not None:
            conn_val["port"] = int(conn_val["port"])
        else:
            conn_val["port"] = 0
            
        conn = Server(conn_val, "server%d" % i)
        try:
            conn.connect()
            server_list.add_new_server(conn)
            print "CONNECTED"
            res = conn.show_server_variable("basedir")
            basedir = res[0][1]
        except MySQLUtilError, e:
            print "%sFAILED%s" % (BOLD_ON, BOLD_OFF)
            if conn.connect_error is not None:
                print conn.connect_error
            print "ERROR:", e.errmsg
    if server_list.num_servers() == 0:
        print "ERROR: Failed to connect to any servers listed."
        exit(1)

# Check for running servers
if server_list.num_servers():
    processes = _check_for_running_servers(opt.start_port)            

# Kill any servers running from the test directory
if len(processes) > 0:
    print
    print "WARNING: There are existing servers running that may have been\n" \
          "spawned by an earlier execution. Attempting shutdown.\n"
    _shutdown_running_servers(server_list, processes, basedir)                
    
test_files = []
failed_tests = []

# Build the list of tests to execute
for root, dirs, files in os.walk(opt.testdir):
    for f in files:
        # Check --suites list. Skip if we have suites and dir is in list
        directory = root[len(opt.testdir)+1:]
        if opt.suites:
            if directory == "":
                if "main" not in opt.suites:
                    continue
            elif directory not in opt.suites:
                continue
        if directory == "":
            directory = "main"
            
        # Get file and extension
        fname, ext = os.path.splitext(f)
        
        # Check for suite.test as well as simply test
        if args and fname not in args and directory + "." + fname not in args:
            continue
        
        # See if test is to be skipped
        if opt.skip_test:
            if fname in opt.skip_test or \
               directory + "." + fname in opt.skip_test:
                continue
            
        # See if suite is to be skipped
        if opt.skip_suites:
            if directory in opt.skip_suites:
                continue
            
        # Include only tests that are .py files and ignore mut library files
        if ext == ".py" and fname != "__init__" and fname != "mutlib":
            test_ref = (directory, root, fname)
            # Do selective tests based on matches for --do-test=
            if opt.wildcard:
                if opt.wildcard == fname[0:len(opt.wildcard)]:
                    test_files.append(test_ref)
            elif opt.skip_tests:
                if opt.skip_tests != fname[0:len(opt.skip_tests)]:
                    test_files.append(test_ref)
            # Add test if no wildcard and suite (dir) is included
            else:
                test_ref = (directory, root, fname)
                test_files.append(test_ref)

# If no tests, there's nothing to do!
if len(test_files) == 0:
    print "No tests match criteria specified."
            
# Sort test cases if option turned on
if opt.sorted:
    test_files.sort()

# Check for validity of --start-test
if start_sequence:
    found = False
    for test_tuple in test_files:
        if opt.start_test == test_tuple[2][0:len(opt.start_test)]:
            found = True
    if not found:
        print "\nWARNING: --start-test=%s%% was not found. Running full " \
              "suite(s)" % opt.start_test
        start_sequence = False

# Get list of disabled tests
disable_list = _read_disabled_tests()

have_disabled = len(disable_list)

# Print header
print "\n" + "-" * opt.width
print "TEST NAME", ' ' * (opt.width - 24), "STATUS   TIME" 
print "=" * opt.width

# Run the tests selected
num_tests_run = 0
last_test = None
for test_tuple in test_files:
    
    # Skip tests for start-test sequence
    if start_sequence:
        if opt.start_test == test_tuple[2][0:len(opt.start_test)]:
            start_sequence = False
        else:
            continue
        
    # Get test parts - directory not used
    test = test_tuple[2]
    test_name = ""
    test_suite = test_tuple[1][len(opt.testdir)+1:]

    # Add path to suite
    if len(test_suite) > 0:
        sys.path.append(opt.testdir + "/" + test_suite)
        test_name = test_suite
    else:
        test_name = "main"
    test_name += "." + test
        
    # record start time
    start_test = time.time()
    
    # Create a reference to the test class
    test_class = __import__(test)
    test_case = test_class.test(server_list,
                                opt.testdir + "/" + test_suite,
                                opt.utildir, opt.verbose, opt.debug)
    
    last_test = test_case
    # Print name of the test
    sys.stdout.write(test_name)
    sys.stdout.flush()
    
    # Skip disabled tests
    if have_disabled > 0 and not opt.force:
        skipped = False
        for disabled_test in disable_list:
            if test_name == disabled_test[0]:
                _report_error("Test marked as disabled.", test_name,
                              "SKIP", start_test, False)
                skipped = True
        if skipped:
            continue

    # Check to see if we need to skip long running tests
    if opt.skip_long and test_case.is_long():
        _report_error("Test marked as long running test.", test_name,
                      "SKIP", start_test, False)
        continue
    
    # Check prerequisites for number of servers. Skip test is there are not
    # enough servers to connect.
    if not _exec_and_report(test_case.check_prerequisites,
                           "Cannot establish resources needed to run test.",
                           test_name, "SKIP", start_test, None):
        continue

    # Set the preconditions for the test
    if not _exec_and_report(test_case.setup,
                           "Cannot establish setup conditions to run test.",
                           test_name, "SKIP", start_test, test_case.cleanup):
        continue
    
    # Run the test
    run_ok = True
    results = None
    run_msg = None
    try:
        run_ok = test_case.run()
    except MUTException, e:
        run_msg = e.errmsg
        run_ok = False
        
    if run_ok:
        # Calculate number of spaces based on test name
        linelen = opt.width - (len(test_name) + 13)
        sys.stdout.write(' ' * linelen)
        
        # Record results of test
        if opt.record:
            sys.stdout.write("RECORD")
            res = test_case.record()
            # Write time here since we're done
            stop_test = time.time()
            _print_elapsed_time(start_test)
            if not res:
                sys.stdout.write("  %sWARNING%s: Test record failed." % \
                      (BOLD_ON, BOLD_OFF))

        # Display status of test
        else:
            run_ok = True
            msg = None
            try:
                results = test_case.get_result()
                if results[0]:
                    sys.stdout.write("[pass]")
                    num_tests_run += 1
            except MUTException, e:
                results = (False, ("Test results cannot be established.\n",
                                   e.errmsg + "\n"))
                msg = e.errmsg
                
            if results[0] == False:
                sys.stdout.write("[%sFAIL%s]\n" % (BOLD_ON, BOLD_OFF))
                run_ok = False
                failed_tests.append(test)
                
        if opt.verbose:
            print test_case.__doc__
    else:
        _report_error("Test execution failed.", test_name, "FAIL", start_test)
        print "%s\n" % run_msg
        run_ok = False
                            
    # Cleanup the database settings if needed
    test_cleanup_ok = True
    cleanup_msg = None
    try:
        test_cleanup_ok = test_case.cleanup()
    except MUTException, e:
        cleanup_msg = e.errmsg
        test_cleanup_ok = False

    # Display the time if not recording
    if not opt.record and run_ok:
        _print_elapsed_time(start_test)

    # Display warning about cleanup
    if not test_cleanup_ok:
        print "\n%sWARNING%s: Test cleanup failed." % (BOLD_ON, BOLD_OFF) 
        if cleanup_msg is not None:
            print "%s\n" % cleanup_msg

    if results is not None and results[1]:
        sys.stdout.write("\n%sERROR:%s " % (BOLD_ON, BOLD_OFF))    
        for str in results[1]:
            sys.stdout.write(str)
        sys.stdout.write("\n")    
    
    # Check force option
    if not run_ok and not opt.force:
        break
        
# Print postamble
print "-" * opt.width
print datetime.datetime.now().strftime("Testing completed: "
                                       "%A %d %B %Y %H:%M:%S\n")
num_fail = len(failed_tests)
num_tests = len(test_files)
if num_fail == 0:
    if num_tests > 0:
        print "All %d tests passed." % (num_tests)
else:
    print "%d of %d tests completed." % \
          (num_tests_run, num_tests)
    print "The following tests failed or were skipped:",
    for test in failed_tests:
        print test,
    print "\n"

# Shutdown connections and spawned servers
if server_list.num_spawned_servers():
    print "\nShutting down spawned servers "
    server_list.shutdown_spawned_servers()

del server_list
        
sys.stdout.write("\n")

exit(0)
