"""Abstract class for BMC implementations."""

from abc import ABC, abstractmethod
from enum import auto, Enum


class BMC_Type(Enum):
    IPMI = auto()
    REDFISH = auto()


class BMC(ABC):
    """Abstract base class for concrete BMC implementations."""
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        """Create new BMC instance.

        Args: hostname, username, password for the bmc to connect to. Required
            for both IPMI and Redfish implementations
        """
        self.bmc_hostname = bmc_hostname
        self.bmc_username = bmc_username
        self.bmc_password = bmc_password

    @property
    @abstractmethod
    async def current_power(self) -> int:
        """Returns the instantaneous power draw in Watts."""
        pass

    @property
    @abstractmethod
    async def current_cap_level(self) -> int | None:
        """Returns the current power cap in Watts."""
        pass

    @abstractmethod
    async def set_cap_level(self, new_cap_level: int):
        """Set the cap level.

        Args: new_cap_level: int - it's all in the name
        """
        pass

    @abstractmethod
    async def deactivate_capping(self):
        """Optional method to deactivate capping.

        For redfish this should be setting the cap level to none, but
        this is not always followed.
        """
        pass
