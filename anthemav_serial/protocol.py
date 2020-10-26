import logging

import time
import asyncio
import functools
import serial
from serial_asyncio import create_serial_connection

LOG = logging.getLogger(__name__)

CONF_EOL = 'command_eol'
CONF_THROTTLE_RATE = 'min_time_between_commands'

DEFAULT_TIMEOUT = 1.0

async def get_async_rs232_protocol(serial_port, serial_config, protocol_config, loop):

    # ensure only a single, ordered command is sent to RS232 at a time (non-reentrant lock)
    async def locked_access(method):
        @functools.wraps(method)
        async def wrapper(self, *method_args, **method_kwargs):
            #with (await self._lock):
                return await method(self, *method_args, **method_kwargs)
        return wrapper

    # check if connected, and abort calling provided method if no connection before timeout
    async def ensure_connected(method):
        @functools.wraps(method)
        async def wrapper(self, *method_args, **method_kwargs):
            try:
                await asyncio.wait_for(self._connected.wait(), self._timeout)
            except:
                LOG.debug(f"Timeout waiting to send data to {self._serial_port}, no connection!")
                return
            return await method(self, *method_args, **method_kwargs)
        return wrapper

    class RS232ControlProtocol(asyncio.Protocol):
        def __init__(self, serial_port, protocol_config, loop):
            super().__init__()

            self._serial_port = serial_port
            self._config = protocol_config
            self._loop = loop

            self._last_send = time.time() - 1
            self._timeout = self._config.get('timeout', DEFAULT_TIMEOUT)
            LOG.info(f"Timeout set to {self._timeout}")

            self._transport = None
            self._connected = asyncio.Event(loop=loop)
            self._q = asyncio.Queue(loop=loop)

            # ensure only a single, ordered command is sent to RS232 at a time (non-reentrant lock)
            #self._lock = asyncio.Lock()

        def connection_made(self, transport):
            self._transport = transport
            LOG.debug(f"Port {self._serial_port} opened {self._transport}")
            self._connected.set()

        def data_received(self, data):
            #            LOG.debug(f"Received from {self._serial_port}: {data}")
            asyncio.ensure_future(self._q.put(data), loop=self._loop)

        def connection_lost(self, exc):
            LOG.debug(f"Port {self._serial_port} closed")


        # throttle the number of RS232 sends per second to avoid causing timeouts
        async def _throttle_requests(self):
            min_time_between_commands = self._config[CONF_THROTTLE_RATE]
            delta_since_last_send = time.time() - self._last_send

            if delta_since_last_send < 0:
                delay = -1 * delta_since_last_send
                LOG.debug(f"Sleeping {delay} seconds until sending another RS232 request as device is powering up")
                await asyncio.sleep(delay)

            elif delta_since_last_send < min_time_between_commands:
                delay = min(max(0, min_time_between_commands - delta_since_last_send), min_time_between_commands)
                await asyncio.sleep(delay)

        @ensure_connected
        #@locked_access
        async def send(self, request: bytes, wait_for_reply=True, skip=0):
            self._throttle_requests()

            # clear all buffers of any data waiting to be read before sending the request
            self._transport.serial.reset_output_buffer()
            self._transport.serial.reset_input_buffer()
            while not self._q.empty():
                self._q.get_nowait()

            # send the request
            LOG.debug("Sending RS232 data %s", request)
            self._last_send = time.time()
            self._transport.write(request)

            # special case for power on, since the Anthem units can't accept more RS232 requests
            # for many seconds after initial powering up
            if request in [ "P1P1\n", "P2P1\n", "P1P3\n" ]:
                self._last_send = time.time() + self._config['delay_after_power_on']

            if wait_for_reply:
                return self._read_unlocked()


        @ensure_connected
        #@locked_access
        async def read(self):
            return self._read_unlocked()

        async def _read_unlocked(self):
            data = bytearray()
            eol = self._config[CONF_EOL].encode('ascii')

            # read the response
            try:
                while True:
                    data += await asyncio.wait_for(self._q.get(), self._timeout, loop=self._loop)
#                       LOG.debug("Partial receive %s", bytes(data).decode('ascii'))
                    if eol in data:
                        # only return the first line (ignore all other lines)
                        result_lines = data.split(eol)
                        if len(result_lines) > 1:
                            LOG.debug("Multiple response lines, ignore all but the first: %s", result_lines)

                        result = result_lines[0].decode('ascii')
#                       LOG.debug('Received "%s"', result)
                        return result
            except asyncio.TimeoutError:
                LOG.error("Timeout receiving response for '%s': received='%s'", request, data)
                raise

    factory = functools.partial(
        RS232ControlProtocol, serial_port, protocol_config, loop)
    LOG.debug(f"Creating RS232 connection to {serial_port}: {serial_config}")
    _, protocol = await create_serial_connection(loop, factory, serial_port, **serial_config)
    return protocol
