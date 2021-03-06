#!/usr/bin/python
# -*- encoding: utf8 -*-

"""
Run qgsolver with outputs from idealized ROMS numerical simulations
"""

import time
import sys

from qgsolver.qg import qg_model
from qgsolver.state import add

#
#==================== ROMS case ============================================
#

d2s = 86400.

def roms_input_runs(ncores_x=32, ncores_y=12, ping_mpi_cfg=False):
    ''' Tests with roms configuration (spatially uniform, vertically stretched)
    '''

    #ncores_x=2; ncores_y=4; # desktop
    #ncores_x=32; ncores_y=12; # datarmor

    if ping_mpi_cfg:
        # escape before computing
        return ncores_x, ncores_y
    
    else:
        
        # proceeds with computations
        start_time = time.time()
        cur_time = start_time
        
        # Top and Bottom boundary condition type: 'N' for Neumann, 'D' for Dirichlet
        bdy_type = {'top': 'N_PSI', 'bottom': 'N_PSI', 'periodic': True}

        # vertical subdomain
        vdom = {'Nz': 50}

        # horizontal subdomain
        hdom = {'Nx': 256, 'Ny': 720}
        # 256 = 2^8
        # 720 = 2^4 x 3^2 x 5

        datapath = '../input/'
        outdir = '../output/'
        hgrid = datapath+'roms_metrics.nc'
        vgrid = datapath+'roms_metrics.nc'
        file_q = datapath+'roms_pv.nc'
        file_psi = datapath+'roms_psi.nc'
        #file_rho = datapath+'roms_rho.nc'
        file_bg = datapath+'roms_bg.nc'
               
        qg = qg_model(ncores_x=ncores_x, ncores_y=ncores_y,
                      hgrid=hgrid, vgrid=vgrid, vdom=vdom, hdom=hdom, mask=True,
                      boundary_types=bdy_type,
                      f0N2_file=file_q, K=200.e0, dt=0.02 * d2s,
                      verbose=1)

        # start filling in variables    
        qg.set_q(file=file_q)
        qg.set_psi(file=file_psi)   
        #qg.set_rho(file=file_rho)
        #qg.write_state(filename=outdir+'output0.nc')
        qg.write_state(filename=outdir+'input.nc')
        # substract background state
        bstate = qg.set_bstate(file=file_bg)
        add(qg.state,bstate,da=None,a2=-1.)
        #qg.state += -bstate
        qg.write_state(filename=outdir+'input.nc', append=True)
        # after PV inversion
        qg.invert_pv()
        qg.write_state(filename=outdir+'input.nc', append=True)

        # compute CFL
        CFL = qg.compute_CFL()
        if qg._verbose>0: print('CFL='+str(CFL))
                
        #
        test=2
        if test==0:
            #Should be updated
            # one time step and store
            #qg.tstep(1, rho_sb=True, bstate=bstate)
            #qg.write_state(filename=outdir+'output.nc', append=True)
            pass
        elif test==1:
            #Should be updated
            #while qg.tstepper.t/86400. < 200 :
            #    qg.tstep(50, rho_sb=True, bstate=bstate)
            #    qg.write_state(filename=outdir+'output.nc', append=True)
            pass
        elif test==2:
            Ndays = 100.   # in days
            dt_out = .1    # in days
            #
            idx=1
            di = int(dt_out * d2s/qg.tstepper.dt)
            while qg.tstepper.t/d2s < Ndays :
                qg.write_state(filename=outdir+'output_%.3i.nc'%idx)
                #
                qg.tstep(di, rho_sb=True, bstate=bstate)
                KE = qg.compute_KE()
                if qg._verbose>0: print(' KE = %.6e' %KE)
                idx+=1
        
        if qg._verbose>0:
            print('----------------------------------------------------')
            print('Elapsed time for all ',str(time.time() - cur_time))
                         
        return qg




def main(ping_mpi_cfg=False):    
    
    #
    qg = roms_input_runs(ping_mpi_cfg=ping_mpi_cfg)
    # 
    
    if ping_mpi_cfg:
        return qg[0], qg[1]
    elif qg._verbose:
        print('All done \n')


if __name__ == "__main__":
    main()
    
    
