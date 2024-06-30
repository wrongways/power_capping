# Capping Tool Agent

This is the agent for the capping tool. It runs
on the system under test. It provides three REST
services:

* Return system information
* Return the current RAPL power
* Launch firestarter load generator

```
usage: CappingAgent [-h] [-P PORT] [-f FIRESTARTER] [-v] [-V]

Launches the capping tool agent

options:
  -h, --help            show this help message and exit
  -P PORT, --port PORT  Port the agent will listen on
  -f FIRESTARTER, --firestarter FIRESTARTER
                        Fully qualified path to the firestarter load generation programme
  -v, --verbose
  -V, --version         show program's version number and exit
```

The default port is 5432

The default firestarter path is `/tmp/FIRESTARTER`
