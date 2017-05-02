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


import steps.mpi
import steps.model as smodel
import steps.utilities.geom_decompose as gd
import steps.mpi.solver as solvmod

import steps.model as smod
import steps.geom as sgeom
import steps.rng as srng

import time 
import numpy as np
import steps.utilities.meshio as meshio

from tol_funcs import *

########################################################################

NITER =	50			# The number of iterations
DT = 0.1			# Sampling time-step
INT = 0.3		# Sim endtime

DCSTA = 400*1e-12
DCSTB = DCSTA
RCST = 100000.0e6

#NA0 = 100000	# 1000000			# Initial number of A molecules
NA0 = 1000
NB0 = NA0		# Initial number of B molecules

SAMPLE = 1686

MESHFILE = 'brick_40_4_4_1686tets'
# <1% fail with a tolerance of 7.5%
tolerance = 7.5/100


# create the array of tet indices to be found at random
tetidxs = np.zeros(SAMPLE, dtype = 'int')
# further create the array of tet barycentre distance to centre
tetrads = np.zeros(SAMPLE)

########################################################################
rng = srng.create('r123', 512) 
rng.initialize(steps.mpi.rank + 1000)


mdl  = smod.Model()

A = smod.Spec('A', mdl)
B = smod.Spec('B', mdl)


volsys = smod.Volsys('vsys',mdl)


R1 = smod.Reac('R1', volsys, lhs = [A,B], rhs = [])

R1.setKcst(0)

D_a = smod.Diff('D_a', volsys, A,   0)
D_b = smod.Diff('D_b', volsys, B,   0)


mesh = meshio.loadMesh('meshes/' +MESHFILE)[0]

VOLA = mesh.getMeshVolume()/2.0
VOLB = VOLA

ntets = mesh.countTets()

acomptets = []
bcomptets = []
max = mesh.getBoundMax()
min = mesh.getBoundMax()
midz = 0.0
compatris=set()
compbtris=set()
for t in range(ntets):
    barycz = mesh.getTetBarycenter(t)[0]
    tris = mesh.getTetTriNeighb(t)
    if barycz < midz: 
        acomptets.append(t)
        compatris.add(tris[0])
        compatris.add(tris[1])
        compatris.add(tris[2])
        compatris.add(tris[3])
    else: 
        bcomptets.append(t)
        compbtris.add(tris[0])
        compbtris.add(tris[1])
        compbtris.add(tris[2])
        compbtris.add(tris[3])

dbset = compatris.intersection(compbtris)
dbtris = list(dbset)

compa = sgeom.TmComp('compa', mesh, acomptets)
compb = sgeom.TmComp('compb', mesh, bcomptets)
compa.addVolsys('vsys')
compb.addVolsys('vsys')

diffb = sgeom.DiffBoundary('diffb', mesh, dbtris)


# Now fill the array holding the tet indices to sample at random
assert(SAMPLE <= ntets)

numfilled = 0
while (numfilled < SAMPLE):
    tetidxs[numfilled] = numfilled
    numfilled +=1

# Now find the distance of the centre of the tets to the Z lower face
for i in range(SAMPLE):
	baryc = mesh.getTetBarycenter(int(tetidxs[i]))
	r = baryc[0]
	tetrads[i] = r*1.0e6

Atets = acomptets
Btets = bcomptets

rng = srng.create('r123', 512)
rng.initialize(steps.mpi)

tet_hosts = gd.binTetsByAxis(mesh, steps.mpi.nhosts)
if steps.mpi.rank ==0:
    gd.printPartitionStat(tet_hosts)

sim = solvmod.TetOpSplit(mdl, mesh, rng, False, tet_hosts)

tpnts = np.arange(0.0, INT, DT)
ntpnts = tpnts.shape[0]
if steps.mpi.rank == 0:
    resA = np.zeros((NITER, ntpnts, SAMPLE))
    resB = np.zeros((NITER, ntpnts, SAMPLE))



for i in range (0, NITER):
    #if steps.mpi.rank == 0: print "iteration: ", i , "/", NITER
    sim.reset()
    sim.setDiffBoundaryDiffusionActive('diffb', 'A', True)
    sim.setDiffBoundaryDiffusionActive('diffb', 'B', True)
    
    sim.setCompDiffD('compa', 'D_a', DCSTA)
    sim.setCompDiffD('compa', 'D_b', DCSTB)
    sim.setCompDiffD('compb', 'D_a', DCSTA)
    sim.setCompDiffD('compb', 'D_b', DCSTB)
    sim.setCompReacK('compa', 'R1', RCST)
    sim.setCompReacK('compb', 'R1', RCST)

    sim.setCompCount('compa', 'A', NA0)
    sim.setCompCount('compb', 'B', NB0)
    
    for t in range(0, ntpnts):
        sim.run(tpnts[t])
        for k in range(SAMPLE):
            count_a = sim.getTetCount(int(tetidxs[k]), 'A')
            count_b = sim.getTetCount(int(tetidxs[k]), 'B')
            if steps.mpi.rank == 0:
                resA[i,t,k] = count_a
                resB[i,t,k] = count_b

