#!/usr/bin/python
# -*- encoding: utf8 -*-


import sys
#import petsc4py
#from petsc4py import PETSc

#from .grid import *
from .set_L import *

#
#==================== Serial solver ============================================
#

class pvinversion():
    """ PV inversion, parallel
    """
    
    def __init__(self, qg):
        """ Setup the PV inversion solver
        """
                
        self._verbose = qg._verbose
                        
        # create the operator
        self.L = qg.da.createMat()
        #
        if self._verbose>0:
            print 'Operator L declared \n'

        # Fill in operator values
        self.L = set_L(self.L, qg)
        #
        if self._verbose>0:
            print 'Operator L filled \n'

        # global vector for PV inversion
        self._Qinv = qg.da.createGlobalVec()

        # local vectors
        self._localQ  = qg.da.createLocalVec()
        self._localPSI  = qg.da.createLocalVec()

        # create solver
        self.ksp = PETSc.KSP()
        self.ksp.create(PETSc.COMM_WORLD)
        self.ksp.setOperators(self.L)
        # use conjugate gradients
        self.ksp.setType('cg')
        #self.ksp.setType('gmres')
        # and incomplete Cholesky for preconditionning
        #self.ksp.getPC().setType('icc')
        # set tolerances
        #self.ksp.setTolerances(rtol=1e-10) # nope
        self.ksp.setFromOptions()
         

    def solve(self, Q, PSI, da):
        """ Compute the PV inversion
        """
        # copy Q into Qinv
        Q.copy(self._Qinv) 
        # fix boundaries
        self.set_qinv_bdy(da)
        # actually solves the pb
        self.ksp.solve(self._Qinv, PSI)
        if self._verbose>1:
            print 'Inversion done'


    def set_qinv_bdy(self, da):
        """ Set bdy in order to implement boundary conditions
        Set q to 0 along boundaries for inversion, may be an issue
        for time stepping
        """ 
        # 
        q = da.getVecArray(self._Qinv)
        mx, my, mz = da.getSizes()
        (xs, xe), (ys, ye), (zs, ze) = da.getRanges()        
        # bottom bdy
        if (zs==0):
            k=0
            for j in range(ys, ye):
                for i in range(xs, xe):
                    q[i, j, k] = 0.
        # upper bdy
        if (ze==mz):
            k=mz-1
            for j in range(ys, ye):
                for i in range(xs, xe):
                    q[i, j, k] = 0.   


#
#==================== Time stepper ============================================
#


