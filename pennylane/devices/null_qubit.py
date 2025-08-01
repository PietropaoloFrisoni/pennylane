# Copyright 2022 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The null.qubit device is a no-op device, useful for resource estimation, and for
benchmarking PennyLane's auxiliary functionality outside direct circuit evaluations.
"""


import inspect
import json
import logging
import time
from collections import defaultdict
from dataclasses import replace
from functools import lru_cache, singledispatch
from numbers import Number

import numpy as np

from pennylane import math
from pennylane.devices.modifiers import simulator_tracking, single_tape_support
from pennylane.measurements import (
    ClassicalShadowMP,
    CountsMP,
    DensityMatrixMP,
    MeasurementProcess,
    MeasurementValue,
    ProbabilityMP,
    StateMP,
)
from pennylane.ops.op_math import Adjoint, Controlled, ControlledOp
from pennylane.tape import QuantumScriptOrBatch
from pennylane.transforms.core import TransformProgram
from pennylane.typing import Result, ResultBatch

from . import DefaultQubit, Device
from .execution_config import DefaultExecutionConfig, ExecutionConfig
from .preprocess import decompose

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

RESOURCES_FNAME_PREFIX = "__pennylane_resources_data_"


@singledispatch
def zero_measurement(
    mp: MeasurementProcess, num_device_wires, shots: int | None, batch_size: int, interface: str
):
    """Create all-zero results for various measurement processes."""
    return _zero_measurement(mp, num_device_wires, shots, batch_size, interface)


def _zero_measurement(
    mp: MeasurementProcess, num_device_wires: int, shots: int | None, batch_size, interface
):
    shape = mp.shape(shots, num_device_wires)
    if batch_size is not None:
        shape = (batch_size,) + shape
    if "jax" not in interface:
        return _cached_zero_return(shape, interface, mp.numeric_type)
    return math.zeros(shape, like=interface, dtype=mp.numeric_type)


@lru_cache(maxsize=128)
def _cached_zero_return(shape, interface, dtype):
    return math.zeros(shape, like=interface, dtype=dtype)


@zero_measurement.register
def _(mp: ClassicalShadowMP, num_device_wires, shots: int | None, batch_size, interface):
    if batch_size is not None:
        # shapes = [(batch_size,) + shape for shape in shapes]
        raise ValueError(
            "Parameter broadcasting is not supported with null.qubit and qml.classical_shadow"
        )
    shape = mp.shape(shots, num_device_wires)
    return math.zeros(shape, like=interface, dtype=np.int8)


@zero_measurement.register
def _(mp: CountsMP, num_device_wires, shots, batch_size, interface):
    outcomes = []
    if mp.obs is None and not isinstance(mp.mv, MeasurementValue):
        state = "0" * num_device_wires
        results = {state: math.asarray(shots, like=interface)}
        if mp.all_outcomes:
            outcomes = [f"{x:0{num_device_wires}b}" for x in range(1, 2**num_device_wires)]
    else:
        outcomes = sorted(mp.eigvals())  # always assign shots to the smallest
        results = {outcomes[0]: math.asarray(shots, like=interface)}
        outcomes = outcomes[1:] if mp.all_outcomes else []

    if outcomes:
        zero = math.asarray(0, like=interface)
        for val in outcomes:
            results[val] = zero
    if batch_size is not None:
        results = tuple(results for _ in range(batch_size))
    return results


zero_measurement.register(DensityMatrixMP)(_zero_measurement)


@zero_measurement.register(StateMP)
@zero_measurement.register(ProbabilityMP)
def _(
    mp: StateMP | ProbabilityMP,
    num_device_wires: int,
    shots: int | None,
    batch_size,
    interface,
):
    num_wires = len(mp.wires) or num_device_wires
    state = [1.0] + [0.0] * (2**num_wires - 1)
    if batch_size is not None:
        state = [state] * batch_size
    return math.asarray(state, like=interface)


def _interface(config: ExecutionConfig):
    return config.interface.get_like() if config.gradient_method == "backprop" else "numpy"


def _simulate_resource_use(circuit, outfile):
    num_wires = len(circuit.wires)
    gate_types = defaultdict(int)

    for op in circuit.operations:
        controls = 0
        adj = False

        while hasattr(op, "base"):
            if type(op) in (Controlled, ControlledOp):
                # Don't check this with `isinstance` to avoid unrolling ops like CNOT
                controls += len(op.control_wires)
            elif isinstance(op, Adjoint):
                adj = not adj
            else:
                break  # Certain gates have "base" but shouldn't be broken down (like CNOT)
            # NOTE: Pow, Exp, Add, etc. intentionally not handled to be compatible with Catalyst
            op = op.base

        # Barrier is not a gate and takes no resources, so we skip it
        if op.name == "Barrier":
            # (this confuses codecov, despite being tested)
            continue  # pragma: no cover

        name = op.name
        if adj:
            name = f"Adj({name})"
        if controls:
            name = f"{controls if controls > 1 else ''}C({name})"

        gate_types[name] += 1
    # NOTE: For now, this information is being printed to match the behaviour of catalyst resource tracking.
    #  In the future it may be better to return this information in a more structured way.
    json.dump(
        {
            "num_wires": num_wires,
            "num_gates": sum(gate_types.values()),
            "gate_types": gate_types,
        },
        outfile,
    )


@simulator_tracking
@single_tape_support
class NullQubit(Device):
    """Null qubit device for PennyLane. This device performs no operations involved in numerical calculations.
    Instead the time spent in execution is dominated by support (or setting up) operations, like tape creation etc.

    Args:
        wires (int, Iterable[Number, str]): Number of wires present on the device, or iterable that
            contains unique labels for the wires as numbers (i.e., ``[-1, 0, 2]``) or strings
            (``['aux_wire', 'q1', 'q2']``). Default ``None`` if not specified.
        shots (int, Sequence[int], Sequence[Union[int, Sequence[int]]]): The default number of shots
            to use in executions involving this device.
        track_resources (bool): If True, track the number of resources used by the device and save them to a JSON file.
            The filename will match ``__pennylane_resources_data_*.json`` where the wildcard (asterisk) is replaced by
            the timestamp of when execution began in nanoseconds since Unix EPOCH. This argument is experimental and
            subject to change.

    **Example:**

    .. code-block:: python

        qs = qml.tape.QuantumScript(
            [qml.Hadamard(0), qml.CNOT([0, 1])],
            [qml.expval(qml.PauliZ(0)), qml.probs()],
        )
        qscripts = [qs, qs, qs]

    >>> dev = NullQubit()
    >>> program, execution_config = dev.preprocess()
    >>> new_batch, post_processing_fn = program(qscripts)
    >>> results = dev.execute(new_batch, execution_config=execution_config)
    >>> post_processing_fn(results)
    ((array(0.), array([1., 0., 0., 0.])),
     (array(0.), array([1., 0., 0., 0.])),
     (array(0.), array([1., 0., 0., 0.])))


    This device currently supports (trivial) derivatives:

    >>> from pennylane.devices import ExecutionConfig
    >>> dev.supports_derivatives(ExecutionConfig(gradient_method="device"))
    True

    This device can be used to track resource usage:

    .. code-block:: python

        n_layers = 50
        n_wires = 100
        shape = qml.StronglyEntanglingLayers.shape(n_layers=n_layers, n_wires=n_wires)

        @qml.qnode(dev)
        def circuit(params):
            qml.StronglyEntanglingLayers(params, wires=range(n_wires))
            return [qml.expval(qml.Z(i)) for i in range(n_wires)]

        params = np.random.random(shape)

        with qml.Tracker(dev) as tracker:
            circuit(params)

    >>> tracker.history["resources"][0]
    num_wires: 100
    num_gates: 10000
    depth: 502
    shots: Shots(total=None)
    gate_types:
    {'Rot': 5000, 'CNOT': 5000}
    gate_sizes:
    {1: 5000, 2: 5000}


    .. details::
        :title: Tracking

        ``NullQubit`` tracks:

        * ``executions``: the number of unique circuits that would be required on quantum hardware
        * ``shots``: the number of shots
        * ``resources``: the :class:`~.resource.Resources` for the executed circuit.
        * ``simulations``: the number of simulations performed. One simulation can cover multiple QPU executions, such as for non-commuting measurements and batched parameters.
        * ``batches``: The number of times :meth:`~.execute` is called.
        * ``results``: The results of each call of :meth:`~.execute`
        * ``derivative_batches``: How many times :meth:`~.compute_derivatives` is called.
        * ``execute_and_derivative_batches``: How many times :meth:`~.execute_and_compute_derivatives` is called
        * ``vjp_batches``: How many times :meth:`~.compute_vjp` is called
        * ``execute_and_vjp_batches``: How many times :meth:`~.execute_and_compute_vjp` is called
        * ``jvp_batches``: How many times :meth:`~.compute_jvp` is called
        * ``execute_and_jvp_batches``: How many times :meth:`~.execute_and_compute_jvp` is called
        * ``derivatives``: How many circuits are submitted to :meth:`~.compute_derivatives` or :meth:`~.execute_and_compute_derivatives`.
        * ``vjps``: How many circuits are submitted to :meth:`~.compute_vjp` or :meth:`~.execute_and_compute_vjp`
        * ``jvps``: How many circuits are submitted to :meth:`~.compute_jvp` or :meth:`~.execute_and_compute_jvp`

    """

    @property
    def name(self):
        """The name of the device."""
        return "null.qubit"

    def __init__(self, wires=None, shots=None, track_resources=False) -> None:
        super().__init__(wires=wires, shots=shots)
        self._debugger = None
        self._track_resources = track_resources

        # this is required by Catalyst to toggle the tracker at runtime
        self.device_kwargs = {"track_resources": track_resources}

    def _simulate(self, circuit, interface):
        num_device_wires = len(self.wires) if self.wires else len(circuit.wires)
        results = []

        if self._track_resources:
            timestamp = int(time.time() * 1e9)  # nanoseconds since epoch
            resources_fname = f"{RESOURCES_FNAME_PREFIX}{timestamp}.json"
            with open(resources_fname, "x", encoding="utf-8") as f:
                _simulate_resource_use(circuit, f)

        for s in circuit.shots or [None]:
            r = tuple(
                zero_measurement(mp, num_device_wires, s, circuit.batch_size, interface)
                for mp in circuit.measurements
            )
            results.append(r[0] if len(circuit.measurements) == 1 else r)
        if circuit.shots.has_partitioned_shots:
            return tuple(results)
        return results[0]

    def _derivatives(self, circuit, interface):
        shots = circuit.shots
        num_device_wires = len(self.wires) if self.wires else len(circuit.wires)
        n = len(circuit.trainable_params)
        derivatives = tuple(
            (
                math.zeros_like(
                    zero_measurement(mp, num_device_wires, shots, circuit.batch_size, interface)
                ),
            )
            * n
            for mp in circuit.measurements
        )
        if n == 1:
            derivatives = tuple(d[0] for d in derivatives)
        return derivatives[0] if len(derivatives) == 1 else derivatives

    @staticmethod
    def _vjp(circuit, interface):
        batch_size = circuit.batch_size
        n = len(circuit.trainable_params)
        res_shape = (n,) if batch_size is None else (n, batch_size)
        return math.zeros(res_shape, like=interface)

    @staticmethod
    def _jvp(circuit, interface):
        jvps = (math.asarray(0.0, like=interface),) * len(circuit.measurements)
        return jvps[0] if len(jvps) == 1 else jvps

    @staticmethod
    def _setup_execution_config(execution_config: ExecutionConfig) -> ExecutionConfig:
        """No-op function to allow for borrowing DefaultQubit.preprocess without AttributeErrors"""
        return execution_config

    @property
    def _max_workers(self):
        """No-op property to allow for borrowing DefaultQubit.preprocess without AttributeErrors"""
        return None

    # pylint: disable=cell-var-from-loop
    def preprocess(
        self, execution_config=DefaultExecutionConfig
    ) -> tuple[TransformProgram, ExecutionConfig]:
        program = DefaultQubit.preprocess_transforms(self, execution_config)
        for t in program:
            if t.transform == decompose.transform:
                original_stopping_condition = t.kwargs["stopping_condition"]

                def new_stopping_condition(op):
                    return (not op.has_decomposition) or original_stopping_condition(op)

                t.kwargs["stopping_condition"] = new_stopping_condition

                original_shots_stopping_condition = t.kwargs.get("stopping_condition_shots", None)
                if original_shots_stopping_condition:

                    def new_shots_stopping_condition(op):
                        return (not op.has_decomposition) or original_shots_stopping_condition(op)

                    t.kwargs["stopping_condition_shots"] = new_shots_stopping_condition

        updated_values = {}
        if execution_config.gradient_method in ["best", "adjoint"]:
            updated_values["gradient_method"] = "device"
        if execution_config.use_device_gradient is None:
            updated_values["use_device_gradient"] = execution_config.gradient_method in {
                "best",
                "device",
                "adjoint",
                "backprop",
            }
        if execution_config.use_device_jacobian_product is None:
            updated_values["use_device_jacobian_product"] = (
                execution_config.gradient_method == "device"
            )
        if execution_config.grad_on_execution is None:
            updated_values["grad_on_execution"] = execution_config.gradient_method == "device"
        return program, replace(execution_config, **updated_values)

    def execute(
        self,
        circuits: QuantumScriptOrBatch,
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ) -> Result | ResultBatch:
        if logger.isEnabledFor(logging.DEBUG):  # pragma: no cover
            logger.debug(
                """Entry with args=(circuits=%s) called by=%s""",
                circuits,
                "::L".join(
                    str(i) for i in inspect.getouterframes(inspect.currentframe(), 2)[1][1:3]
                ),
            )
        return tuple(self._simulate(c, _interface(execution_config)) for c in circuits)

    def supports_derivatives(self, execution_config=None, circuit=None):
        return execution_config is None or execution_config.gradient_method in (
            "device",
            "backprop",
            "adjoint",
        )

    def supports_vjp(self, execution_config=None, circuit=None):
        return execution_config is None or execution_config.gradient_method in (
            "device",
            "backprop",
            "adjoint",
        )

    def supports_jvp(self, execution_config=None, circuit=None):
        return execution_config is None or execution_config.gradient_method in (
            "device",
            "backprop",
            "adjoint",
        )

    def compute_derivatives(
        self,
        circuits: QuantumScriptOrBatch,
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        return tuple(self._derivatives(c, _interface(execution_config)) for c in circuits)

    def execute_and_compute_derivatives(
        self,
        circuits: QuantumScriptOrBatch,
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        results = tuple(self._simulate(c, _interface(execution_config)) for c in circuits)
        jacs = tuple(self._derivatives(c, _interface(execution_config)) for c in circuits)

        return results, jacs

    def compute_jvp(
        self,
        circuits: QuantumScriptOrBatch,
        tangents: tuple[Number],
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        return tuple(self._jvp(c, _interface(execution_config)) for c in circuits)

    def execute_and_compute_jvp(
        self,
        circuits: QuantumScriptOrBatch,
        tangents: tuple[Number],
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        results = tuple(self._simulate(c, _interface(execution_config)) for c in circuits)
        jvps = tuple(self._jvp(c, _interface(execution_config)) for c in circuits)

        return results, jvps

    def compute_vjp(
        self,
        circuits: QuantumScriptOrBatch,
        cotangents: tuple[Number],
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        return tuple(self._vjp(c, _interface(execution_config)) for c in circuits)

    def execute_and_compute_vjp(
        self,
        circuits: QuantumScriptOrBatch,
        cotangents: tuple[Number],
        execution_config: ExecutionConfig = DefaultExecutionConfig,
    ):
        results = tuple(self._simulate(c, _interface(execution_config)) for c in circuits)
        vjps = tuple(self._vjp(c, _interface(execution_config)) for c in circuits)
        return results, vjps

    # TODO: Remove when PL supports pylint==3.3.6 (it is considered a useless-suppression) [sc-91362]
    # pylint: disable=unused-argument
    def eval_jaxpr(
        self, jaxpr: "jax.extend.core.Jaxpr", consts: list, *args, execution_config=None
    ) -> list:
        from pennylane.capture.primitives import (  # pylint: disable=import-outside-toplevel
            AbstractMeasurement,
        )

        def zeros_like(var):
            if isinstance(var.aval, AbstractMeasurement):
                shots = self.shots.total_shots
                s, dtype = var.aval.abstract_eval(num_device_wires=len(self.wires), shots=shots)
                return math.zeros(s, dtype=dtype, like="jax")
            return math.zeros(var.aval.shape, dtype=var.aval.dtype, like="jax")

        return [zeros_like(var) for var in jaxpr.outvars]