ndiff = sim.getDiffExtent()
niteration = sim.getNIteration()
nreac = sim.getReacExtent()

def getdetc(t, x):
    N = 1000		# The number to represent infinity in the exponential calculation
    L = 20e-6
    
    concA  = 0.0
    for n in range(N):
        concA+= ((1.0/(2*n +1))*np.exp((-(DCSTA/(20.0e-6))*np.power((2*n +1), 2)*np.power(np.pi, 2)*t)/(4*L))*np.sin(((2*n +1)*np.pi*x)/(2*L)))
    concA*=((4*NA0/np.pi)/(VOLA*6.022e26))*1.0e6	
    
    return concA

if steps.mpi.rank == 0:
    itermeansA = np.mean(resA, axis=0)
    itermeansB = np.mean(resB, axis=0)
    passed = False
    force_end = False

    tpnt_compare = [1, 2]
    max_err = 0.0

    for tidx in tpnt_compare:
        if force_end: break
        NBINS=10
        radmax = 0.0
        radmin = 10.0
        for r in tetrads:
            if (r > radmax): radmax = r
            if (r < radmin) : radmin = r
        
        rsec = (radmax-radmin)/NBINS
        binmins = np.zeros(NBINS+1)
        tetradsbinned = np.zeros(NBINS)
        r = radmin
        bin_vols = np.zeros(NBINS)
        
        for b in range(NBINS+1):
            binmins[b] = r
            if (b!=NBINS): tetradsbinned[b] = r +rsec/2.0
            r+=rsec
        
        bin_countsA = [None]*NBINS
        bin_countsB = [None]*NBINS
        for i in range(NBINS):
            bin_countsA[i] = []
            bin_countsB[i] = []
        filled = 0
        
        for i in range(itermeansA[tidx].size):
            irad = tetrads[i]
            
            for b in range(NBINS):
                if(irad>=binmins[b] and irad<binmins[b+1]):
                    bin_countsA[b].append(itermeansA[tidx][i])
                    bin_vols[b]+=sim.getTetVol(int(tetidxs[i]))
                    filled+=1.0
                    break
        filled = 0
        for i in range(itermeansB[tidx].size):
            irad = tetrads[i]
            
            for b in range(NBINS):
                if(irad>=binmins[b] and irad<binmins[b+1]):
                    bin_countsB[b].append(itermeansB[tidx][i])
                    filled+=1.0
                    break
        
        bin_concsA = np.zeros(NBINS)
        bin_concsB = np.zeros(NBINS)
        
        for c in range(NBINS): 
            for d in range(bin_countsA[c].__len__()):
                bin_concsA[c] += bin_countsA[c][d]
            for d in range(bin_countsB[c].__len__()):
                bin_concsB[c] += bin_countsB[c][d]        
            
            bin_concsA[c]/=(bin_vols[c])
            bin_concsA[c]*=(1.0e-3/6.022e23)*1.0e6    
            bin_concsB[c]/=(bin_vols[c])
            bin_concsB[c]*=(1.0e-3/6.022e23)*1.0e6 
        
        for i in range(NBINS):
            rad = abs(tetradsbinned[i])*1.0e-6
            
            if (tetradsbinned[i] < -5):
                # compare A
                det_conc = getdetc(tpnts[tidx], rad)
                steps_conc = bin_concsA[i]
                if tolerable(det_conc, steps_conc, tolerance):
                    passed = True
                else:
                    passed = False
                    force_end = True
                    break
                if (abs(2*(det_conc-steps_conc)/(det_conc+steps_conc)) > max_err): max_err = abs(2*(det_conc-steps_conc)/(det_conc+steps_conc))
            if (tetradsbinned[i] > 5):
                # compare B
                det_conc = getdetc(tpnts[tidx], rad)
                steps_conc = bin_concsB[i]
                if tolerable(det_conc, steps_conc, tolerance):
                    passed = True
                else:
                    passed = False
                    force_end = True
                    break
                if (abs(2*(det_conc-steps_conc)/(det_conc+steps_conc)) > max_err): max_err = abs(2*(det_conc-steps_conc)/(det_conc+steps_conc))
    print "Max error:", max_err*100, "%, passed: ", passed