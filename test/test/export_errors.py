#!/usr/bin/env python

import os
import mysql_test
import export_basic
from mysql.utilities.exception import MySQLUtilError, MUTException

class test(export_basic.test):
    """Export errors
    This test executes the export utility on a single server to exercise
    the error conditions.
    """

    def check_prerequisites(self):
        return export_basic.test.check_prerequisites(self)

    def setup(self):
        self.server1 = self.servers.get_server(0)
        res = self.server1.exec_query("CREATE USER 'joe'@'localhost'")
        return export_basic.test.setup(self)
    
    def run(self):
        self.server1 = self.servers.get_server(0)
        self.res_fname = self.testdir + "result.txt"
        
        from_conn = "--server=%s" % self.build_connection_string(self.server1)
        
        cmd = "mysqlexport.py %s util_test  " % from_conn
       
        comment = "Test case 1 - bad --skip values"
        cmd += " --skip=events,wiki-waki,woo-woo "
        res = self.run_test_case(1, cmd, comment)
        if not res:
            raise MUTException("%s: failed" % comment)
                    
        comment = "Test case 2 - exporting data and skipping data"
        cmd += " --skip=data --export=data"
        res = self.run_test_case(1, cmd, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        cmd_str = "mysqlexport.py %s " % from_conn
        comment = "Test case 3 - no database specified"
        res = self.run_test_case(2, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        cmd_str = "mysqlexport.py --server=rocks_rocks_rocks "
        cmd_str += "util_test "
        comment = "Test case 4 - cannot parse --server"
        res = self.run_test_case(2, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        cmd_str = "mysqlexport.py "
        cmd_str += "--server=nope:nada@localhost:3306 util_test"
        comment = "Test case 5 - error: cannot connect to server"
        res = self.run_test_case(1, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        joe_conn = "--server=joe@localhost:3306 "
        # Watchout for Windows: it doesn't use sockets!
        if os.name == "posix":
            joe_conn = "--server=joe@localhost:%s" % self.server1.port
            if self.server1.socket is not None:
                joe_conn += ":%s" % self.server1.socket

        cmd_str = "mysqlexport.py %s util_test " % joe_conn
        comment = "Test case 6 - error: not enough privileges"
        res = self.run_test_case(1, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        cmd_str = "mysqlexport.py %s notthereatall" % from_conn
        comment = "Test case 7 - database does not exist"
        res = self.run_test_case(1, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        cmd_str = "mysqlexport.py %s util_test --export=definitions" % joe_conn
        comment = "Test case 8 - error: not enough privileges"
        res = self.run_test_case(1, cmd_str, comment)
        if not res:
            raise MUTException("%s: failed" % comment)

        return True
          
    def get_result(self):
        return self.compare(__name__, self.results)
    
    def record(self):
        return self.save_result_file(__name__, self.results)
    
    def cleanup(self):
        try:
            self.server1.exec_query("DROP USER 'joe'@'localhost'")
        except:
            pass 
        return export_basic.test.cleanup(self)




