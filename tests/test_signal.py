############
# Standard #
############
import random

############
# External #
############
from ophyd import Kind
from ophyd.signal import Signal
from ophyd.sim import (SynSignal, SynSignalRO, FakeEpicsSignal,
                       FakeEpicsSignalRO)
from pydm.widgets import PyDMEnumComboBox
from qtpy.QtWidgets import QWidget
###########
# Package #
###########
from typhon.signal import SignalPanel, TyphonSignalPanel
from .conftest import show_widget, RichSignal, DeadSignal


def test_panel_creation(qtbot):
    standard = FakeEpicsSignal('Tst:Pv')
    read_and_write = FakeEpicsSignal('Tst:Read', write_pv='Tst:Write')
    read_only = FakeEpicsSignalRO('Tst:Pv:RO')
    simulated = SynSignal(func=random.random, name='simul')
    simulated_ro = SynSignalRO(func=random.random, name='simul_ro')

    standard.sim_put(1)
    read_and_write.sim_put(2)
    read_only.sim_put(3)
    simulated.put(4)

    panel = SignalPanel(signals={
                    # Signal is its own write
                    'Standard': standard,
                    # Signal has separate write/read
                    'Read and Write': read_and_write,
                    # Signal is read-only
                    'Read Only': read_only,
                    # Simulated Signal
                    'Simulated': simulated,
                    'SimulatedRO': simulated_ro})
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setLayout(panel)
    assert len(panel.signals) == 5
    # Check read-only channels do not have write widgets
    panel.layout().itemAtPosition(2, 1).layout().count() == 1
    panel.layout().itemAtPosition(4, 1).layout().count() == 1
    # Check write widgets are present
    panel.layout().itemAtPosition(0, 1).layout().count() == 2
    panel.layout().itemAtPosition(1, 1).layout().count() == 2
    panel.layout().itemAtPosition(3, 1).layout().count() == 2
    return panel


def test_panel_add_enum(qtbot):
    panel = SignalPanel()
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setLayout(panel)
    # Create an enum pv
    epics_sig = FakeEpicsSignal("Tst:Enum")
    epics_sig.sim_set_enum_strs(('A', 'B'))
    epics_sig.sim_put('A')

    # Create an enum signal
    syn_sig = RichSignal(name='Syn:Enum', value=1)
    # Add our signals to the panel
    loc1 = panel.add_signal(epics_sig, "EPICS Enum PV")
    loc2 = panel.add_signal(syn_sig, "Sim Enum PV")
    # Check our signal was added a QCombobox
    # Assume it is the last item in the button layout
    but_layout = panel.layout().itemAtPosition(loc1, 1)
    assert isinstance(but_layout.itemAt(but_layout.count()-1).widget(),
                      PyDMEnumComboBox)
    # Check our signal was added a QCombobox
    # Assume it is the last item in the button layout
    but_layout = panel.layout().itemAtPosition(loc2, 1)
    assert isinstance(but_layout.itemAt(but_layout.count()-1).widget(),
                      PyDMEnumComboBox)
    return panel


def test_add_dead_signal(qtbot):
    panel = SignalPanel()
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setLayout(panel)
    dead_sig = DeadSignal(name='ded', value=0)
    panel.add_signal(dead_sig, 'Dead Signal')
    assert 'Dead Signal' in panel.signals


def test_add_pv(qtbot):
    panel = SignalPanel()
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setLayout(panel)
    panel.add_pv('Tst:A', 'Read Only')
    assert 'Read Only' in panel.signals
    assert panel.layout().itemAtPosition(0, 1).count() == 1
    panel.add_pv('Tst:A', "Write", write_pv='Tst:B')
    assert panel.layout().itemAtPosition(1, 1).count() == 2


@show_widget
def test_typhon_panel(qapp, client, qtbot):
    panel = TyphonSignalPanel()
    qtbot.addWidget(panel)
    # Setting Kind without device doesn't explode
    panel.showConfig = False
    panel.showConfig = True
    # Add a device channel
    panel.channel = 'happi://test_device'
    assert panel.channel == 'happi://test_device'
    # Reset channel and no smoke comes out
    panel.channel = 'happi://test_motor'
    qapp.establish_widget_connections(panel)
    # Check we have our device
    assert len(panel.devices) == 1
    device = panel.devices[0]
    num_hints = len(device.hints['fields'])
    num_read = len(device.read_attrs)
    # Check we got all our signals
    assert len(panel.layout().signals) == len(device.component_names)
    panel.showOmitted = False
    panel.showConfig = False
    panel.showNormal = False
    panel.showHints = True
    assert len(panel.layout().signals) == num_hints
    panel.showNormal = True
    panel.showHints = False
    assert len(panel.layout().signals) == num_read - num_hints
    panel.showHints = True
    assert len(panel.layout().signals) == num_read
    return panel


@show_widget
def test_typhon_panel_sorting(qapp, client, qtbot):
    panel = TyphonSignalPanel()
    qtbot.addWidget(panel)
    # Sort by name
    panel.sortBy = panel.SignalOrder.byName
    panel.channel = 'happi://test_motor'
    qapp.establish_widget_connections(panel)
    sorted_names = sorted(panel.devices[0].component_names)
    sig_layout = panel.layout().layout()
    assert list(panel.layout().signals.keys()) == sorted_names
    # Sort by kind
    panel.sortBy = panel.SignalOrder.byKind
    key_order = list(panel.layout().signals.keys())
    assert key_order[0] == 'readback'
    assert key_order[-1] == 'unused'
