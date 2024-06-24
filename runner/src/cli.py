import argparse


def parse_args():
    parser = argparse.ArgumentParser(
            prog='Capping test tool',
            description='Runs some capping tests against a given system',
    )
    parser.add_argument('-H', '--bmc_hostname', required=True, help='BMC hostname/ip')
    parser.add_argument('-U', '--bmc_username', required=True, help='BMC username')
    parser.add_argument('-P', '--bmc_password', required=True, help='BMC password')
    parser.add_argument('-t', '--bmc_type', required=True, choices=['ipmi', 'redfish'], help='BMC password')
    parser.add_argument('-a', '--agent_url', required=True,
                        help='hostname and port number of the agent running on the system under test')
    parser.add_argument('-d', '--db_path', metavar='<PATH TO DB FILE>', required=False,
                        help='''Path to the sqlite3 db on the local system holding the collected statistics. \
                        If the file does not exist, it will be created, otherwise the tables will be updated \
                        with the data from this run. If not provided, the database file will be found in the \
                        current directory, with the name: <agent_name><timestamp>.db
                        ''')
    parser.add_argument('-i', '--ipmitool_path',
                        # required='ipmi' in sys.argv,
                        metavar='<PATH TO IPMITOOL>',
                        default='/usr/bin/ipmitool',
                        help='Path to ipmitool on the local system. Only required if bmc_type="ipmi". \
                        Default: /usr/bin/ipmitool')

    return parser.parse_args()
