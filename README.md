# Cap testing tool

This repository hosts a tool to test the effectiveness of
capping commands.

The tool comprises four components:

BMC
: The interface to the BMC. It supports IPMI and Redfish and is
used by the runner.

Agent
: A REST server that runs on the system under test. It provides three primary
services:

* `/firestarter` - launch firestarter on the system under test
* `/rapl_power` - returns the power consumed by each socket on the server
* `/system_info` - returns the system information

Runner
: The test driver. Sets up the initial conditions and launches the
individual tests that comprise the test suite. The test conditions
and power measurements are periodically sampled by a concurrent
collector function and stored in an sqlite3 database.

Analyzer
: Lists the number of samples where the power measured by the BMC
exceeds the cap level. It also plots the power consumption and cap levels.

## Operation

There are two distinct phases

1. Run the test
2. Analyze the results

To run the tests perform the following steps (for additional details
see the README for each component).

1. Install and launch the agent on the system under test
   1. Create and activate a python virtual environment on the system under test (optional)
   2. Install the `aiohttp` package
   3. Copy a FIRESTARTER executable to the system under test. By default, the agent will look for firestarter
      under `/tmp`
   4. Launch the agent: `python agent/src/agent.py --firestarter <path/to/firestarter>`
2. Install & launch the runner on any system that has access to the system under test and its BMC
   1. Create and activate a python virtual environment (optional)
   2. Install the `aiohttp` package
   3. Configure the test in the `runner/config.py` file
   4. export the environment variable `PYTHONPATH=<capping tool root directory>`
   5. Launch the
      runner: `python runner/src/runner.py -H <bmc_hostname> -U <bmc_user> -P <bmc_pass> -t <bmc_type = redfish|ipmi>`

Once the run is complete copy the resulting database file to any system, typically a
local workstation and run the analyzer:

1. Create and activate a python virtual environment (optional)
2. Install the prerequisites: `plotly, dash, dash_bootstrap_components, pandas`
3. Launch the analysis tool: `python analyzer/src/analyzer.py -d <path/to/databasefile>`
4. Open a browser to localhost on port 8050 and select the test configuration to display.

Of course once the database has been copied, any additional analysis
and presentation becomes fairly trivial.