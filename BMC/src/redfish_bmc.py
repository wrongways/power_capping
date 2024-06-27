import argparse
import asyncio
import json
import logging
from pathlib import Path

import aiohttp

from BMC.src.bmc import BMC

REDFISH_ROOT = '/redfish/v1'
KNOWN_MOTHERBOARDS = {'motherboard', 'self', '1'}

logger = logging.getLogger(__name__)


class RedfishBMC(BMC):
    def __init__(self, bmc_hostname: str, bmc_username: str, bmc_password: str):
        super().__init__(bmc_hostname, bmc_username, bmc_password)
        self.token = ''
        self.session_id = None
        self._chassis = None
        self.redfish_root = f'https://{bmc_hostname}{REDFISH_ROOT}'
        self.authenticated_root = f'https://{bmc_username}:{bmc_password}@{bmc_hostname}{REDFISH_ROOT}'

    async def connect(self):
        """Establish a redfish session."""

        session_endpoint = f'{self.authenticated_root}/SessionService/Sessions/'
        credentials = {"UserName": self.bmc_username, "Password": self.bmc_password}

        async with aiohttp.ClientSession() as session:
            # headers = {'content-type': 'application/json'}
            async with session.post(session_endpoint, json=credentials, ssl=False) as r:
                json_body = await r.json()
                logger.debug(json.dumps(json_body, sort_keys=True, indent=2))
                logger.debug(await r.text())
                if not (200 <= r.status < 300):
                    raise RuntimeError(
                            f'Failed to establish redfish session: Status: {r.status} Headers:{r.raw_headers}'
                    )
                self.token = r.headers.get('X-Auth-Token')
                self.session_id = json_body.get('Id')
                logger.debug(f'Connect status code: {r.status}')

    async def disconnect(self):
        """Disconnects from a redfish session."""

        disconnect_endpoint = f'{self.redfish_root}/SessionService/Sessions/{self.session_id}'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.delete(disconnect_endpoint, headers=headers, ssl=False) as r:
                await r.text()
                if r.status != 204:  # expect "No content" status
                    print(f'Unexpected disconnect status code: {r.status}')

    @property
    async def chassis(self) -> [str]:
        """
        Lists all chassis - Finds all the members under REDFISH_ROOT/Chassis.

        Returns list of chassis names, caches the result under self.chassis.
        """

        if self._chassis is not None:
            return self._chassis

        print('Fetching /Chassis members')
        chassis_endpoint = f'{self.redfish_root}/Chassis'
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(chassis_endpoint, headers=headers, ssl=False) as r:
                if not r.ok:
                    body = await r.text()
                    msg = f'Failed to get chassis, Bailing. {r.headers}, {body}'
                    logger.error(msg)
                    raise RuntimeError(msg)

                # print(json.dumps(json_body, sort_keys=True, indent=2))
                # Chassis are held under the '@odata.id' key in the 'Members' array
                json_body = await r.json()
                paths = [member.get('@odata.id') for member in json_body.get('Members')]
                all_chassis = [str(Path(path).name) for path in paths]
                self.chassis = all_chassis
                return all_chassis

    @chassis.setter
    def chassis(self, value):
        self._chassis = value

    @property
    async def motherboard(self):
        chassis = await self.chassis
        for chassis in chassis:
            if chassis.lower() in KNOWN_MOTHERBOARDS:
                return chassis

    @property
    async def current_power(self) -> int:
        """
        Reads the current power draw.

        Returns: Power draw in Watts
        """
        motherboard = await self.motherboard
        power_endpoint = f'{self.redfish_root}/Chassis/{motherboard}/Power'
        headers = {'X-Auth-Token': self.token}
        logger.debug(f'Connecting to {power_endpoint}')
        async with aiohttp.ClientSession() as session:
            async with session.get(power_endpoint, headers=headers, ssl=False) as r:
                if not r.ok:
                    body = await r.text()
                    msg = f'Failed to get current_power: {r.headers} {body}'
                    logger.error(msg)
                    raise RuntimeError(msg)
                json_body = await r.json()
                power = json_body.get('PowerControl', [{}])[0].get('PowerConsumedWatts')
                return int(power)

    @property
    async def current_cap_level(self) -> int | None:
        print(f'Getting cap level')
        motherboard = await self.motherboard
        power_endpoint = f'{self.redfish_root}/Chassis/{motherboard}/Power'
        logger.debug(f'Connecting to {power_endpoint}')
        headers = {'X-Auth-Token': self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(power_endpoint, headers=headers, ssl=False) as r:

                if not r.ok:
                    msg = f'''current_cap_level(): Failed to get cap level:
                            Response headers: {r.headers}
                            Response body: {r.text()}
                            '''
                    logger.error(msg)
                    raise RuntimeError(msg)

                json_body = await r.json()
                if json_body is not None:
                    logger.debug(
                            f'current_cap_level Status: {r.status}\n\t{json.dumps(json_body, indent=3, sort_keys=True)}'
                    )
                    return json_body.get('PowerControl', [{}])[0].get('PowerLimit', {}).get('LimitInWatts', 0)

                logger.warning(f'current_cap_level received empty body, returning "0". HTTP Status: {r.status}')
                return 0

    async def set_cap_level(self, new_cap_level: int):
        logger.debug(f'Setting cap level to {new_cap_level}')
        motherboard = await self.motherboard
        power_endpoint = f'{self.redfish_root}/Chassis/{motherboard}/Power'
        cap_dict = {
            'PowerControl': [{'PowerLimit': {'LimitInWatts': new_cap_level}}]
        }
        logger.debug(f'Connecting to {power_endpoint}')
        logger.debug(f'Patch data: {json.dumps(cap_dict, sort_keys=True, indent=2)}')
        headers = {
            'X-Auth-Token': self.token,
            'If-Match': '*'
        }
        async with aiohttp.ClientSession() as session:
            async with session.patch(power_endpoint, headers=headers, json=cap_dict, ssl=False) as r:
                response = await r.text()
                if not r.ok:
                    raise RuntimeError(
                            f'Failed to set cap level: {r.headers} {response}'
                    )
                logger.debug(f'set_cap_level Status: {r.status}\n\t{response=}')

                return response

    async def do_set_capping(self, operation):
        """Activates or Deactivates capping on certain systems.

        @param: operation: String either "Activate" or "Deactivate"
        @return: None

        Some systems require that "LimitTrigger" be set to "Activate" to enable
        capping. On other systems this Redfish endpoint is not available; because
        of this, 404 errors are ignored.
        """

        assert operation in "Activate Deactivate"
        logger.debug('Activating capping')
        motherboard = await self.motherboard
        power_endpoint = f'{self.redfish_root}/Chassis/{motherboard}/Power/Actions/LimitTrigger'
        cap_dict = {f'PowerLimitTrigger': {operation}}
        logger.debug(f'Connecting to {power_endpoint}')
        logger.debug(f'Patch data: {json.dumps(cap_dict, sort_keys=True, indent=2)}')
        headers = {
            'X-Auth-Token': self.token,
            'If-Match': '*'
        }
        async with aiohttp.ClientSession() as session:
            async with session.patch(power_endpoint, headers=headers, json=cap_dict, ssl=False) as r:
                # This action returns no data if all OK, just wait
                response = await r.json()
                if not r.ok:

                    if r.status == 404:
                        # The endpoint is not implemented on this system
                        logger.warning("PowerLimitTrigger is not implemented on this system")
                        return None

                    # Got an error back, but it's not a 404, so raise an Error
                    raise RuntimeError(
                            f'Failed to set cap level: {r.headers} {json.dumps(response, indent=3, sort_keys=True)}'
                    )

        logger.debug(f'Capping {operation}ed')
        return None

    async def activate_capping(self):
        await self.do_set_capping('Activate')

    async def deactivate_capping(self):
        await self.do_set_capping('Deactivate')


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
        print('Connecting')
        try:
            await bmc.connect()
            print('Chassis')
            all_chassis = await bmc.chassis
            for chassis in all_chassis:
                print(' -', chassis)

            power = await bmc.current_power
            print(f'Current power draw: {power}')

            print('Getting current cap level', end=' ')
            initial_cap_level = await bmc.current_cap_level
            print(f'Initial cap level: {initial_cap_level}')

            new_cap_level = initial_cap_level + 50
            print('Set power cap to', new_cap_level)
            await bmc.set_cap_level(new_cap_level)

            print('Getting current cap level', end=' ')
            new_cap_level = await bmc.current_cap_level
            print(f'Capping level: {new_cap_level}')

            print('Reset power cap to', initial_cap_level)
            await bmc.set_cap_level(initial_cap_level)

            print('Getting current cap level', end=' ')
            new_cap_level = await bmc.current_cap_level
            print(f'Capping level: {new_cap_level}')
            assert new_cap_level == initial_cap_level

        finally:
            print('Disconnecting')
            await bmc.disconnect()

    program_args = parse_args()
    asyncio.run(main(program_args))
