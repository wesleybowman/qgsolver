#!/usr/bin/python
# -*- encoding: utf8 -*-

""" Create metrics, psi, pv fields for a curvlinear grid
    
    Test version by SF (16 Feb 17)
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from netCDF4 import Dataset

# maybe temporary
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.fftpack._fftpack import zfft

d2r = np.pi/180.
reflev=250

def create_nc(filename, lon, lat, zc, zf):
    
    ### create a netcdf file
    rootgrp = Dataset(filename, 'w',
                      format='NETCDF4_CLASSIC', clobber=True)

    # create dimensions
    rootgrp.createDimension('x', lon.shape[1])
    rootgrp.createDimension('y', lat.shape[0])
    rootgrp.createDimension('zc', zc.size)
    rootgrp.createDimension('zf', zf.size)
    
    # create variables
    dtype='f8'
    nc_lon = rootgrp.createVariable('lon',dtype,('y','x'))
    nc_lat = rootgrp.createVariable('lat',dtype,('y','x'))
    nc_zc = rootgrp.createVariable('zc',dtype,('zc'))
    nc_zf = rootgrp.createVariable('zf',dtype,('zf'))
    
    nc_lon[:] = lon
    nc_lat[:] = lat
    nc_zc[:] = zc
    nc_zf[:] = zf
        
    #rootgrp.createVariable(name,dtype,('z','y','x',)))
    return rootgrp



if __name__ == "__main__":
    
    
    ### NEMO grid file
    datadir='/home7/pharos/othr/NATL60/'
    #datadir='data/'
    griddir=datadir+'NATL60-I/BOXES/'
    
    
    ### horizontal grid
    hgrid_file=griddir+'NATL60LMX_coordinates_v4.nc'
    
    hgrid = Dataset(hgrid_file, 'r')
    lon = hgrid.variables['nav_lon'][:]
    lat = hgrid.variables['nav_lat'][:]
    e1 = hgrid.variables['e1t'][:]
    e2 = hgrid.variables['e2t'][:]
    
    
    ### vertical grid
    vgrid_file=griddir+'NATL60LMX_v4.1_cdf_mesh_zgr.nc'
    
    vgrid = Dataset(vgrid_file, 'r')
    zc = -vgrid.variables['gdept_0'][0,::-1]
    zf = -vgrid.variables['gdepw_0'][0,::-1]   
    # myzc = -vgrid.variables['gdept_0'][0,:]
    # myzf = -vgrid.variables['gdepw_0'][0,:]  
    nz=zc.shape[0]
    dzc = np.diff(zf)
    dzf = np.diff(zc)

    
    # compute the Coriolis frequency and a reference value
    # from oocgcm/oocgcm/parameters/physicalparameters.py
    grav = 9.81                  # acceleration due to gravity (m.s-2)
    omega = 7.292115083046061e-5 # earth rotation rate (s-1)
    earthrad = 6371229            # mean earth radius (m)
    f = 2. * omega * np.sin(lat * d2r)
    f0 = np.mean(f)
    f0 = 8.5158e-5    
    rho0 = 1000.
    dtype='f8'


    ### load  rho
    
    rho_file = datadir+'DIAG_DIMUP/density/LMX/LMX_y2007m01d01_density.nc'
    rhoin = Dataset(rho_file, 'r')
    rho = rhoin.variables['density'][:]
 

    # load background density
    rhobg_file = datadir+'DIAG_DIMUP/2007_2008/LMX/bg/LMX_2007_2008_density_bg_mindepth10.nc'
    bgin = Dataset(rhobg_file, 'r')
    rhobg = bgin.variables['density_bg'][:]
    rho[:,:,:]=np.flipud(rho[:,:,:]-rhobg[:,None,None])
 

    # create netcdf file with dpsi/dz from rho at level reflev        
    rhoout = create_nc('data/rho.nc', lon, lat, zc[reflev], zf[reflev])
    nc_rholev = rhoout.createVariable('rholev',dtype,('zc','y','x'))
    nc_rholev[0,:,:] = - grav*0.5*(rho[reflev,:,:] + rho[reflev+1,:,:])/(rho0*f0)

    ### load and store psi
    
    # psi_file = datadir+'DIAG_DIMUP/psi0/LMX/LMX_y2007m01d01_psi0_test16fev17_nopsfc.nc'
    psi_file = datadir+'DIAG_DIMUP/psi0/LMX/LMX_y2007m01d01_psi0_split.nc'
    psiin = Dataset(psi_file, 'r')
    # psi = np.flipud(psiin.variables['psi0'][:])
    psi_hydro = psiin.variables['psi0_hydrostatic'][:]       
    # psi_surf = psiin.variables['psi0_surface_pressure'][:]
    # psi = np.flipud(psi_hydro+psi_surf)
    psi = np.flipud(psi_hydro)



    # # compute my psi from rho
    # mypsi = np.empty_like(rho) 
    # mypsi[0,:,:] = -0.5*grav*(myzf[0]-myzc[0])*(rho[0,:,:]- rhobg[0])/rho0/f0
    # for k in range(1,zc.size):
    #     mypsi[k,:,:]=mypsi[k-1,:,:] - 0.5*grav*(myzc[k-1]-myzc[k])*(rho[k-1,:,:]-rhobg[k-1]+ \
    #         rho[k,:,:]- rhobg[k])/rho0/f0

    # create netcdf file with dpsi/dz at level reflev
    dpsidzout = create_nc('data/dpsidz.nc', lon, lat, zc[reflev], zf[reflev])
    nc_dpsidz = dpsidzout.createVariable('dpsidz',dtype,('zc','y','x'))
    nc_dpsidz[0,:,:] = (psi[reflev+1,:,:]-psi[reflev,:,:])/dzf[reflev]

    # create netcdf file with dpsi/dz - rho at level reflev
    diffmy = create_nc('data/diff.nc', lon, lat, zc[reflev], zf[reflev])
    diff = diffmy.createVariable('diff',dtype,('zc','y','x'))
    diff[:] = nc_dpsidz[:]- nc_rholev[:]
 

