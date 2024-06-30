# BMC

An abstract BMC class and two concrete implementations
for IPMI and Redfish.

The class provides the following asynchronous methods:

* `current_cap_level()`
* `set_cap_level()`
* `activate_capping()`
* `deactivate_capping()`

All the methods are `async` and thus must be `await`ed when called.

The Redfish implementation of activate/deactivate uses
the LimitTrigger endpoint. As this is not
available on many BMC implementations, errors are
ignored.

