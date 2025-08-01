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
Subroutines are the most basic template, consisting of a collection of quantum operations, and not fulfilling
any of the characteristics of other templates (i.e. to prepare a specific state, to be repeated or to encode features).
"""

from .arbitrary_unitary import ArbitraryUnitary
from .approx_time_evolution import ApproxTimeEvolution
from .commuting_evolution import CommutingEvolution
from .fermionic_double_excitation import FermionicDoubleExcitation
from .interferometer import Interferometer
from .fermionic_single_excitation import FermionicSingleExcitation
from .uccsd import UCCSD
from .permute import Permute
from .qft import QFT
from .qpe import QuantumPhaseEstimation
from .qmc import QuantumMonteCarlo
from .all_singles_doubles import AllSinglesDoubles
from .grover import GroverOperator
from .kupccgsd import kUpCCGSD
from .hilbert_schmidt import HilbertSchmidt, LocalHilbertSchmidt
from .flip_sign import FlipSign
from .basis_rotation import BasisRotation
from .fable import FABLE
from .select import Select
from .prepselprep import PrepSelPrep
from .reflection import Reflection
from .qubitization import Qubitization
from .qdrift import QDrift
from .controlled_sequence import ControlledSequence
from .trotter import TrotterProduct, TrotterizedQfunc, trotterize
from .aqft import AQFT
from .amplitude_amplification import AmplitudeAmplification
from .qrom import QROM
from .phase_adder import PhaseAdder
from .adder import Adder
from .multiplier import Multiplier
from .out_multiplier import OutMultiplier
from .out_adder import OutAdder
from .mod_exp import ModExp
from .out_poly import OutPoly
from .gqsp import GQSP
from .select_pauli_rot import SelectPauliRot
from .temporary_and import TemporaryAND, Elbow
from .semi_adder import SemiAdder
from .qsvt import poly_to_angles, QSVT, qsvt, transform_angles
