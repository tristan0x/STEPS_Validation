# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# STEPS - STochastic Engine for Pathway Simulation
# Copyright (C) 2007-2013 Okinawa Institute of Science and Technology, Japan.
# Copyright (C) 2003-2006 University of Antwerp, Belgium.
#
# See the file AUTHORS for details.
#
# This file is part of STEPS.
#
# STEPS is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# STEPS is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

import numpy as np
import time

import steps
import steps.mpi
import steps.mpi.solver as solvmod
import steps.utilities.geom_decompose as gd

import steps.model as smod
import steps.geom as sgeom
import steps.rng as srng
import steps.utilities.meshio as meshio

from tol_funcs import *

### NOW   A+B-> B,  0->A (see Erban and Chapman, 2009)

########################################################################
SCALE = 1.0

KCST_f = 100e6*SCALE			# The reaction constant, degradation
KCST_b = (20.0e-10*SCALE) 		# The reaction constant, production

DCST_A = 20e-12
DCST_B = 20e-12

B0 = 1   # The number of B moleucles

DT = 0.1			# Sampling time-step
INT = 50000.1 		# Sim endtime
filename = 'cube_1_1_1_73tets.inp'

# A tolerance of 7.5% will fail <1% of the time
tolerance = 7.5/100

########################################################################

mdl  = smod.Model()

A = smod.Spec('A', mdl)
B = smod.Spec('B', mdl)

volsys = smod.Volsys('vsys',mdl)

diffA = smod.Diff('diffA', volsys, A,  0)
diffB = smod.Diff('diffB', volsys, B,  0)

# Production
R1 = smod.Reac('R1', volsys, lhs = [A, B], rhs = [B], kcst = 0)
R2 = smod.Reac('R2', volsys, lhs = [], rhs = [A], kcst = 0)

geom = meshio.loadMesh('meshes/'+filename)[0]

comp1 = sgeom.TmComp('comp1', geom, range(geom.ntets))
comp1.addVolsys('vsys')

rng = srng.create('r123', 512)
rng.initialize(steps.mpi.rank + 1000)

tet_hosts = gd.binTetsByAxis(geom, steps.mpi.nhosts)
if steps.mpi.rank ==0:
    gd.printPartitionStat(tet_hosts)

sim = solvmod.TetOpSplit(mdl, geom, rng, False, tet_hosts)

tpnts = np.arange(0.0, INT, DT)
ntpnts = tpnts.shape[0]

if steps.mpi.rank ==0:
    res = np.zeros([ntpnts])
    res_std1 = np.zeros([ntpnts])
    res_std2 = np.zeros([ntpnts])

sim.setCompCount('comp1', 'A', 0)
sim.setCompCount('comp1', 'B', B0)

sim.setCompDiffD('comp1', 'diffA', DCST_A)
sim.setCompDiffD('comp1', 'diffB', DCST_B)

sim.setCompReacK('comp1', 'R1', KCST_f)
sim.setCompReacK('comp1', 'R2', KCST_b)
b_time = time.time()
for t in range(0, ntpnts):
    if steps.mpi.rank == 0 and t % 1000 == 0: print "Running time: ", tpnts[t], "/", INT
    sim.run(tpnts[t])
    count = sim.getCompCount('comp1', 'A')
    if steps.mpi.rank ==0:
        res[t] = count
    if count >= 50:
        print "over res: ", count
        break
ndiff = sim.getDiffExtent()
niteration = sim.getNIteration()
nreac = sim.getReacExtent()

def fact(x): return (1 if x==0 else x * fact(x-1))

# Do cumulative count, but not comparing them all. 
# Don't get over 50 (I hope)

if steps.mpi.rank == 0:
    passed = False

    steps_n_res = np.zeros(50)
    for r in res: steps_n_res[r]+=1
    for s in range(50): steps_n_res[s] = steps_n_res[s]/ntpnts

    max_err = 0.0

    k1 = KCST_f/6.022e23
    k2 = KCST_b*6.022e23
    v = comp1.getVol()*1.0e3 # litres

    for m in range(5, 11):
        analy = (1.0/fact(m))*np.power((k2*v*v)/(B0*k1), m)*np.exp(-((k2*v*v)/(k1*B0)))
        if tolerable(steps_n_res[m], analy, tolerance):
            passed = True
        else:
            passed = False
            break
    if (abs(2*(steps_n_res[m]-analy)/(steps_n_res[m]+analy)) > max_err): max_err = abs(2*(steps_n_res[m]-analy)/(steps_n_res[m]+analy))
    print "Max error: ", max_err*100, "%"
    print passed

