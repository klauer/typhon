"""
Module Docstring
"""
############
# Standard #
############
import logging

###############
# Third Party #
###############
import numpy as np
from ophyd.utils.epics_pvs import _type_map
from pydm.data_plugins.plugin import PyDMPlugin, PyDMConnection
from qtpy.QtCore import Slot, Qt

##########
# Module #
##########
from ..utils import raise_to_operator

logger = logging.getLogger(__name__)

signal_registry = dict()


def register_signal(signal):
    """
    Add a new Signal to the registry

    The Signal object is kept within ``signal_registry`` for reference by name
    in the :class:`.SignalConnection`. Signals can be added multiple times and
    overwritten but a warning will be emitted.
    """
    # Warn the user if they are adding twice
    if signal.name in signal_registry:
        logger.debug("A signal named %s is already registered!", signal.name)
        return
    signal_registry[signal.name] = signal


class SignalConnection(PyDMConnection):
    """
    Connection to monitor an Ophyd Signal

    This is meant as a generalized connection to any type of Ophyd Signal. It
    handles reporting updates to listeners as well as pushing new values that
    users request in the PyDM interface back to the underlying signal

    The signal `data_type` is used to inform PyDM on the Python type that the
    signal will expect and emit. It is expected that this type is static
    through the execution of the application

    Attributes
    ----------
    signal : ophyd.Signal
        Stored signal object
    """
    supported_types = [int, float, str, np.ndarray]

    # Keys from Signal.describe() mapped to the Qt Signal
    describe_key_to_signal = {
        'units': 'unit_signal',
        'precision': 'prec_signal',
        'lower_ctrl_limit': 'lower_ctrl_limit_signal',
        'upper_ctrl_limit': 'upper_ctrl_limit_signal',
        'enum_strs': 'enum_strings_signal',
    }

    # Keys from ophyd metadata callbacks mapped to the Qt Signal
    metadata_key_to_signal = {
        'connected': 'connection_state_signal',
        'write_access': 'write_access_signal',
        # unused entries:
        # - read_access
    }

    def __init__(self, channel, address, protocol=None, parent=None):
        # Create base connection
        super().__init__(channel, address, protocol=protocol, parent=parent)
        self.signal_type = None

        self._key_to_signal = {
            key: getattr(self, signal_attr)
            for key, signal_attr in (
                list(self.describe_key_to_signal.items()) +
                list(self.metadata_key_to_signal.items()))
        }

        # Collect our signal
        self.signal = signal_registry[address]
        # Subscribe to value updates from ophyd
        self._cid = self.signal.subscribe(self.send_new_value,
                                          event_type=self.signal.SUB_VALUE)
        # Subscribe to metadata updates from ophyd
        self._mid = self.signal.subscribe(self.send_metadata,
                                          event_type=self.signal.SUB_META)
        # Add listener
        self.add_listener(channel)

    @Slot(int)
    @Slot(float)
    @Slot(str)
    @Slot(np.ndarray)
    def put_value(self, new_val):
        """
        Pass a value from the UI to Signal

        We are not guaranteed that this signal is writeable so catch exceptions
        if they are created. We attempt to cast the received value into the
        reported type of the signal unless it is of type ``np.ndarray``
        """
        try:
            # Cast into the correct type
            if self.signal_type is not np.ndarray:
                new_val = self.signal_type(new_val)
            logger.debug("Putting value %r to %r", new_val, self.address)
            self.signal.put(new_val)
        except Exception as exc:
            logger.exception("Unable to put %r to %s", new_val, self.address)
            raise_to_operator(exc)

    def send_new_value(self, value=None, severity=None, **kwargs):
        """
        Update the UI with a new value from the Signal
        """
        # If this is the first time we are receiving a new value note the type
        # We make the assumption that signals do not change types during a
        # connection
        if not self.signal_type:
            dtype = self.signal.describe()[self.signal.name]['dtype']
            # Only way this raises a KeyError is if ophyd is confused
            self.signal_type = _type_map[dtype][0]

        try:
            if self.signal_type is not np.ndarray:
                value = self.signal_type(value)
            self.new_value_signal[self.signal_type].emit(value)
        except Exception:
            logger.exception("Unable to update %r with value %r.",
                             self.signal.name, value)

        if severity is not None:
            try:
                self.new_severity_signal.emit(severity)
            except Exception:
                logger.exception("Unable to update %r severity with value %r.",
                                 self.signal.name, severity)

    def send_metadata(self, **kwargs):
        """
        Update the UI with new Signal metadata
        """

        if self.signal.connected:
            info = self.signal.describe()[self.signal.name]
            info.update(**kwargs)
            # info now includes both metadata from describe() and metadata from
            # this specific callback.
        else:
            # We only have legitimate access to what's given in the metadata
            # callback, as the signal is not yet connected
            info = kwargs

        enum_strs = info.get('enum_strs', None)
        if enum_strs is not None:
            info['enum_strs'] = tuple(enum_strs)

        for key, signal in self._key_to_signal.items():
            try:
                value = info[key]
            except KeyError:
                ...
            else:
                if value is not None:
                    try:
                        signal.emit(value)
                    except Exception:
                        logger.debug('Failed to emit %s %s=%s',
                                     self.signal.name, key, value)

    def add_listener(self, channel):
        """
        Add a listener channel to this connection

        This attaches values input by the user to the `send_new_value` function
        in order to update the Signal object in addition to the default setup
        performed in PyDMConnection
        """
        # Perform the default connection setup
        logger.debug("Adding %r ...", channel)
        super().add_listener(channel)
        # Report as no-alarm state
        self.new_severity_signal.emit(0)
        try:
            # Gather the current value
            signal_val = self.signal.get()
            # Gather metadata
            signal_desc = self.signal.describe()[self.signal.name]
        except Exception:
            logger.exception("Failed to gather proper information "
                             "from signal %r to initialize %r",
                             self.signal.name, channel)
            return
        # Report as connected
        self.write_access_signal.emit(True)
        self.connection_state_signal.emit(True)
        # Report metadata
        for (field, signal) in (
                    ('precision', self.prec_signal),
                    ('enum_strs', self.enum_strings_signal),
                    ('units', self.unit_signal)):
            # Check if we have metadata to send for field
            val = signal_desc.get(field)
            # If so emit it to our listeners
            if val:
                if isinstance(val, list):
                    val = tuple(val)
                signal.emit(val)
        # Report new value
        self.send_new_value(signal_val)
        # If the channel is used for writing to PVs, hook it up to the
        # 'put' methods.
        if channel.value_signal is not None:
            for _typ in self.supported_types:
                try:
                    val_sig = channel.value_signal[_typ]
                    val_sig.connect(self.put_value, Qt.QueuedConnection)
                except KeyError:
                    logger.debug("%s has no value_signal for type %s",
                                 channel.address, _typ)

    def remove_listener(self, channel, destroying=False, **kwargs):
        """
        Remove a listener channel from this connection

        This removes the `send_new_value` connections from the channel in
        addition to the default disconnection performed in PyDMConnection
        """
        logger.debug("Removing %r ...", channel)
        # Disconnect put_value from outgoing channel
        if channel.value_signal is not None and not destroying:
            for _typ in self.supported_types:
                try:
                    channel.value_signal[_typ].disconnect(self.put_value)
                except (KeyError, TypeError):
                    logger.debug("Unable to disconnect value_signal from %s "
                                 "for type %s", channel.address, _typ)
        # Disconnect any other signals
        super().remove_listener(channel, destroying=destroying, **kwargs)
        logger.debug("Successfully removed %r", channel)

    def close(self):
        """Unsubscribe from the Ophyd signal"""
        self.signal.unsubscribe(self._cid)
        self.signal.unsubscribe(self._mid)


class SignalPlugin(PyDMPlugin):
    """Plugin registered with PyDM to handle SignalConnection"""
    protocol = 'sig'
    connection_class = SignalConnection

    def add_connection(self, channel):
        """Add a connection to a channel"""
        try:
            # Add a PyDMConnection for the channel
            super().add_connection(channel)
        # There is a chance that we raise an Exception on creation. If so,
        # don't add this to our list of good to go connections. The next
        # attempt we try again.
        except KeyError:
            logger.error("Unable to find signal for %r in signal registry."
                         "Use typhon.plugins.register_signal()",
                         channel)
        except Exception:
            logger.exception("Unable to create a connection to %r",
                             channel)
