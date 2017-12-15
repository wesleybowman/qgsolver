#!/usr/bin/python
# -*- encoding: utf8 -*-


import sys
import numpy as np

#from .set_L import *
from .inout import write_nc


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
        #print('t = %e d' % (self.t/86400.))
        
        ### 4 steps explicit RungeKutta parameters
        self._a = [1./6., 1./3., 1./3., 1./6.]
        self._b = [0.5, 0.5, 1.]

        ### additional global vectors
        self._RHS0 = qg.da.createGlobalVec()
        self._RHS1 = qg.da.createGlobalVec()
        self._dRHS = qg.da.createGlobalVec()
        
        if self._verbose>0:
            print('PV time stepper is set up')


    def go(self, qg, nt,rhosb=False):
        """ Carry out the time stepping
        """
        if self._verbose>0:
            print('<--- Start time stepping ')
        _tstep=0

        if rhosb:
            # copy upper and lower density into Q
            self.copy_topdown_rho_to_q(qg)
        #for i in xrange(nt):
        while _tstep < nt:
            # update time parameters and indexes
            self.t += self.dt
            _tstep += 1
            #
            qg.Q.copy(self._RHS0) # copies Q into RHS0
            qg.Q.copy(self._RHS1) # copies Q into RHS1
            for rk in range(4):
                if rhosb:
                    self.update_topdown_rho(qg)
                qg.pvinv.solve(qg)
                #
                if qg.grid._flag_hgrid_uniform and qg.grid._flag_vgrid_uniform:
                    self._computeRHS(qg)
                else:
                    self._computeRHS_curv(qg)
                #
                if rk < 3: qg.Q.waxpy(self._b[rk]*self.dt, self._dRHS, self._RHS0)
                self._RHS1.axpy(self._a[rk]*self.dt, self._dRHS)
            self._RHS1.copy(qg.Q) # copies RHS1 into Q
            # reset q at boundaries
            self.set_rhs_bdy(qg)
            if self._verbose>0:
                print('t = %f d' % (self.t/86400.))
        # need to invert PV one final time in order to get right PSI
        qg.comm.barrier()
        if rhosb:
            self.update_topdown_rho(qg)
        qg.invert_pv()
        # reset q
        self.reset_topdown_q(qg)
        if self._verbose>0:
            print('Time stepping done --->')

    
    def _computeRHS(self,qg):
        """ Compute the RHS of the pv evolution equation i.e: J(psi,q)
        Jacobian 9 points (from Q-GCM):
        Arakawa and Lamb 1981:
        DOI: http://dx.doi.org/10.1175/1520-0493(1981)109<0018:APEAEC>2.0.CO;2
        """
    
        ### compute PV inversion to streamfunction
        #qg.invert_pv()
        
        ### declare local vectors
        local_RHS  = qg.da.createLocalVec()
        #local_dRHS  = qg.da.createLocalVec()
        local_PSI  = qg.da.createLocalVec()

        ###
        qg.da.globalToLocal(qg.Q, local_RHS)
        qg.da.globalToLocal(qg.PSI, local_PSI)
        #qg.da.globalToLocal(self._dRHS, local_dRHS)
        #
        q = qg.da.getVecArray(local_RHS)
        psi = qg.da.getVecArray(local_PSI)
        dq = qg.da.getVecArray(self._dRHS)
        #dq = qg.da.getVecArray(local_dRHS)
        #
        mx, my, mz = qg.da.getSizes()
        dx, dy, dz = qg.grid.dx, qg.grid.dy, qg.grid.dz
        idx, idy, idz = [1.0/dl for dl in [dx, dy, dz]]
        idx2, idy2, idz2 = [1.0/dl**2 for dl in [dx, dy, dz]]
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()
        #
        ### advect PV:
        # RHS= -u x dq/dx - v x dq/dy = -J(psi,q) = - (-dpsi/dy x dq/dx + dpsi/dx x dq/dy)
        #
        for k in range(zs, ze):
            for j in range(ys, ye):
                for i in range(xs, xe):
                    if (i==0    or j==0 or
                        i==mx-1 or j==my-1):
                        # lateral boundaries
                        dq[i, j, k] = 0.
                    else:
                        ### Jacobian
                        #
                        # naive approach leads to noodling (see Arakawa 1966, J_pp)
                        # dq[i, j, k] = - ( -dpsidy * dqdx + dpsidx * dqdy)
                        # 
                        # Arakawa Jacobian
                        #
                        J_pp =   ( q[i+1,j,k] - q[i-1,j,k] ) * ( psi[i,j+1,k] - psi[i,j-1,k] ) \
                               - ( q[i,j+1,k] - q[i,j-1,k] ) * ( psi[i+1,j,k] - psi[i-1,j,k] )
                        J_pp *= idx*idy*0.25
                        #
                        J_pc =   q[i+1,j,k] * (psi[i+1,j+1,k]-psi[i+1,j-1,k]) \
                               - q[i-1,j,k] * (psi[i-1,j+1,k]-psi[i-1,j-1,k]) \
                               - q[i,j+1,k] * (psi[i+1,j+1,k]-psi[i-1,j+1,k]) \
                               + q[i,j-1,k] * (psi[i+1,j-1,k]-psi[i-1,j-1,k])
                        J_pc *= idx*idy*0.25
                        #
                        J_cp =   q[i+1,j+1,k] * (psi[i,j+1,k]-psi[i+1,j,k]) \
                               - q[i-1,j-1,k] * (psi[i-1,j,k]-psi[i,j-1,k]) \
                               - q[i-1,j+1,k] * (psi[i,j+1,k]-psi[i-1,j,k]) \
                               + q[i+1,j-1,k] * (psi[i+1,j,k]-psi[i,j-1,k])
                        J_cp *= idx*idy*0.25
                        #
                        dq[i, j, k] = ( J_pp + J_pc + J_cp )/3.
                        #
                        ### Dissipation
                        dq[i, j, k] +=   self.K*(q[i+1,j,k]-2.*q[i,j,k]+q[i-1,j,k])*idx2 \
                                       + self.K*(q[i,j+1,k]-2.*q[i,j,k]+q[i,j-1,k])*idy2  



   
    def _computeRHS_curv(self,qg):
        """ Compute the RHS of the pv evolution equation i.e: J(psi,q)
        Jacobian 9 points (from Q-GCM):
        Arakawa and Lamb 1981:
        DOI: http://dx.doi.org/10.1175/1520-0493(1981)109<0018:APEAEC>2.0.CO;2
        """
    
        ### compute PV inversion to streamfunction
        #qg.invert_pv()
        
        ### declare local vectors
        local_Q  = qg.da.createLocalVec()
        #local_dRHS  = qg.da.createLocalVec()
        local_PSI  = qg.da.createLocalVec()
        
        ###
        qg.da.globalToLocal(qg.Q, local_Q)
        qg.da.globalToLocal(qg.PSI, local_PSI)
        #qg.da.globalToLocal(self._dRHS, local_dRHS)
        #
        q = qg.da.getVecArray(local_Q)
        psi = qg.da.getVecArray(local_PSI)
        dq = qg.da.getVecArray(self._dRHS)
        #dq = qg.da.getVecArray(local_dRHS)
        #
        mx, my, mz = qg.da.getSizes()
        #
        #D = qg.da.getVecArray(qg.grid.D)
        local_D  = qg.da.createLocalVec()
        qg.da.globalToLocal(qg.grid.D, local_D)
        D = qg.da.getVecArray(local_D)
        #kmask = qg.grid._k_mask
        kdxu = qg.grid._k_dxu
        kdyu = qg.grid._k_dyu
        kdxv = qg.grid._k_dxv
        kdyv = qg.grid._k_dyv
        kdxt = qg.grid._k_dxt
        kdyt = qg.grid._k_dyt
        kf = qg.grid._k_f
        #
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()
        #
        # advect PV:
        # RHS= -u x dq/dx - v x dq/dy = -J(psi,q) = - (-dpsi/dy x dq/dx + dpsi/dx x dq/dy)
        # 
        for k in range(zs, ze):
            for j in range(ys, ye):
                for i in range(xs, xe):
                    if (i==0    or j==0 or
                        i==mx-1 or j==my-1):
                        # lateral boundaries
                        dq[i, j, k] = 0.
                    else:
                        ### Jacobian
                        #
                        # naive approach leads to noodling (see Arakawa 1966, J_pp)
                        # dq[i, j, k] = - ( -dpsidy * dqdx + dpsidx * dqdy)
                        # 
                        # Arakawa Jacobian
                        #
                        J_pp =   ( q[i+1,j,k] - q[i-1,j,k] ) * ( psi[i,j+1,k] - psi[i,j-1,k] ) \
                               - ( q[i,j+1,k] - q[i,j-1,k] ) * ( psi[i+1,j,k] - psi[i-1,j,k] )
                        J_pp *= 0.25
                        #
                        J_pc =   q[i+1,j,k] * (psi[i+1,j+1,k]-psi[i+1,j-1,k]) \
                               - q[i-1,j,k] * (psi[i-1,j+1,k]-psi[i-1,j-1,k]) \
                               - q[i,j+1,k] * (psi[i+1,j+1,k]-psi[i-1,j+1,k]) \
                               + q[i,j-1,k] * (psi[i+1,j-1,k]-psi[i-1,j-1,k])
                        J_pc *= 0.25
                        #
                        J_cp =   q[i+1,j+1,k] * (psi[i,j+1,k]-psi[i+1,j,k]) \
                               - q[i-1,j-1,k] * (psi[i-1,j,k]-psi[i,j-1,k]) \
                               - q[i-1,j+1,k] * (psi[i,j+1,k]-psi[i-1,j,k]) \
                               + q[i+1,j-1,k] * (psi[i+1,j,k]-psi[i,j-1,k])
                        J_cp *= 0.25
                        #
                        dq[i, j, k] = ( J_pp + J_pc + J_cp )/3. /D[i,j,kdxt]/D[i,j,kdyt]
                        #
                        ### Add advection of planetary vorticity, shouldn't f-f0 be part of q though !!!
                        Jp_pp =   ( D[i+1,j,kf] - D[i-1,j,kf] ) * ( psi[i,j+1,k] - psi[i,j-1,k] ) \
                               - ( D[i,j+1,kf] - D[i,j-1,kf] ) * ( psi[i+1,j,k] - psi[i-1,j,k] )
                        Jp_pp *= 0.25
                        #
                        Jp_pc =  D[i+1,j,kf] * (psi[i+1,j+1,k]-psi[i+1,j-1,k]) \
                               - D[i-1,j,kf] * (psi[i-1,j+1,k]-psi[i-1,j-1,k]) \
                               - D[i,j+1,kf] * (psi[i+1,j+1,k]-psi[i-1,j+1,k]) \
                               + D[i,j-1,kf] * (psi[i+1,j-1,k]-psi[i-1,j-1,k])
                        Jp_pc *= 0.25
                        #
                        Jp_cp =  D[i+1,j+1,kf] * (psi[i,j+1,k]-psi[i+1,j,k]) \
                               - D[i-1,j-1,kf] * (psi[i-1,j,k]-psi[i,j-1,k]) \
                               - D[i-1,j+1,kf] * (psi[i,j+1,k]-psi[i-1,j,k]) \
                               + D[i+1,j-1,kf] * (psi[i+1,j,k]-psi[i,j-1,k])
                        Jp_cp *= 0.25
                        #
                        dq[i, j, k] += ( Jp_pp + Jp_pc + Jp_cp )/3. /D[i,j,kdxt]/D[i,j,kdyt]
                        ### Dissipation
                        #dq[i, j, k] +=   self.K*(q[i+1,j,k]-2.*q[i,j,k]+q[i-1,j,k])/D[i,j,kdxt]/D[i,j,kdxt] \
                        #               + self.K*(q[i,j+1,k]-2.*q[i,j,k]+q[i,j-1,k])/D[i,j,kdyt]/D[i,j,kdyt]
                        dq[i, j, k] += self.K/D[i,j,kdxt]/D[i,j,kdyt] * ( \
                                                q[i+1,j,k] * D[i,j,kdyu]/D[i,j,kdxu] \
                                               -q[i-1,j,k] * D[i-1,j,kdyu]/D[i-1,j,kdxu] \
                                               +q[i,j+1,k] * D[i,j,kdxv]/D[i,j,kdyv] \
                                               -q[i,j-1,k] * D[i,j-1,kdxv]/D[i,j-1,kdyv] \
                                                ) 
                            
    def set_rhs_bdy(self, qg):
        """ Reset rhs at boundaries such that drhs/dn=0 """
        #
        rhs = qg.da.getVecArray(qg.Q)

        #
        mx, my, mz = qg.da.getSizes()
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()

        # south bdy
        if (ys == 0):
            j = 0
            for k in range(zs, ze):
                for i in range(xs, xe):
                    rhs[i, j, k] = rhs[i, j + 1, k]
        # north bdy
        if (ye == my):
            j = my - 1
            for k in range(zs, ze):
                for i in range(xs, xe):
                    rhs[i, j, k] = rhs[i, j - 1, k]
        # west bdy
        if (xs == 0):
            i = 0
            for k in range(zs, ze):
                for j in range(ys, ye):
                    rhs[i, j, k] = rhs[i + 1, j, k]
        # east bdy
        if (xe == mx):
            i = mx - 1
            for k in range(zs, ze):
                for j in range(ys, ye):
                    rhs[i, j, k] = rhs[i - 1, j, k]
        return


    def update_topdown_rho(self,qg):
        """ update top and down rho from time stepped Q for boundary conditions
        """
        mx, my, mz = qg.da.getSizes()
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()

        kdown = qg.grid.kdown
        kup = qg.grid.kup
        
        q = qg.da.getVecArray(qg.Q)
        rho = qg.da.getVecArray(qg.RHO)
           
        for j in range(ys, ye):
            for i in range(xs, xe):           
                rho[i, j, kdown] = q[i, j, kdown]
                rho[i, j, kdown+1] = q[i, j, kdown]
                rho[i, j, kup] = q[i, j, kup]
                rho[i, j, kup-1] = q[i, j, kup]
                
        return

    def copy_topdown_rho_to_q(self, qg, flag_PSI=True):
        """ Copy top and down rho into Q for easy implementation of rho time stepping
        """
        mx, my, mz = qg.da.getSizes()
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()

        kdown = qg.grid.kdown
        kup = qg.grid.kup
        
        q = qg.da.getVecArray(qg.Q)
                
        if flag_PSI:
            psi = qg.da.getVecArray(qg.PSI)        
            psi2rho = -(qg.rho0*qg.f0)/qg.g
            for j in range(ys, ye):
                for i in range(xs, xe):           
                    q[i, j, kdown] = (psi[i,j,kdown+1]-psi[i,j,kdown])/qg.grid.dzw[kdown] *psi2rho
                    q[i, j, kup] = (psi[i,j,kup]-psi[i,j,kup-1])/qg.grid.dzw[kup-1] *psi2rho
        else:
            rho = qg.da.getVecArray(qg.RHO)        
            for j in range(ys, ye):
                for i in range(xs, xe):           
                    q[i, j, kdown] = 0.5*(rho[i, j, kdown]+rho[i, j, kdown+1])
                    q[i, j, kup] = 0.5*(rho[i, j, kup]+rho[i, j, kup-1])
                
        return
            

    def reset_topdown_q(self, qg):
        """ reset Q with simplest extrapolation
        """
        mx, my, mz = qg.da.getSizes()
        (xs, xe), (ys, ye), (zs, ze) = qg.da.getRanges()

        kdown = qg.grid.kdown
        kup = qg.grid.kup
        
        q = qg.da.getVecArray(qg.Q)

        for j in range(ys, ye):
            for i in range(xs, xe):           
                q[i, j, kdown] = q[i, j, kdown+1]
                q[i, j, kup] = q[i, j, kup-1]
                
        return