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



