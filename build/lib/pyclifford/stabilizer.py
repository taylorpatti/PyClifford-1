import numpy
import qutip as qt
from .utils import (
    acq_mat, ps0, z2inv, pauli_combine, pauli_transform, binary_repr,
    random_pauli, random_clifford, map_to_state, state_to_map, clifford_rotate,
    stabilizer_project, stabilizer_measure, stabilizer_expect, 
    stabilizer_entropy, mask, stabilizer_projection_trace)
from .paulialg import Pauli, PauliList, PauliPolynomial, pauli, paulis

class CliffordMap(PauliList):
    '''Represents a Clifford map. This is a subclass of PauliList.
    
    Idea: a most general Clifford transformation is specified by the operator
    mapping (how each single Pauli maps to under the trnasformation):
    X0 -> U X0 U^dagger = Pauli[g0,p0]
    Z0 -> U Z0 U^dagger = Pauli[g1,p1]
    X1 -> U X1 U^dagger = Pauli[g2,p2]
    Z1 -> U Z1 U^dagger = Pauli[g3,p3]
    ....
    The operators [g0,g1,g2,g3,...] forms a PauliList.

    Parameters:
    gs: int (2*N, 2*N) - strings of Pauli operators to be mapped to.
    ps: int (2*N) - phase indicators of Pauli operators to be mapped to.'''
    def __init__(self, *args, **kwargs):
        super(CliffordMap, self).__init__(*args, **kwargs)

    def __repr__(self):
        xz = {0:'X',1:'Z'}
        l = str(int(numpy.ceil(numpy.log10(self.N))))
        dis = '{}{:<'+l+'d}->{}'
        if self.N <= 10:
            lns = [dis.format(xz[i%2], i//2, pauli) for i, pauli in enumerate(self)]
            return 'CliffordMap(\n{})'.format('\n'.join(lns)).replace('\n','\n  ')
        else:
            lns1 = [dis.format(xz[i%2], i//2, pauli) for i, pauli in zip(range(10), self[:10])]
            lns2 = [dis.format(xz[i%2], i//2, pauli) for i, pauli in zip(range(self.L-10, self.L), self[-10:])]
            return 'CliffordMap(\n{}\n   ...\n{})'.format('\n'.join(lns1),'\n'.join(lns2)).replace('\n','\n  ')
    
    def copy(self):
        return CliffordMap(self.gs.copy(), self.ps.copy())

    def to_state(self, r=None):
        '''Interprete the Clifford map as a stabilizer state, such that the
            state is generated by the map from the zero state.'''
        gs, ps = map_to_state(self.gs, self.ps)
        return StabilizerState(gs, ps).set_r(r)

    def embed(self, small_map, mask):
        '''Embed a smaller map acting on a subsystem specified by qubit indices.'''
        mask2 = numpy.repeat(mask, 2)
        self.gs[numpy.ix_(mask2, mask2)] = small_map.gs
        self.ps[mask2] = small_map.ps
        return self

    def compose(self, other):
        '''Returns the composition of this map with the other map (this map
        will transform first in the forward transformation). This is equivalent
        to tranforming the Pauli operators in this map by the next map.'''
        gs, ps = pauli_transform(self.gs, self.ps, other.gs, other.ps)
        return CliffordMap(gs, ps)

    def inverse(self):
        '''Returns the inverse of this Clifford map, (such that it composes with
        its inverse results in identity map).'''
        gs_inv = z2inv(self.gs)
        gs_iden, ps_mis = pauli_combine(gs_inv, self.gs, self.ps)
        ps_inv = (- ps_mis - ps0(gs_inv))%4
        return CliffordMap(gs_inv, ps_inv)

class StabilizerState(PauliList):
    '''Represents a stabilizer state. This is a subclass of PauliList.
        rho = 1/2^r prod_{a=1}^{N-r} (1+ Pauli[g_a,p_a])/2

    The stabilizer state is specified by a stablizer tableau, as a binary matrix
    of the shape (2*N, 2*N).
        rows [0,r) - standby stabilizers
        rows [r,N) - active stabilizers (g_a)
        rows [N,N+r) - standby destabilizers
        rows [N+r,2*N) - active destabilizers
    The stabilizers and destablizers in the tableau forms a list of Pauli 
    operators, which can be represented as a subclass of PauliList.

    Parameters:
    gs: int (2*N, 2*N) - strings of Pauli operators in the stabilizer tableau.
    ps: int (2*N) - phase indicators (should only be 0 or 2).
    r:  int  - number of logical qubits (log2 rank of density matrix)'''
    # def __init__(self, *args, **kwargs):
    def __init__(self, gs, r=0, **kwargs):
        super(StabilizerState, self).__init__(gs, **kwargs)
        self.r = r # pure state by default
        
    def __repr__(self):
        ''' will only show active stabilizers, 
            to see the full stabilizer tableau, convert to PauliList by [:] '''
        subrepr = repr(self.stabilizers)
        if subrepr == '':
            return 'StabilizerState()'
        else:
            return 'StabilizerState(\n{})'.format(subrepr).replace('\n','\n  ')

    @property
    def stabilizers(self):
        return self[self.r:self.N]
    
    def copy(self):
        return StabilizerState(self.gs.copy(), self.ps.copy()).set_r(self.r)

    def set_r(self, r=None):
        '''set log2 rank of the density matrix.'''
        self.r = 0 if r is None else r
        return self

    def to_map(self):
        '''Interprete the stabilizer code as its encoding Clifford map.'''
        gs, ps = state_to_map(self.gs, self.ps)
        return CliffordMap(gs, ps)

    def measure(self, obs):
        '''Perform measurement on the stabilizer state.
        
        Parameters:
        obs: PauliList or StabilizerState (only active stabilizers measured)

        Returns:
        out: int (L) - array of measurement outcomes of each observable.
        log2prob: real - log2 probability of this set of outcomes.'''
        if isinstance(obs, StabilizerState):
            obs = obs.stabilizers
        self.gs, self.ps, self.r, out, log2prob = stabilizer_measure(
            self.gs, self.ps, obs.gs, obs.ps, self.r)
        return out, log2prob

    def expect(self, obs):
        '''Evaluate expectation values of observables on the statilizer state.
        
        Parameters:
        obs: observable, can be Pauli, PauliList, PauliPolynomial, StabilizerState
        z: fugacity of operator weight, it is not used when obs is StabilizerState

        Returns:
        out: output (depending on the type of obs)
            * Pauli: promote to PauliPolynomial
            * PauliPolynomial O: Tr(rho O z^|O|)
            * StabilizerState sigma: Tr(rho sigma)
            * PauliList [O_i]: [Tr(rho O_i z^|O_i|)]
        '''
        if isinstance(obs, Pauli):
            return self.expect(obs.as_polynomial()) # cast Pauli to PauliPolynomial
        elif isinstance(obs, PauliPolynomial):
            xs = self.expect(PauliList(obs.gs, obs.ps)) # cast PauliPolynomial to PauliList
            return numpy.sum(obs.cs * xs)
        elif isinstance(obs, StabilizerState):
            if self.r!=0:
                raise NotImplementedError("Will be added in the next release!")
            else:
                _, _, _, trace = stabilizer_projection_trace(numpy.array(self.gs), numpy.array(self.ps), \
                                  numpy.array(obs.gs[obs.r:obs.N,:]), numpy.array(obs.ps[obs.r:obs.N]), 0)
                return trace/2**obs.r
            
        elif isinstance(obs, PauliList):
            xs = stabilizer_expect(self.gs, self.ps, obs.gs, obs.ps, self.r)
            return xs
    def to_qutip(self):
        ID = qt.tensor([qt.qeye(2) for i in range(self.N)])
        rho = ID
        for i in range(self.r,self.N):
            rho = rho*(ID+Pauli(self.gs[i],self.ps[i]).to_qutip())/2
            # rho = rho*(ID+pauli2pauli(state.gs[i],state.ps[i]))/2
        rho = rho/(2**self.r)
        return rho
        
    def entropy(self, subsys):
        '''Entanglement entropy of the stabilizer state in a given region.'''
        if isinstance(subsys, (tuple, list)):
            subsys = numpy.array(subsys)
        if len(subsys) == 0:
            return 0
        else:
            if not isinstance(subsys[0], numpy.bool_):
                subsys = mask(subsys, self.N)
        return stabilizer_entropy(self.stabilizers.gs, subsys)

    def tokenize(self):
        return self.stabilizers.tokenize()
    
    def sample(self, L):
        '''Sample stabilizers from the stabilizer group.'''
        C = numpy.random.randint(2, size=(L,self.N-self.r))
        gs, ps = pauli_combine(C, self.gs[self.r:self.N], self.ps[self.r:self.N])
        return PauliList(gs, ps)
    def get_prob(self, readout):
        '''
        Evaluate the probability of getting a bit string readout
        '''
        if self.N != readout.shape[0]:
            raise Error("readout is incompitile with system size!")
        readout_state = identity_map(self.N).to_state()
        readout_state.ps[:self.N]=readout
        return self.expect(readout_state)

    # !!! this function has exponential complexity.
    @property
    def density_matrix(self):
        '''Expand stabilizer state as density matrix in PauliPolynomial representation.
        '''
        C = binary_repr(numpy.arange(2**(self.N-self.r)))
        gs, ps = pauli_combine(C, self.gs[self.r:self.N], self.ps[self.r:self.N])
        return PauliPolynomial(gs, ps) / 2**self.N

    def __neg__(self):
        return -self.density_matrix

    def __rmul__(self, other):
        return other * self.density_matrix

    def __truediv__(self, other):
        return self.density_matrix/other

    def __add__(self, other):
        return self.density_matrix + other

    def __radd__(self, other):
        return self.density_matrix + other

    def __sub__(self, other):
        return self.density_matrix - other

    def __matmul__(self, other):
        return self.density_matrix @ other

# ---- map constructors ----
def identity_map(N):
    '''construct identity Clifford map of N qubits.'''
    gs = numpy.eye(2*N, dtype=numpy.int_)
    return CliffordMap(gs)

def random_pauli_map(N):
    '''construct random Pauli map of N qubits.'''
    gs = random_pauli(N) # shape (2*N, 2*N), mapping matrix
    ps = 2 * numpy.random.randint(0,2,2*N) # shape (2*N), phase indicator
    return CliffordMap(gs, ps)

def random_clifford_map(N):
    '''construct random Clifford map of N qubits.
        drawn from N-qubit Clifford group uniformly.'''
    gs = random_clifford(N) # shape (2*N, 2*N), mapping matrix
    ps = 2 * numpy.random.randint(0,2,2*N) # shape (2*N), phase indicator
    return CliffordMap(gs, ps)

def clifford_rotation_map(gen):
    '''construct Clifford map from generator.'''
    gen = pauli(gen)
    gs = numpy.eye(2*gen.N, dtype=numpy.int_) # initialize
    ps = numpy.zeros(2*gen.N, dtype=numpy.int_) # initialize
    gs, ps = clifford_rotate(gen.g, gen.p, gs, ps)
    return CliffordMap(gs, ps)

# ---- state constructors ----
def stabilizer_state(*stabilizers):
    '''Construct a stabilizer state from a list of stabilizers

    Parameters:
    stabilizers: PauliList or descriptions of stabilizers.'''
    stabilizers = paulis(*stabilizers) # parsing input to PauliList
    # validity check:
    if not (acq_mat(stabilizers.gs) == 0).all():
        raise ValueError('stabilizers must all commute with each other.')
    state = maximally_mixed_state(stabilizers.N)
    state.gs, state.r = stabilizer_project(state.gs, numpy.flipud(stabilizers.gs), state.r)
    state.ps[state.r:state.N] = stabilizers.ps
    return state

def maximally_mixed_state(N):
    return identity_map(N).to_state(r=N)

def zero_state(N):
    return identity_map(N).to_state()

def one_state(N):
    return -zero_state(N)

def ghz_state(N):
    objs = [pauli({i:3,i+1:3},N) for i in range(N-1)]
    objs.append(pauli([1]*N))
    return stabilizer_state(paulis(objs))

def random_pauli_state(N, r=None):
    return random_pauli_map(N).to_state(r)

def random_clifford_state(N, r=None):
    return random_clifford_map(N).to_state(r)