class time_stepper():
    """ Time stepper, parallel with petsc4py
    4 steps explicit RungeKutta
    """
    
    def __init__(self, qg, dt, t0 = 0.):
        
        self._verbose = qg._verbose
        
        ### physical parameters
        # laplacian parameter, should move outside of here
        self.K = qg.K
        
        ### time variables
        self.dt = dt
        self._t0 = t0
        self.t = t0
        #print 't = %e d' % (self.t/86400.)
        
        ### 4 steps explicit RungeKutta parameters
        self._a = [1./6., 1./3., 1./3., 1./6.]
        self._b = [0.5, 0.5, 1.]

        ### additional global vectors
        self._Q0 = qg.da.createGlobalVec()
        self._Q1 = qg.da.createGlobalVec()
        self._dQ = qg.da.createGlobalVec()


    def go(self, qg, nt):
        """ Carry out the time stepping
        """
        _tstep=0
        #for i in xrange(nt):
        while _tstep < nt:
            # update time parameters and indexes
            self.t += self.dt
            _tstep += 1
            #
            qg.Q.copy(self._Q0) # copies Q into Q0
            qg.Q.copy(self._Q1) # copies Q into Q1
            for rk in range(4):
                self._computeRHS(qg)
                if rk < 3: qg.Q.waxpy(self._b[rk]*self.dt,self._dQ,self._Q0)
                self._Q1.axpy(self._a[rk]*self.dt,self._dQ)
            self._Q1.copy(qg.Q) # copies Q1 into Q
            # reset q at boundaries
            qg.set_q_bdy()
            if self._verbose>0:
                print 't = %f d' % (self.t/86400.)
        if self._verbose>0:
            print 'Time stepping done'


    
    def _computeRHS(self,qg):
        """ Compute the RHS of the pv evolution equation i.e: -J(psi,q)
        Jacobian 9 points (from Q-GCM):
        Arakawa and Lamb 1981:
        DOI: http://dx.doi.org/10.1175/1520-0493(1981)109<0018:APEAEC>2.0.CO;2
        """
    
        ### compute PV inversion to streamfunction
        qg.invert_pv()
        
        ### declare local vectors
        localQ  = qg.da.createLocalVec()
        localdQ  = qg.da.createLocalVec()
        localPSI  = qg.da.createLocalVec()
        
        ###
        qg.da.globalToLocal(qg.Q, localQ)
        qg.da.globalToLocal(qg.PSI, localPSI)
        q = qg.da.getVecArray(localQ)
        psi = qg.da.getVecArray(localPSI)
        dq = qg.da.getVecArray(self._dQ)
        #
        mx, my, mz = qg.da.getSizes()
        dx, dy, dz = qg.grid.dx, qg.grid.dy, qg.grid.dz
        idx, idy, idz = [1.0/dl for dl in [dx, dy, dz]]
        idx2, idy2, idz2 = [1.0/dl**2 for dl in [dx, dy, dz]]
        ### advect PV:
        # RHS= -u x dq/dx - v x dq/dy = -J(psi,q) = - (-dpsi/dy x dq/dx + dpsi/dx x dq/dy) 
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()
        for k in range(zs, ze):
            for j in range(ys, ye):
                for i in range(xs, xe):
                    if (i==0    or j==0 or
                        i==mx-1 or j==my-1):
                        dq[i, j, k] = 0.
                    else:
                        q_c   = q[ i  ,  j  ,  k ] # center
                        q_e = q[i+1 ,  j  ,  k ] # east
                        q_w = q[i-1 ,  j  ,  k ] # west
                        q_n = q[ i  , j+1 ,  k ] # north
                        q_s = q[ i  , j-1 ,  k ] # south
                        dqdx = (q_e - q_w)*0.5*idx
                        dqdy = (q_n - q_s)*0.5*idy
                        #
                        psi_c   = psi[ i  ,  j  ,  k ] # center
                        psi_e = psi[i+1 ,  j  ,  k ] # east
                        psi_w = psi[i-1 ,  j  ,  k ] # west
                        psi_n = psi[ i  , j+1 ,  k ] # north
                        psi_s = psi[ i  , j-1 ,  k ] # south
                        dpsidx = (psi_e - psi_w)*0.5*idx
                        dpsidy = (psi_n - psi_s)*0.5*idy
                        ### Jacobian
                        # classical approach, leads to noodling (see Arakawa 1966, J_pp)
                        #dq[i, j, k] = - ( -dpsidy * dqdx + dpsidx * dqdy)
                        # 
                        J_pp = (q[i+1,j,k]-q[i-1,j,k])*idx*0.5 * (psi[i,j+1,k]-psi[i,j-1,k])*idy*0.5 - (q[i,j+1,k]-q[i,j-1,k])*idy*0.5 * (psi[i+1,j,k]-psi[i-1,j,k])*idx*0.5
                        J_pc = q[i+1,j,k] * (psi[i+1,j+1,k]-psi[i+1,j-1,k])*idy*0.5 *idx*0.5 
                        -q[i-1,j,k] * (psi[i-1,j+1,k]-psi[i-1,j-1,k])*idy*0.5 *idx*0.5
                        -q[i,j+1,k] * (psi[i+1,j+1,k]-psi[i-1,j+1,k])*idx*0.5 *idy*0.5
                        +q[i,j-1,k] * (psi[i+1,j-1,k]-psi[i-1,j-1,k])*idx*0.5 *idy*0.5
                        J_cp = q[i+1,j+1,k] * (psi[i,j+1,k]-psi[i+1,j,k])*idx*0.5 *idy*0.5
                        -q[i-1,j-1,k] * (psi[i-1,j,k]-psi[i,j-1,k])*idx*0.5 *idy*0.5
                        -q[i-1,j+1,k] * (psi[i,j+1,k]-psi[i-1,j,k])*idx*0.5 *idy*0.5
                        +q[i+1,j-1,k] * (psi[i+1,j,k]-psi[i,j-1,k])*idx*0.5 *idy*0.5
                        #J_cc = (q[i+1,j+1,k]-q[i-1,j-1,k]) * (psi[i-1,j+1,k]-psi[i+1,j-1,k])*idx*0.5 *idy*0.5 *0.5 \
                        #      -(q[i-1,j+1,k]-q[i+1,j-1,k]) * (psi[i+1,j+1,k]-psi[i-1,j-1,k])*idx*0.5 *idy*0.5 *0.5
                        dq[i, j, k] = ( J_pp + J_pc + J_cp )/3.
                        ### Dissipation
                        dq[i, j, k] -= self.K*(psi[i+1,j,k]-2.*psi[i,j,k]+psi[i-1,j,k])*idx2    
        
        
    