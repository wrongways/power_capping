# Runner

This is the main application that launches the test run.

The test configuration is stipulated in the `config.py` file.
This configuration can be customised/overridden by the command-line
options.

Before launching the test runner, the agent should be running on the
system under test. See the agent `README` file for details.

Before executing the runner, you must add the test-tool root directory
to the `PYTHONPATH` environment variable:

```export PYTHONPATH=</path/to/root/directory>```

## Synopsis

```commandline
options:
  -h, --help            show this help message and exit
  -H BMC_HOSTNAME, --bmc_hostname BMC_HOSTNAME
                        BMC hostname/ip
  -U BMC_USERNAME, --bmc_username BMC_USERNAME
                        BMC username
  -P BMC_PASSWORD, --bmc_password BMC_PASSWORD
                        BMC password
  -t {ipmi,redfish}, --bmc_type {ipmi,redfish}
                        BMC password
  -a AGENT_URL, --agent_url AGENT_URL
                        hostname and port number of the agent running on the system under test
  -d <PATH TO DB FILE>, --db_path <PATH TO DB FILE>
                        Path to the sqlite3 db on the local system holding the collected statistics. If the file does not exist, it will be created, otherwise the tables will be updated
                        with the data from this run. If not provided, the database file will be found in the current directory, with the name: <agent_name><timestamp>_capping_test.db
  -i <PATH TO IPMITOOL>, --ipmitool_path <PATH TO IPMITOOL>
                        Path to ipmitool on the local system. Only required if bmc_type="ipmi". Default: /usr/bin/ipmitool
  --min_load {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100}
                        Minimum firestarter load for test run
  --max_load {2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100}
                        Maximum firestarter load for test run
  --load_delta {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100}
                        The change in firestarter load between each test run.
  --cap_min CAP_MIN     Minimum power cap setting
  --cap_max CAP_MAX     Maximum power cap setting
  --cap_delta CAP_DELTA
                        The change in cap settings for each test run. The test runner will generate a run for each step between min and max
```

To reduce the risk of leaving sensitive information in git repositories
the bmc hostname, username, password and type must be provided on the command-line. The
remaining options can be left at their default or set in the `config.py` file.

# Operation

The runner creates a BMC instance that represents the connection
to the BMC of the system under test. It also launches a collector
instance that begins collecting system and power information
from both the BMC and the agent.

## Database file

The runner shares an sqlite3 database file with the collector.
There are five relations (tables) in the database:

bmc
: The bmc statistics: timestamped power and cap level readings

rapl
: Intel RAPL statistics: timestamped package (socket) and power

tests
: Test description, start & end times, capping levels, and load percentage

capping_commands
: Timestamped capping commands sent from runner to the BMC

system_info
: A table with a single row containing information about the system
under test including hostname, OS name, CPU and firmware details.
