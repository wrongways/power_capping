import argparse
import asyncio
import json

import aiohttp

from bmc import BMC

REDFISH_ROOT = '/redfish/v1'


class RedfishBMC(BMC):
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.token = ''
        self.session_id = None
        self.redfish_root = f'https://{bmc_hostname}{REDFISH_ROOT}'

    async def connect(self):
        session_endpoint = '/SessionService/Sessions'
        credentials = {"UserName": self.bmc_username, "Password": self.bmc_password}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.redfish_root + session_endpoint, json=credentials, ssl=False) as r:
                print(f'Response status code: {r.status}')
                json_body = await r.json()
                print(f'X-Auth-Token: {json_body.get("headers", {}).get("X-Auth-Token")}')
                print(f'Headers: {json_body.get("headers", )}')
                print(json.dumps(json_body, sort_keys=True, indent=2))

                self.session_id = json_body.get('Id')

    async def disconnect(self):
        session_endpoint = f'/SessionService/Sessions/{self.session_id}'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.delete(self.redfish_root + session_endpoint, headers=headers, ssl=False) as r:
                json_body = await r.json()
                print(json.dumps(json_body, sort_keys=True, indent=2))

    @property
    async def current_power(self) -> int:
        return 0

    @property
    async def current_cap_level(self) -> int | None:
        return 0

    async def set_cap_level(self, new_cap_level: int):
        pass

    async def deactivate_capping(self):
        pass


if __name__ == '__main__':
    def parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            prog='IPMI BMC Test tool',
            description='Runs some elementary tests against a bmc',
        )
        parser.add_argument('-H', '--hostname', required=True, help='BMC hostname/ip')
        parser.add_argument('-U', '--username', required=True, help='BMC username')
        parser.add_argument('-P', '--password', required=True, help='BMC password')
        return parser.parse_args()


    async def main(args):
        bmc = RedfishBMC(args.hostname, args.username, args.password)
        await bmc.connect()
        await bmc.disconnect()

    program_args = parse_args()
    asyncio.run(main(program_args))
