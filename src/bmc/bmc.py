from abc import ABC, abstractmethod
from typing import NamedTuple


class Result(NamedTuple):
    ok: bool
    bmc_dict: {str: str}
    stdout: str
    stderr: str
    args: str


class BMC(ABC):
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        self.bmc_hostname = bmc_hostname
        self.bmc_username = bmc_username
        self.bmc_password = bmc_password

    @property
    @abstractmethod
    async def current_power(self) -> float:
        pass

    @property
    @abstractmethod
    async def current_cap_level(self) -> float | None:
        pass

    @abstractmethod
    async def set_cap_level(self, new_cap_level: float | None):
        pass

    async def deactivate_capping(self):
        pass
