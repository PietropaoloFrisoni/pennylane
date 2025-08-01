# Copyright 2018-2021 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""
Contains the k-UpCCGSD template.
"""
# pylint: disable-msg=too-many-branches,too-many-arguments,protected-access
# pylint: disable-msg=too-many-positional-arguments
import copy
from itertools import product

import numpy as np

from pennylane import math
from pennylane.operation import Operation
from pennylane.templates.embeddings import BasisEmbedding
from pennylane.wires import Wires

from .fermionic_double_excitation import FermionicDoubleExcitation
from .fermionic_single_excitation import FermionicSingleExcitation


def generalized_singles(wires, delta_sz):
    r"""Return generalized single excitation terms

    .. math::
        \hat{T_1} = \sum_{pq} t_{p}^{q} \hat{c}^{\dagger}_{q} \hat{c}_{p}

    """
    n = len(wires)
    sz = 0.5 * (-1) ** np.arange(n)  # alpha-beta electrons
    gen_singles_wires = []
    for r, p in product(range(n), repeat=2):
        if sz[p] - sz[r] == delta_sz and p != r:
            if r < p:
                gen_singles_wires.append(wires[r : p + 1])
            else:
                gen_singles_wires.append(wires[p : r + 1][::-1])
    return gen_singles_wires


def generalized_pair_doubles(wires):
    r"""Return pair coupled-cluster double excitations

    .. math::
        \hat{T_2} = \sum_{pq} t_{p_\alpha p_\beta}^{q_\alpha, q_\beta}
               \hat{c}^{\dagger}_{q_\alpha} \hat{c}^{\dagger}_{q_\beta} \hat{c}_{p_\beta} \hat{c}_{p_\alpha}

    """
    pair_gen_doubles_wires = [
        # wires for [wires[r], wires[r+1], wires[p], wires[p+1]] terms
        [wires[r : r + 2], wires[p : p + 2]]
        for r, p in product(range(0, len(wires) - 1, 2), repeat=2)
        if p != r  # remove redundant terms
    ]
    return pair_gen_doubles_wires


class kUpCCGSD(Operation):
    r"""Implements the k-Unitary Pair Coupled-Cluster Generalized Singles and Doubles (k-UpCCGSD) ansatz.

    The k-UpCCGSD ansatz calls the :func:`~.FermionicSingleExcitation` and :func:`~.FermionicDoubleExcitation`
    templates to exponentiate the product of :math:`k` generalized singles and pair coupled-cluster doubles
    excitation operators. Here, "generalized" means that the single and double excitation terms do not
    distinguish between occupied and unoccupied orbitals. Additionally, the term "pair coupled-cluster"
    refers to the fact that the double excitations contain only those two-body excitations that move a
    pair of electrons from one spatial orbital to another. This k-UpCCGSD belongs to the family of Unitary
    Coupled Cluster (UCC) based ansätze, commonly used to solve quantum chemistry problems on quantum computers.

    The k-UpCCGSD unitary, within the first-order Trotter approximation for a given integer :math:`k`, is given by:

    .. math::

        \hat{U}(\vec{\theta}) =
        \prod_{l=1}^{k} \bigg(\prod_{p,r}\exp{\Big\{
        \theta_{r}^{p}(\hat{c}^{\dagger}_p\hat{c}_r - \text{H.c.})\Big\}}
        \ \prod_{i,j} \Big\{\exp{\theta_{j_\alpha j_\beta}^{i_\alpha i_\beta}
        (\hat{c}^{\dagger}_{i_\alpha}\hat{c}^{\dagger}_{i_\beta}
        \hat{c}_{j_\alpha}\hat{c}_{j_\beta} - \text{H.c.}) \Big\}}\bigg)

    where :math:`\hat{c}` and :math:`\hat{c}^{\dagger}` are the fermionic annihilation and creation operators.
    The indices :math:`p, q` run over the spin orbitals and :math:`i, j` run over the spatial orbitals. The
    singles and paired doubles amplitudes :math:`\theta_{r}^{p}` and
    :math:`\theta_{j_\alpha j_\beta}^{i_\alpha i_\beta}` represent the set of variational parameters.

    Args:
        weights (tensor_like): Tensor containing the parameters :math:`\theta_{pr}` and :math:`\theta_{pqrs}`
            entering the Z rotation in :func:`~.FermionicSingleExcitation` and :func:`~.FermionicDoubleExcitation`.
            These parameters are the coupled-cluster amplitudes that need to be optimized for each generalized
            single and pair double excitation terms.
        wires (Iterable): wires that the template acts on
        k (int): Number of times UpCCGSD unitary is repeated.
        delta_sz (int): Specifies the selection rule ``sz[p] - sz[r] = delta_sz``
            for the spin-projection ``sz`` of the orbitals involved in the generalized single excitations.
            ``delta_sz`` can take the values :math:`0` and :math:`\pm 1`.
        init_state (array[int]): Length ``len(wires)`` occupation-number vector representing the
            HF state. ``init_state`` is used to initialize the wires.

    .. details::
        :title: Usage Details

        #. The number of wires has to be equal to the number of
           spin-orbitals included in the active space, and should be even.

        #. The number of trainable parameters scales linearly with the number of layers as
           :math:`2 k n`, where :math:`n` is the total number of
           generalized singles and paired doubles excitation terms.

        An example of how to use this template is shown below:

        .. code-block:: python

            import pennylane as qml
            from pennylane import numpy as np

            # Build the electronic Hamiltonian
            symbols = ["H", "H"]
            coordinates = np.array([0.0, 0.0, -0.6614, 0.0, 0.0, 0.6614])
            H, wires = qml.qchem.molecular_hamiltonian(symbols, coordinates)

            # Define the Hartree-Fock state
            electrons = 2
            ref_state = qml.qchem.hf_state(electrons, wires)

            # Define the device
            dev = qml.device('default.qubit', wires=wires)

            # Define the ansatz
            @qml.qnode(dev)
            def ansatz(weights):
                qml.kUpCCGSD(weights, wires=[0, 1, 2, 3],
                                k=1, delta_sz=0, init_state=ref_state)
                return qml.expval(H)

            # Get the shape of the weights for this template
            layers = 1
            shape = qml.kUpCCGSD.shape(k=layers,
                                n_wires=wires, delta_sz=0)

            # Initialize the weight tensors
            np.random.seed(24)
            weights = np.random.random(size=shape)

            # Define the optimizer
            opt = qml.GradientDescentOptimizer(stepsize=0.4)

            # Store the values of the cost function
            energy = [ansatz(weights)]

            # Store the values of the circuit weights
            angle = [weights]
            max_iterations = 100
            conv_tol = 1e-06
            for n in range(max_iterations):
                weights, prev_energy = opt.step_and_cost(ansatz, weights)
                energy.append(ansatz(weights))
                angle.append(weights)
                conv = np.abs(energy[-1] - prev_energy)
                if n % 4 == 0:
                    print(f"Step = {n},  Energy = {energy[-1]:.8f} Ha")
                if conv <= conv_tol:
                    break

            print("\n" f"Final value of the ground-state energy = {energy[-1]:.8f} Ha")
            print("\n" f"Optimal value of the circuit parameters = {angle[-1]}")

        .. code-block:: none

            Step = 0,  Energy = -1.08949110 Ha
            Step = 4,  Energy = -1.13370605 Ha
            Step = 8,  Energy = -1.13581648 Ha
            Step = 12,  Energy = -1.13613171 Ha
            Step = 16,  Energy = -1.13618030 Ha
            Step = 20,  Energy = -1.13618779 Ha

            Final value of the ground-state energy = -1.13618779 Ha

            Optimal value of the circuit parameters = [[0.97879636 0.46093583 0.98108824
            0.45864352 0.65531446 0.44558289]]


        **Parameter shape**

        The shape of the weights argument can be computed by the static method
        :meth:`~.kUpCCGSD.shape` and used when creating randomly
        initialised weight tensors:

        .. code-block:: python

            shape = qml.kUpCCGSD.shape(n_layers=2, n_wires=4)
            weights = np.random.random(size=shape)

        >>> weights.shape
        (2, 6)

    """

    grad_method = None

    def _flatten(self):

        # Do not need to flatten s_wires or d_wires because they are derived hyperparameters
        hyperparameters = tuple(
            (key, self.hyperparameters[key]) for key in ["k", "delta_sz", "init_state"]
        )
        return self.data, (self.wires, hyperparameters)

    def __init__(self, weights, wires, k=1, delta_sz=0, init_state=None, id=None):
        if len(wires) < 4:
            raise ValueError(f"Requires at least four wires; got {len(wires)} wires.")
        if len(wires) % 2:
            raise ValueError(f"Requires even number of wires; got {len(wires)} wires.")

        if k < 1:
            raise ValueError(f"Requires k to be at least 1; got {k}.")

        if delta_sz not in [-1, 0, 1]:
            raise ValueError(f"Requires delta_sz to be one of ±1 or 0; got {delta_sz}.")

        s_wires = generalized_singles(list(wires), delta_sz)
        d_wires = generalized_pair_doubles(list(wires))

        shape = math.shape(weights)
        if shape != (k, len(s_wires) + len(d_wires)):
            raise ValueError(
                f"Weights tensor must be of shape {(k, len(s_wires) + len(d_wires))}; got {shape}."
            )

        init_state = math.toarray(init_state)
        if init_state.dtype != np.dtype("int"):
            raise ValueError(f"Elements of 'init_state' must be integers; got {init_state.dtype}")

        self._hyperparameters = {
            "init_state": tuple(init_state),
            "s_wires": s_wires,
            "d_wires": d_wires,
            "k": k,
            "delta_sz": delta_sz,
        }
        super().__init__(weights, wires=wires, id=id)

    def map_wires(self, wire_map: dict):
        new_op = copy.deepcopy(self)
        new_op._wires = Wires([wire_map.get(wire, wire) for wire in self.wires])
        new_op._hyperparameters["s_wires"] = [
            [wire_map.get(w, w) for w in wires] for wires in self._hyperparameters["s_wires"]
        ]
        new_op._hyperparameters["d_wires"] = [
            [[wire_map.get(w, w) for w in _wires] for _wires in wires]
            for wires in self._hyperparameters["d_wires"]
        ]
        return new_op

    @property
    def num_params(self):
        return 1

    @staticmethod
    def compute_decomposition(
        weights,
        wires,
        s_wires,
        d_wires,
        k,
        init_state,
        delta_sz=None,
    ):  # pylint: disable=arguments-differ, unused-argument
        r"""Representation of the operator as a product of other operators.

        .. math:: O = O_1 O_2 \dots O_n.



        .. seealso:: :meth:`~.kUpCCGSD.decomposition`.

        Args:
            weights (tensor_like): tensor containing the parameters entering the Z rotation
            wires (Any or Iterable[Any]): wires that the operator acts on
            k (int): number of times UpCCGSD unitary is repeated
            s_wires (Iterable[Any]): single excitation wires
            d_wires (Iterable[Any]): double excitation wires
            init_state (array[int]): Length ``len(wires)`` occupation-number vector representing the
                HF state.

        Returns:
            list[.Operator]: decomposition of the operator
        """
        op_list = []

        op_list.append(BasisEmbedding(init_state, wires=wires))

        for layer in range(k):
            for i, (w1, w2) in enumerate(d_wires):
                op_list.append(
                    FermionicDoubleExcitation(
                        weights[layer][len(s_wires) + i], wires1=w1, wires2=w2
                    )
                )

            for j, s_wires_ in enumerate(s_wires):
                op_list.append(FermionicSingleExcitation(weights[layer][j], wires=s_wires_))

        return op_list

    @staticmethod
    def shape(k, n_wires, delta_sz):
        r"""Returns the shape of the weight tensor required for this template.
        Args:
            k (int): Number of layers
            n_wires (int): Number of wires
            delta_sz (int): Specifies the selection rules ``sz[p] - sz[r] = delta_sz``
            for the spin-projection ``sz`` of the orbitals involved in the single excitations.
            ``delta_sz`` can take the values :math:`0` and :math:`\pm 1`.
        Returns:
            tuple[int]: shape
        """

        if n_wires < 4:
            raise ValueError(
                f"This template requires the number of wires to be greater than four; got 'n_wires' = {n_wires}"
            )

        if n_wires % 2:
            raise ValueError(
                f"This template requires an even number of wires; got 'n_wires' = {n_wires}"
            )

        s_wires = generalized_singles(range(n_wires), delta_sz)
        d_wires = generalized_pair_doubles(range(n_wires))

        return k, len(s_wires) + len(d_wires)
