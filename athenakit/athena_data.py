import os
from pathlib import Path
import numpy as np
global cupy_enabled
try:
    import cupy as xp
    cupy_enabled = True
except ImportError:
    import numpy as xp
    cupy_enabled = False
import h5py
import pickle
import warnings
from packaging.version import parse as version_parse

from matplotlib import pyplot as plt

from .io import read_binary
from .utils import save_dict_to_hdf5, load_dict_from_hdf5

def load(filename):
    ad = AthenaData(filename)
    ad.load(filename,config=True)
    return ad

def asnumpy(arr):
    if (cupy_enabled):
        return xp.asnumpy(arr)
    else:
        return arr

class AthenaData:
    def __init__(self,num=0,version='1.0'):
        self.num=num
        self.version=version
        self._header={}
        self.binary={}
        self.coord={}
        self.data_raw={}
        self.data_func={}
        self.sums={}
        self.avgs={}
        self.hists={}
        self.profs={}
        self.slices={}
        self.spectra={}
        return
    
    # TODO(@mhguo): write a correct function to load data
    def load(self,filename,config=True,**kwargs):
        self.filename=filename
        if (filename.endswith('.bin')):
            self.binary_name = filename
            self.load_binary(filename,**kwargs)
        elif (filename.endswith('.athdf')):
            self.athdf_name = filename
            self.load_athdf(filename,**kwargs)
        elif (filename.endswith(('.h5','.hdf5'))):
            self.hdf5_name = filename
            self.load_hdf5(filename,**kwargs)
        elif (filename.endswith('.pkl')):
            self.hdf5_name = filename
            self.load_pickle(filename,**kwargs)
        else:
            raise ValueError(f"Unknown file type: {filename.split('.')[-1]}")
        if (config):
            self.config()
        return

    def save(self,filename,except_keys=[],
             default_except_keys=['binary', 'h5file', 'h5dic', 'coord', 'data_raw', 'data_func'],
             **kwargs):
        dic={}
        for k,v in self.__dict__.items():
            if (k not in except_keys+default_except_keys and not callable(v)):
                if(type(v) in [xp.ndarray]):
                    dic[k]=asnumpy(v)
                else:
                    dic[k]=v
        if (filename.endswith(('.h5','.hdf5'))):
            self.save_hdf5(dic,filename,**kwargs)
        elif (filename.endswith(('.p','.pkl'))):
            self.save_pickle(dic,filename,**kwargs)
        else:
            raise ValueError(f"Unknown file type: {filename.split('.')[-1]}")
        return

    def load_binary(self,filename):
        self._load_from_binary(read_binary(filename))
        return

    # TODO(@mhguo): write a correct function to load data from athena++ hdf5 data
    def load_athdf(self,filename):
        self._load_from_athdf(filename)
        return
    
    def load_pickle(self,filename,**kwargs):
        self._load_from_dic(pickle.load(open(filename,'rb')),**kwargs)
        return

    def load_hdf5(self,filename,**kwargs):
        self._load_from_dic(load_dict_from_hdf5(filename),**kwargs)
        return

    def save_hdf5(self,dic,filename):
        save_dict_to_hdf5(dic,filename)
        return
    
    def save_pickle(self,dic,filename):
        pickle.dump(dic,open(filename,'wb'))
        return

    def _load_from_dic(self,dic,except_keys=['header', 'data', 'binary', 'coord', 'data_raw']):
        for k,v in dic.items():
            if (k not in except_keys):
                self.__dict__[k]=v
        return

    def _load_from_binary(self,binary):
        self.binary = binary
        self._load_from_dic(self.binary)
        for var in self.binary['var_names']:
            self.data_raw[var]=xp.asarray(binary['mb_data'][var])
        self._config_header(self.binary['header'])
        self._config_attrs_from_header()
        return
    
    def _load_from_athdf(self,filename):
        h5file = h5py.File(filename, mode='r')
        self.h5file = h5file
        self.h5dic = load_dict_from_hdf5(filename)
        self._config_header(self.h5file.attrs['Header'])
        self._config_attrs_from_header()
        self.time = self.h5file.attrs['Time']
        self.cycle = self.h5file.attrs['NumCycles']
        self.n_mbs = self.h5file.attrs['NumMeshBlocks']
        self.mb_logical = xp.append(self.h5dic['LogicalLocations'],self.h5dic['Levels'].reshape(-1,1),axis=1)
        self.mb_geometry = xp.asarray([self.h5dic['x1f'][:,0],self.h5dic['x1f'][:,-1],
                                       self.h5dic['x2f'][:,0],self.h5dic['x2f'][:,-1],
                                       self.h5dic['x3f'][:,0],self.h5dic['x3f'][:,-1],]).T
        n_var_read = 0
        for ds_n,num in enumerate(self.h5file.attrs['NumVariables']):
            for i in range(num):
                var = self.h5file.attrs['VariableNames'][n_var_read+i].decode("utf-8")
                self.data_raw[var] = xp.asarray(self.h5dic[self.h5file.attrs['DatasetNames'][ds_n].decode("utf-8")][i])
            n_var_read += num
        return

    def config(self):
        if (not self.coord): self.set_coord()
        self._config_data_func()
        self.path = str(Path(self.filename).parent)
        self.num = int(self.filename.split('.')[-2])
        # assuming use_e=True
        # assuming we have dens, velx, vely, velz, eint
        # TODO(@mhguo): add support for arbitrary variables
        return

    def _config_header(self, header):
        for line in [entry for entry in header]:
            if line.startswith('<'):
                block = line.strip('<').strip('>')
                self._header[block]={}
                continue
            key, value = line.split('=')
            self._header[block][key.strip()] = value

    def header(self, blockname, keyname, astype=str, default=None):
        blockname = blockname.strip()
        keyname = keyname.strip()
        if blockname in self._header.keys():
            if keyname in self._header[blockname].keys():
                return astype(self._header[blockname][keyname])
        warnings.warn(f'Warning: no parameter called {blockname}/{keyname}, return default value: {default}')
        return default
    
    def _config_attrs_from_header(self):
        self.Nx1 = self.header( 'mesh', 'nx1', int)
        self.Nx2 = self.header( 'mesh', 'nx2', int)
        self.Nx3 = self.header( 'mesh', 'nx3', int)
        self.nx1 = self.header( 'meshblock', 'nx1', int)
        self.nx2 = self.header( 'meshblock', 'nx2', int)
        self.nx3 = self.header( 'meshblock', 'nx3', int)
        self.nghost = self.header( 'mesh', 'nghost', int)
        self.x1min = self.header( 'mesh', 'x1min', float)
        self.x1max = self.header( 'mesh', 'x1max', float)
        self.x2min = self.header( 'mesh', 'x2min', float)
        self.x2max = self.header( 'mesh', 'x2max', float)
        self.x3min = self.header( 'mesh', 'x3min', float)
        self.x3max = self.header( 'mesh', 'x3max', float)

        self.use_e=self.header('hydro','use_e',bool,True) if 'hydro' in self._header.keys() else self.header('mhd','use_e',bool,True) 
        self.gamma=self.header('hydro','gamma',float,5/3) if 'hydro' in self._header.keys() else self.header('mhd','gamma',float,5/3)
        
        return
    
    def set_coord(self):
        mb_geo, n_mbs = self.mb_geometry, self.n_mbs
        nx1, nx2, nx3 = self.nx1, self.nx2, self.nx3
        x=xp.swapaxes(xp.linspace(mb_geo[:,0],mb_geo[:,1],nx1+1),0,1)
        y=xp.swapaxes(xp.linspace(mb_geo[:,2],mb_geo[:,3],nx2+1),0,1)
        z=xp.swapaxes(xp.linspace(mb_geo[:,4],mb_geo[:,5],nx3+1),0,1)
        x,y,z=0.5*(x[:,:-1]+x[:,1:]),0.5*(y[:,:-1]+y[:,1:]),0.5*(z[:,:-1]+z[:,1:])
        ZYX=xp.swapaxes(xp.asarray([xp.meshgrid(z[i],y[i],x[i]) for i in range(n_mbs)]),0,1)
        self.coord['x'],self.coord['y'],self.coord['z']=ZYX[2].swapaxes(1,2),ZYX[1].swapaxes(1,2),ZYX[0].swapaxes(1,2)
        dx=xp.asarray([xp.full((nx3,nx2,nx1),(mb_geo[i,1]-mb_geo[i,0])/nx1) for i in range(n_mbs)])
        dy=xp.asarray([xp.full((nx3,nx2,nx1),(mb_geo[i,3]-mb_geo[i,2])/nx2) for i in range(n_mbs)])
        dz=xp.asarray([xp.full((nx3,nx2,nx1),(mb_geo[i,5]-mb_geo[i,4])/nx3) for i in range(n_mbs)])
        self.coord['dx'],self.coord['dy'],self.coord['dz']=dx,dy,dz
        return

    ### data handling ###
    def add_data_func(self,name,func):
        self.data_func[name]=func
        return
    
    def _config_data_func(self):
        self.data_func['zeros'] = lambda self : xp.zeros(self.data('dens').shape)
        self.data_func['ones'] = lambda self : xp.ones(self.data('dens').shape)
        self.data_func['vol'] = lambda self : self.data('dx')*self.data('dy')*self.data('dz')
        self.data_func['r'] = lambda self : xp.sqrt(self.data('x')**2+self.data('y')**2+self.data('z')**2)
        self.data_func['mass'] = lambda self : self.data('vol')*self.data('dens')
        self.data_func['pres'] = lambda self : (self.gamma-1)*self.data('eint')
        self.data_func['temp'] = lambda self : (self.gamma-1)*self.data('eint')/self.data('dens')
        self.data_func['entropy'] = lambda self : self.data('pres')/self.data('dens')**self.gamma
        self.data_func['c_s^2'] = lambda self : self.gamma*self.data('pres')/self.data('dens')
        self.data_func['c_s'] = lambda self : xp.sqrt(self.data('c_s^2'))
        self.data_func['momx'] = lambda self : self.data('velx')*self.data('dens')
        self.data_func['momy'] = lambda self : self.data('vely')*self.data('dens')
        self.data_func['momz'] = lambda self : self.data('velz')*self.data('dens')
        self.data_func['velr'] = lambda self : (self.data('velx')*self.data('x')+\
                                               self.data('vely')*self.data('y')+\
                                               self.data('velz')*self.data('z'))/self.data('r')
        self.data_func['momr'] = lambda self : self.data('velr')*self.data('dens')
        self.data_func['velin'] = lambda self : xp.minimum(self.data('velr'),0.0)
        self.data_func['velout'] = lambda self : xp.maximum(self.data('velr'),0.0)
        self.data_func['vtot^2'] = lambda self : self.data('velx')**2+self.data('vely')**2+self.data('velz')**2
        self.data_func['vtot'] = lambda self : xp.sqrt(self.data('vtot^2'))
        self.data_func['vrot'] = lambda self : xp.sqrt(self.data('vtot^2')-self.data('velr')**2)
        self.data_func['momtot'] = lambda self : self.data('dens')*self.data('vtot')
        self.data_func['ekin'] = lambda self : 0.5*self.data('dens')*self.data('vtot^2')
        self.data_func['etot'] = lambda self : self.data('ekin')+self.data('eint')
        self.data_func['amx'] = lambda self : self.data('y')*self.data('velz')-self.data('z')*self.data('vely')
        self.data_func['amy'] = lambda self : self.data('z')*self.data('velx')-self.data('x')*self.data('velz')
        self.data_func['amz'] = lambda self : self.data('x')*self.data('vely')-self.data('y')*self.data('velx')
        self.data_func['amtot'] = lambda self : self.data('r')*self.data('vrot')
        self.data_func['mflxr'] = lambda self : self.data('dens')*self.data('velr')
        self.data_func['mflxrin'] = lambda self : self.data('dens')*self.data('velin')
        self.data_func['mflxrout'] = lambda self : self.data('dens')*self.data('velout')
        self.data_func['momflxr'] = lambda self : self.data('dens')*self.data('velr')**2
        self.data_func['momflxrin'] = lambda self : self.data('dens')*self.data('velr')*self.data('velin')
        self.data_func['momflxrout'] = lambda self : self.data('dens')*self.data('velr')*self.data('velout')
        self.data_func['ekflxr'] = lambda self : self.data('dens')*.5*self.data('vtot^2')*self.data('velr')
        self.data_func['ekflxrin'] = lambda self : self.data('dens')*.5*self.data('vtot^2')*self.data('velin')
        self.data_func['ekflxrout'] = lambda self : self.data('dens')*.5*self.data('vtot^2')*self.data('velout')
        self.data_func['bccx'] = lambda self : self.data('bcc1')
        self.data_func['bccy'] = lambda self : self.data('bcc2')
        self.data_func['bccz'] = lambda self : self.data('bcc3')
        self.data_func['bccr'] = lambda self : (self.data('bccx')*self.data('x')+\
                                                self.data('bccy')*self.data('y')+\
                                                self.data('bccz')*self.data('z'))/self.data('r')
        self.data_func['btot^2'] = lambda self : self.data('bccx')**2+self.data('bccy')**2+self.data('bccz')**2
        self.data_func['btot'] = lambda self : xp.sqrt(self.data('btot^2'))
        self.data_func['brot'] = lambda self : xp.sqrt(self.data('btot^2')-self.data('bccr')**2)
        self.data_func['v_A^2'] = lambda self : self.data('btot^2')/self.data('dens')
        self.data_func['v_A'] = lambda self : xp.sqrt(self.data('v_A^2'))
        self.data_func['beta'] = lambda self : self.data('pres')/self.data('btot^2')
        return

    @property
    def data_list(self):
        return list(self.coord.keys())+list(self.data_raw.keys())+list(self.data_func.keys())

    def data(self,var):
        if (type(var) is str):
            # coordinate
            if (var in self.coord.keys()):
                return self.coord[var]
            # raw data
            elif (var in self.data_raw.keys()):
                return self.data_raw[var]
            # derived data
            elif (var in self.data_func.keys()):
                return self.data_func[var](self)
            else:
                raise ValueError(f"No variable callled '{var}' ")
        elif (type(var) in [list,tuple]):
            return [self.data(v) for v in var]
        else:
            return var

    ### get data in a single array ###
    # TODO(@mhguo): deal with the cell center and cell edge issue
    def get_refined_coord(self,level=0,xyz=[]):
        if (not xyz):
            xyz = [self.x1min,self.x1max,self.x2min,self.x2max,self.x3min,self.x3max]
        # level is physical level
        nx1_fac = 2**level*self.Nx1/(self.x1max-self.x1min)
        nx2_fac = 2**level*self.Nx2/(self.x2max-self.x2min)
        nx3_fac = 2**level*self.Nx3/(self.x3max-self.x3min)
        i_min = int((xyz[0]-self.x1min)*nx1_fac)
        i_max = int((xyz[1]-self.x1min)*nx1_fac)
        j_min = int((xyz[2]-self.x2min)*nx2_fac)
        j_max = int((xyz[3]-self.x2min)*nx2_fac)
        k_min = int((xyz[4]-self.x3min)*nx3_fac)
        k_max = int((xyz[5]-self.x3min)*nx3_fac)
        # TODO(@mhguo)
        #data = xp.zeros((k_max-k_min, j_max-j_min, i_max-i_min))
        x=xp.linspace(xyz[0],xyz[1],i_max-i_min)
        y=xp.linspace(xyz[2],xyz[3],j_max-j_min)
        z=xp.linspace(xyz[4],xyz[5],k_max-k_min)
        dx=(xyz[1]-xyz[0])/(i_max-i_min)
        dy=(xyz[3]-xyz[2])/(j_max-j_min)
        dz=(xyz[5]-xyz[4])/(k_max-k_min)
        ZYX=xp.meshgrid(z,y,x)
        return ZYX[2].swapaxes(0,1),ZYX[1].swapaxes(0,1),ZYX[0].swapaxes(0,1),dx,dy,dz

    def get_refined_data(self,var,level=0,xyz=[]):
        if (not xyz):
            xyz = [self.x1min,self.x1max,self.x2min,self.x2max,self.x3min,self.x3max]
        # block_level is physical level of mesh refinement
        physical_level = level
        nx1_fac = 2**level*self.Nx1/(self.x1max-self.x1min)
        nx2_fac = 2**level*self.Nx2/(self.x2max-self.x2min)
        nx3_fac = 2**level*self.Nx3/(self.x3max-self.x3min)
        i_min = int((xyz[0]-self.x1min)*nx1_fac)
        i_max = int((xyz[1]-self.x1min)*nx1_fac)
        j_min = int((xyz[2]-self.x2min)*nx2_fac)
        j_max = int((xyz[3]-self.x2min)*nx2_fac)
        k_min = int((xyz[4]-self.x3min)*nx3_fac)
        k_max = int((xyz[5]-self.x3min)*nx3_fac)
        data = xp.zeros((k_max-k_min, j_max-j_min, i_max-i_min))
        raw = self.data(var)
        for nmb in range(self.n_mbs):
            block_level = self.mb_logical[nmb,-1]
            block_loc = self.mb_logical[nmb,:3]
            block_data = raw[nmb]
            
            # Prolongate coarse data and copy same-level data
            if (block_level <= physical_level):
                s = int(2**(physical_level - block_level))
                # Calculate destination indices, without selection
                il_d = block_loc[0] * self.nx1 * s if self.Nx1 > 1 else 0
                jl_d = block_loc[1] * self.nx2 * s if self.Nx2 > 1 else 0
                kl_d = block_loc[2] * self.nx3 * s if self.Nx3 > 1 else 0
                iu_d = il_d + self.nx1 * s if self.Nx1 > 1 else 1
                ju_d = jl_d + self.nx2 * s if self.Nx2 > 1 else 1
                ku_d = kl_d + self.nx3 * s if self.Nx3 > 1 else 1
                # Calculate (prolongated) source indices, with selection
                il_s = max(il_d, i_min) - il_d
                jl_s = max(jl_d, j_min) - jl_d
                kl_s = max(kl_d, k_min) - kl_d
                iu_s = min(iu_d, i_max) - il_d
                ju_s = min(ju_d, j_max) - jl_d
                ku_s = min(ku_d, k_max) - kl_d
                if il_s >= iu_s or jl_s >= ju_s or kl_s >= ku_s:
                    continue
                # Account for selection in destination indices
                il_d = max(il_d, i_min) - i_min
                jl_d = max(jl_d, j_min) - j_min
                kl_d = max(kl_d, k_min) - k_min
                iu_d = min(iu_d, i_max) - i_min
                ju_d = min(ju_d, j_max) - j_min
                ku_d = min(ku_d, k_max) - k_min
                if s > 1:
                    if self.Nx1 > 1:
                        block_data = xp.repeat(block_data, s, axis=2)
                    if self.Nx2 > 1:
                        block_data = xp.repeat(block_data, s, axis=1)
                    if self.Nx3 > 1:
                        block_data = xp.repeat(block_data, s, axis=0)
                data[kl_d:ku_d,jl_d:ju_d,il_d:iu_d]=block_data[kl_s:ku_s,jl_s:ju_s,il_s:iu_s]
            # Restrict fine data, volume average
            else:
                # Calculate scale
                s = int(2 ** (block_level - physical_level))
                # Calculate destination indices, without selection
                il_d = int(block_loc[0] * self.nx1 / s) if self.Nx1 > 1 else 0
                jl_d = int(block_loc[1] * self.nx2 / s) if self.Nx2 > 1 else 0
                kl_d = int(block_loc[2] * self.nx3 / s) if self.Nx3 > 1 else 0
                iu_d = int(il_d + self.nx1 / s) if self.Nx1 > 1 else 1
                ju_d = int(jl_d + self.nx2 / s) if self.Nx2 > 1 else 1
                ku_d = int(kl_d + self.nx3 / s) if self.Nx3 > 1 else 1
                #print(kl_d,ku_d,jl_d,ju_d,il_d,iu_d)
                # Calculate (restricted) source indices, with selection
                il_s = max(il_d, i_min) - il_d
                jl_s = max(jl_d, j_min) - jl_d
                kl_s = max(kl_d, k_min) - kl_d
                iu_s = min(iu_d, i_max) - il_d
                ju_s = min(ju_d, j_max) - jl_d
                ku_s = min(ku_d, k_max) - kl_d
                if il_s >= iu_s or jl_s >= ju_s or kl_s >= ku_s:
                    continue
                # Account for selection in destination indices
                il_d = max(il_d, i_min) - i_min
                jl_d = max(jl_d, j_min) - j_min
                kl_d = max(kl_d, k_min) - k_min
                iu_d = min(iu_d, i_max) - i_min
                ju_d = min(ju_d, j_max) - j_min
                ku_d = min(ku_d, k_max) - k_min
                
                # Account for restriction in source indices
                num_extended_dims = 0
                if self.Nx1 > 1:
                    il_s *= s
                    iu_s *= s
                    num_extended_dims += 1
                if self.Nx2 > 1:
                    jl_s *= s
                    ju_s *= s
                    num_extended_dims += 1
                if self.Nx3 > 1:
                    kl_s *= s
                    ku_s *= s
                    num_extended_dims += 1
                
                # Calculate fine-level offsets
                io_vals = range(s) if self.Nx1 > 1 else (0,)
                jo_vals = range(s) if self.Nx2 > 1 else (0,)
                ko_vals = range(s) if self.Nx3 > 1 else (0,)

                # Assign values
                for ko in ko_vals:
                    for jo in jo_vals:
                        for io in io_vals:
                            data[kl_d:ku_d,jl_d:ju_d,il_d:iu_d] += block_data[
                                                                kl_s+ko:ku_s:s,
                                                                jl_s+jo:ju_s:s,
                                                                il_s+io:iu_s:s]\
                                                                /(s**num_extended_dims)
        return data
    
    # helper functions similar to numpy/cupy
    def sum(self,var,**kwargs):
        return asnumpy(xp.sum(self.data(var),**kwargs))
    def average(self,var,weights='ones',where=None,**kwargs):
        return asnumpy(xp.average(self.data(var)[where],weights=self.data(weights)[where],**kwargs))

    # kernal functions for histograms and profiles
    def _set_bins(self,var,bins,range,scale,where):
        if (type(bins) is int):
            if (scale=='linear'):
                if (range is None):
                    dat = self.data(var)[where]
                    dat = dat[xp.isfinite(dat)]
                    if dat.size==0:
                        warnings.warn(f"Warning: no bins for {var}, using linspace(0,1) instead")
                        return xp.linspace(0.0,1.0,bins+1)
                    return xp.linspace(dat.min(),dat.max(),bins+1)
                else:
                    return xp.linspace(range[0],range[1],bins+1)
            elif (scale=='log'):
                if (range is None):
                    dat = self.data(var)[where]
                    dat = dat[xp.isfinite(dat)]
                    dat = dat[dat>0.0]
                    if dat.size==0:
                        warnings.warn(f"Warning: no bins for {var}, using logspace(0,1) instead")
                        return xp.logspace(0.0,1.0,bins+1)
                    else:
                        return xp.logspace(xp.log10(dat.min()),xp.log10(dat.max()),bins+1)
                else:
                    return xp.logspace(xp.log10(range[0]),xp.log10(range[1]),bins+1)
            else:
                raise ValueError(f"scale '{scale}' not supported")
        return bins

    def _histograms(self,varll,bins=10,range=None,weights=None,scales='linear',where=None,**kwargs):
        """
        Compute the histogram of a list of variables

        Parameters
        ----------
        varll : list of list of str
            varaible list

        Returns
        -------
        hist : dict
            dictionary of distributions
        """
        if (type(varll) is str):
            varll = [varll]
        for i,varl in enumerate(varll):
            if (type(varl) is str):
                varll[i] = [varl]
        if (type(weights) is str):
            weights = self.data(weights)[where].ravel()
        if (type(scales) is str):
            scales = [scales]*len(varll)

        hists = {}
        bins_0 = bins
        range_0 = range
        for varl,scale in zip(varll,scales):
            arr = [self.data(v)[where].ravel() for v in varl]
            histname = '_'.join(varl)
            # get bins
            bins = [bins_0]*len(varl)
            scale = [scale]*len(varl) if (type(scale) is str) else scale
            range = [range_0]*len(varl) if (range_0 is None) else range_0
            for i,v in enumerate(varl):
                bins[i] = self._set_bins(v,bins[i],range[i],scale[i],where)
            bins = xp.asarray(bins)
            # get histogram
            hist = xp.histogramdd(arr,bins=bins,weights=weights,**kwargs)
            hists[histname] = {'dat':xp.asarray(hist[0]),'edges':xp.asarray(hist[1])}
            hists[histname]['centers'] = (hists[histname]['edges'][:,:-1]+hists[histname]['edges'][:,1:])/2
            for k in hists[histname].keys():
                hists[histname][k] = asnumpy(hists[histname][k])
        return hists

    def _profiles(self,bin_varl,varl,bins=10,range=None,weights=None,scales='linear',where=None,**kwargs):
        """
        Compute the profile of a (list of) variable with respect to one or more bin variables.

        Parameters
        ----------
        bin_varl : str or list of str
            bin varaible list
        
        varl : str or list of str
            variable list

        Returns
        -------
        profs : dict
            dictionary of profiles
        """
        if (type(bin_varl) is str):
            bin_varl = [bin_varl]
        if (type(varl) is str):
            varl = [varl]
        if (type(bins) is int):
            bins = [bins]*len(bin_varl)
        if (range is None):
            range = [None]*len(bin_varl)
        if (type(weights) is str):
            weights = self.data(weights)[where].ravel()
        if (type(scales) is str):
            scales = [scales]*len(bin_varl)
        for i,v in enumerate(bin_varl):
            bins[i] = self._set_bins(v,bins[i],range[i],scales[i],where)
        bins = xp.asarray(bins)
        bin_arr = [self.data(v)[where].ravel() for v in bin_varl]
        norm = xp.histogramdd(bin_arr,bins=bins,weights=weights,**kwargs)
        profs = {'edges':xp.asarray(norm[1]),'norm':xp.asarray(norm[0])}
        profs['centers'] = (profs['edges'][:,:-1]+profs['edges'][:,1:])/2
        for var in bin_varl:
            profs[var] = profs['centers'][bin_varl.index(var)]
        for var in varl:
            if (weights is None):
                data_weights = self.data(var)[where].ravel()
            else:
                data_weights = self.data(var)[where].ravel()*weights
            profs[var] = xp.histogramdd(bin_arr,bins=bins,weights=data_weights,**kwargs)[0]/norm[0]
        for k in profs.keys():
            profs[k] = asnumpy(profs[k])
        return profs

    ### get data in a dictionary ###
    def histogram(self,*args,**kwargs):
        hists = self._histograms(*args,**kwargs)
        for k in hists.keys():
            hists[k]['edges'] = hists[k]['edges'][0]
            hists[k]['centers'] = hists[k]['centers'][0]
        return hists
    def histogram2d(self,*args,**kwargs):
        return self._histograms(*args,**kwargs)
    
    def get_sum(self,varl,*args,**kwargs):
        varl = [varl] if (type(varl) is str) else varl
        return {var : self.sum(var,*args,**kwargs) for var in varl}
    def get_avg(self,varl,*args,**kwargs):
        varl = [varl] if (type(varl) is str) else varl
        return {var : self.average(var,*args,**kwargs) for var in varl}
    def set_sum(self,*args,**kwargs):
        self.sums.update(self.get_sum(*args,**kwargs))
    def set_avg(self,*args,**kwargs):
        self.avgs.update(self.get_avg(*args,**kwargs))

    def get_hist(self,varl,bins=128,scales='log',weights='vol',**kwargs):
        return self.histogram(varl,bins=bins,scales=scales,weights=weights,**kwargs)
    def get_hist2d(self,varl,bins=128,scales='log',weights='vol',**kwargs):
        return self.histogram2d(varl,bins=bins,scales=scales,weights=weights,**kwargs)
    def get_profile(self,bin_var,varl,bins=256,weights='vol',**kwargs):
        return self._profiles(bin_var,varl,bins=bins,weights=weights,**kwargs)
    def get_profile2d(self,bin_varl,varl,bins=256,weights='vol',**kwargs):
        return self._profiles(bin_varl,varl,bins=bins,weights=weights,**kwargs)

    def set_hist(self,varl,key=None,bins=128,scales='log',weights='vol',**kwargs):
        key = weights if key is None else key
        if key not in self.hists.keys():
            self.hists[key] = {}
        self.hists[key].update(self.get_hist(varl,bins=bins,scales=scales,weights=weights,**kwargs))
    def set_hist2d(self,varl,key=None,bins=128,scales='log',weights='vol',**kwargs):
        key = weights if key is None else key
        if key not in self.hists.keys():
            self.hists[key] = {}
        self.hists[key].update(self.get_hist2d(varl,bins=bins,scales=scales,weights=weights,**kwargs))

    def set_profile(self,bin_var,varl,key=None,bins=256,weights='vol',**kwargs):
        key = bin_var if key is None else key
        if key not in self.profs.keys():
            self.profs[key] = {}
        self.profs[key].update(self.get_profile(bin_var,varl,bins=bins,weights=weights,**kwargs))
    def set_profile2d(self,bin_varl,varl,key=None,bins=256,weights='vol',**kwargs):
        key = '_'.join(bin_varl) if key is None else key
        if key not in self.profs.keys():
            self.profs[key] = {}
        self.profs[key].update(self.get_profile2d(bin_varl,varl,bins=bins,weights=weights,**kwargs))

    # TODO(@mhguo): use profile 2d now, need to change to a real slice!
    def set_slice(self,bin_varl,varl,key=None,**kwargs):
        key = 'z' if key is None else key
        if key not in self.slices.keys():
            self.slices[key] = {}
        self.slices[key].update(self.get_profile2d(bin_varl,varl,**kwargs))

    #def get_radial(self,varl=['dens','temp','velr','mflxr'],bins=256,scales='log',weights='vol',**kwargs):
    #    return self._profiles(['r'],varl,bins=bins,scales=scales,weights=weights,**kwargs)
    #def set_radial(self,varl=['dens','temp','velr','mflxr'],bins=256,scales='log',weights='vol',**kwargs):
    #    self.profs.update(self.get_radial(varl,bins=bins,scales=scales,weights=weights,**kwargs))

    def get_slice_coord(self,zoom=0,level=0,xyz=[],axis=0):
        if (not xyz):
            xyz = [self.x1min/2**zoom,self.x1max/2**zoom,
                   self.x2min/2**zoom,self.x2max/2**zoom,
                   self.x3min/2**level/self.Nx3,self.x3max/2**level/self.Nx3]
        x,y,z,dx,dy,dz=self.get_refined_coord(level=level,xyz=xyz)
        return xp.average(x,axis=axis),xp.average(y,axis=axis),xp.average(z,axis=axis),xyz

    # TODO(@mhguo): we should have the ability to get slice at any position with any direction
    def get_slice(self,var='dens',zoom=0,level=0,xyz=[],axis=0):
        if (not xyz):
            xyz = [self.x1min/2**zoom,self.x1max/2**zoom,
                   self.x2min/2**zoom,self.x2max/2**zoom,
                   self.x3min/2**level/self.Nx3,self.x3max/2**level/self.Nx3]
        return xp.average(self.get_refined_data(var,level=level,xyz=xyz),axis=axis),xyz
    
    #def get_slice(self,var='dens',normal='z',north='y',center=[0.,0.,0.],width=1,height=1,zoom=0,level=0):
    #    return

    '''def set_slice(self,varl=['dens','temp'],varsuf='',zoom=0,level=0,xyz=[],axis=0,redo=False):
        for var in varl:
            varname = var+varsuf
            if (redo or varname not in self.slices.keys()):
                self.slices[varname] = {}
                data = self.get_slice(var,zoom=zoom,level=level,xyz=xyz,axis=axis)
                self.slices[varname]['dat'] = data[0]
                self.slices[varname]['xyz'] = data[1]
    '''

    def plot_snapshot(self,var='dens',data=None,varname='',zoom=0,level=0,xyz=[],unit=1.0,bins=None,\
                   title='',label='',xlabel='X',ylabel='Y',cmap='viridis',\
                   norm='log',save=False,figdir='../figure/Simu_',figpath=None,\
                   savepath='',savelabel='',figlabel='',dpi=200,vec=None,stream=None,circle=True,\
                   fig=None,ax=None,xyunit=1.0,colorbar=True,returnim=False,stream_color='k',stream_linewidth=None,\
                   stream_arrowsize=None,vecx='velx',vecy='vely',vel_method='ave',axis=0,**kwargs):
        fig=plt.figure(dpi=dpi) if fig is None else fig
        ax = plt.axes() if ax is None else ax
        bins=int(xp.min(xp.asarray([self.Nx1,self.Nx2,self.Nx3]))) if not bins else bins
        varname = var+f'_{zoom}' if not varname else varname
        if (not xyz):
            xyz = [self.x1min/2**zoom,self.x1max/2**zoom,
                   self.x2min/2**zoom,self.x2max/2**zoom,
                   self.x3min/2**level/self.Nx3,self.x3max/2**level/self.Nx3]
        if (data is not None):
            slc = data['dat']*unit
            xyz = list(data['xyz'])
        elif varname in self.slices.keys():
            slc = self.slices[varname]['dat']*unit
            xyz = list(self.slices[varname]['xyz'])
        else:
            slc = self.get_slice(var,zoom=zoom,level=level,xyz=xyz,axis=axis)[0]*unit
        x0,x1,y0,y1,z0,z1 = xyz[0],xyz[1],xyz[2],xyz[3],xyz[4],xyz[5]
        if (vec is not None):
            x,y,z = self.get_slice_coord(zoom=zoom,level=vec,xyz=list(xyz),axis=axis)[:3]
            if (f'{vecx}_{zoom}' in self.slices.keys()):
                u = self.slices[f'{vecx}_{zoom}']['dat']
            else:
                u = self.get_slice(vecx,zoom=zoom,level=level,xyz=list(xyz),axis=axis)[0]
            if (f'{vecy}_{zoom}' in self.slices.keys()):
                v = self.slices[f'{vecy}_{zoom}']['dat']
            else:
                v = self.get_slice(vecy,zoom=zoom,level=level,xyz=list(xyz),axis=axis)[0]
            #x = self.get_slice('x',zoom=zoom,level=vel,xyz=xyz)[0]
            #y = self.get_slice('y',zoom=zoom,level=vel,xyz=xyz)[0]
            fac=max(int(2**(level-vec)),1)
            if (vel_method=='ave'):
                n0,n1=int(u.shape[0]/fac),int(u.shape[1]/fac)
                u=xp.average(u.reshape(n0,fac,n1,fac),axis=(1,3))
                n0,n1=int(v.shape[0]/fac),int(v.shape[1]/fac)
                v=xp.average(v.reshape(n0,fac,n1,fac),axis=(1,3))
            else:
                u=u[int(fac/2)::fac,int(fac/2)::fac]
                v=v[int(fac/2)::fac,int(fac/2)::fac]
            x,y,u,v = asnumpy(x),asnumpy(y),asnumpy(u),asnumpy(v)
            ax.quiver(x*xyunit, y*xyunit, u, v)
        if (stream is not None):
            x,y,z = self.get_slice_coord(zoom=zoom,level=stream,xyz=xyz,axis=axis)[:3]
            #x = self.get_slice('x',zoom=zoom,level=stream,xyz=xyz)[0]
            #y = self.get_slice('y',zoom=zoom,level=stream,xyz=xyz)[0]
            if (f'{vecx}_{zoom}' in self.slices.keys()):
                u = self.slices[f'{vecx}_{zoom}']['dat']
            else:
                u = self.get_slice(vecx,zoom=zoom,level=level,xyz=list(xyz),axis=axis)[0]
            if (f'{vecy}_{zoom}' in self.slices.keys()):
                v = self.slices[f'{vecy}_{zoom}']['dat']
            else:
                v = self.get_slice(vecy,zoom=zoom,level=level,xyz=list(xyz),axis=axis)[0]
            #x,y=xp.meshgrid(x,y)
            #z,x=xp.meshgrid(z,x)
            #xp.mgrid[-w:w:100j, -w:w:100j]
            #beg=8
            #step=16
            #ax.streamplot(x[beg::step,beg::step], z[beg::step,beg::step], (u[0]/norm[0])[beg::step,beg::step], (v[0]/norm[0])[beg::step,beg::step])
            #print(x.shape,y.shape,u.shape,v.shape)
            # TODO(@mhguo): fix axis=1 case!
            #if(axis==1): x,y = z.swapaxes(0,1), x.swapaxes(0,1)
            if(axis==2): x,y = y,z
            ax.streamplot(x*xyunit, y*xyunit, u, v,color=stream_color,linewidth=stream_linewidth,arrowsize=stream_arrowsize)
        # TODO(@mhguo): fix axis=1 case!
        #if(axis==1): x0,x1,y0,y1 = z0,z1,x0,x1
        if(axis==2): x0,x1,y0,y1 = y0,y1,z0,z1
        im_arr = asnumpy(slc[::-1,:])
        im=ax.imshow(im_arr,extent=(x0*xyunit,x1*xyunit,y0*xyunit,y1*xyunit),\
            norm=norm,cmap=cmap,**kwargs)
        #im=ax.imshow(slc.swapaxes(0,1)[::-1,:],extent=(x0,x1,y0,y1),norm=norm,cmap=cmap,**kwargs)
        #im=ax.imshow(xp.rot90(data),cmap='plasma',norm=LogNorm(0.9e-1,1.1e1),extent=extent)
        if(circle and self.header('problem','r_in')):
            ax.add_patch(plt.Circle((0,0),float(self.header('problem','r_in')),ec='k',fc='#00000000'))
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if (title != None): ax.set_title(f"Time = {self.time}" if not title else title)
        if (colorbar):
            from mpl_toolkits.axes_grid1 import make_axes_locatable
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4%", pad=0.02)
            fig.colorbar(im,ax=ax,cax=cax, orientation='vertical',label=label)
        if (save):
            figpath=figdir+Path(self.path).parts[-1]+'/'+self.label+"/" if not figpath else figpath
            if (not os.path.isdir(figpath)):
                os.mkdir(figpath)
            fig.savefig(f"{figpath}fig_{varname+figlabel if not savelabel else savelabel}_{self.num:04d}.png"\
                        if not savepath else savepath, bbox_inches='tight')
        if (returnim):
            return fig,im
        return fig

    # plot is only for plot, accept the data array
    def plot_image(self,x,y,img,title='',label='',xlabel='X',ylabel='Y',xscale='linear',yscale='linear',\
                   cmap='viridis',norm='log',save=False,figfolder=None,figlabel='',figname='',\
                   dpi=200,fig=None,ax=None,colorbar=True,returnim=False,aspect='auto',**kwargs):
        fig=plt.figure(dpi=dpi) if fig is None else fig
        img = asnumpy(img[:,:])
        #print(x,y,img)
        im=ax.pcolormesh(x,y,img,norm=norm,cmap=cmap,**kwargs)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_xscale(xscale)
        ax.set_yscale(yscale)
        ax.set_aspect(aspect)
        if (title != None): ax.set_title(f"Time = {self.time}" if not title else title)
        if (colorbar):
            from mpl_toolkits.axes_grid1 import make_axes_locatable
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4%", pad=0.02)
            fig.colorbar(im,ax=ax,cax=cax, orientation='vertical',label=label)
        if (save):
            if (not os.path.isdir(figfolder)):
                os.mkdir(figfolder)
            fig.savefig(f"{figfolder}/fig_{figlabel}_{self.num:04d}.png"\
                        if not figname else figname, bbox_inches='tight')
        if (returnim):
            return fig,im
        return fig

    def plot_stream(self,dpi=200,fig=None,ax=None,x=None,y=None,u=None,v=None,
                    xyunit=1.0,stream_color='k',stream_linewidth=None,stream_arrowsize=None):
        fig=plt.figure(dpi=dpi) if fig is None else fig
        ax.streamplot(x*xyunit, y*xyunit, u, v, color=stream_color,linewidth=stream_linewidth,arrowsize=stream_arrowsize)
        return fig

    def plot_phase(self,varname='dens_temp',key='vol',bins=128,weights='vol',title='',label='',xlabel='X',ylabel='Y',xscale='log',yscale='log',\
                   unit=1.0,cmap='viridis',norm='log',extent=None,density=False,save=False,colorbar=True,savepath='',figdir='../figure/Simu_',\
                   figpath='',x=None,y=None,xshift=0.0,xunit=1.0,yshift=0.0,yunit=1.0,fig=None,ax=None,dpi=128,**kwargs):
        fig=plt.figure(dpi=dpi) if fig is None else fig
        ax = plt.axes() if ax is None else ax
        #print(key,varname)
        try:
            dat = self.hists[key][varname]
        except:
            dat = self.get_hist2d([varname.split('_')],bins=bins,scales=[[xscale,yscale]],weights=weights)[varname]
        x,y = asnumpy(dat['edges'])
        im_arr = asnumpy(dat['dat'])
        extent = [x.min(),x.max(),y.min(),y.max()] if extent is None else extent
        if (density):
            xlength = (extent[1]-extent[0] if xscale=='linear' else np.log10(extent[1]/extent[0]))/(x.shape[0]-1)
            ylength = (extent[3]-extent[2] if yscale=='linear' else np.log10(extent[3]/extent[2]))/(y.shape[0]-1)
            unit /= xlength*ylength
        #im = ax.imshow(dat['dat'].swapaxes(0,1)[::-1,:]*unit,extent=extent,norm=norm,cmap=cmap,aspect=aspect,**kwargs)
        im_arr = im_arr.T*unit
        x =  x*xunit+xshift
        y =  y*yunit+yshift
        fig,im=self.plot_image(x,y,im_arr,title=title,label=label,xlabel=xlabel,ylabel=ylabel,xscale=xscale,yscale=yscale,\
                     cmap=cmap,norm=norm,save=save,figfolder=figdir,figlabel=varname,figname=savepath,fig=fig,ax=ax,returnim=True,**kwargs)
        if (title != None): ax.set_title(f"Time = {self.time}" if not title else title)
        if (colorbar):
            from mpl_toolkits.axes_grid1 import make_axes_locatable
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4%", pad=0.02)
            fig.colorbar(im,ax=ax,cax=cax, orientation='vertical',label=label)
        if (save):
            figpath=figdir+Path(self.path).parts[-1]+'/'+self.label+"/" if not figpath else figpath
            if not os.path.isdir(figpath):
                os.mkdir(figpath)
            fig.savefig(f"{figpath}fig_{varname}_{self.num:04d}.png"\
                        if not savepath else savepath, bbox_inches='tight')
        return fig
    
    def plot_slice(self,var='dens',key=None,data=None,zoom=0,level=0,xyz=[],unit=1.0,bins=None,\
                   title='',label='',xlabel='X',ylabel='Y',cmap='viridis',\
                   norm='log',save=False,figdir='../figure/Simu_',figpath=None,\
                   savepath='',savelabel='',figlabel='',dpi=200,vec=None,stream=None,circle=True,\
                   fig=None,ax=None,xyunit=1.0,colorbar=True,returnim=False,stream_color='k',stream_linewidth=None,\
                   stream_arrowsize=None,vecx='velx',vecy='vely',vel_method='ave',axis=0,**kwargs):
        fig=plt.figure(dpi=dpi) if fig is None else fig
        ax = plt.axes() if ax is None else ax
        bins=int(xp.min(xp.asarray([self.Nx1,self.Nx2,self.Nx3]))) if not bins else bins
        if var in self.slices[key].keys():
            slc = self.slices[key][var]
        else:
            slc = self.get_slice(['x,y'],var,weights='vol',bins=128,where=xp.abs(self.data('z'))<self.x3max/2**zoom/self.nx3,
                     range=[[self.x1min/2**zoom,self.x1max/2**zoom],[self.x2min/2**zoom,self.x2max/2**zoom]])
        x,y = asnumpy(self.slices[key]['edges'])
        xc,yc = asnumpy(self.slices[key]['centers'])
        im_arr = asnumpy(slc)*unit
        if (vec is not None):
            u,v = self.slices[key][vecx],self.slices[key][vecy]
            ax.quiver(xc*xyunit, yc*xyunit, u, v)
        if (stream is not None):
            u,v = self.slices[key][vecx],self.slices[key][vecy]
            ax.streamplot(xc*xyunit, yc*xyunit, u, v,color=stream_color,linewidth=stream_linewidth,arrowsize=stream_arrowsize)
        fig,im=self.plot_image(x*xyunit,y*xyunit,im_arr,title=title,label=label,xlabel=xlabel,ylabel=ylabel,\
                     cmap=cmap,norm=norm,save=save,figfolder=figdir,figlabel=var,figname=savepath,fig=fig,ax=ax,returnim=True,**kwargs)
        if(circle and self.header('problem','r_in')):
            ax.add_patch(plt.Circle((0,0),float(self.header('problem','r_in')),ec='k',fc='#00000000'))
        if (title != None): ax.set_title(f"Time = {self.time}" if not title else title)
        if (colorbar):
            from mpl_toolkits.axes_grid1 import make_axes_locatable
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4%", pad=0.02)
            fig.colorbar(im,ax=ax,cax=cax, orientation='vertical',label=label)
        if (returnim):
            return fig,im
        return fig

class AthenaDataSet:
    def __init__(self,nlim=10001,version='1.0'):
        self.nlim=nlim
        self.version=version
        self.ilist=[]
        self.alist=[None]*self.nlim
        #self._config_func()
        return

    """
    def _config_func(self):
        #ad_methods = [method_name for method_name in dir(AthenaData) if callable(getattr(AthenaData, method_name)) and method_name[0]!='_']
        ad_methods = [method_name for method_name in dir(AthenaData) if method_name[0]!='_']
        for method_name in ad_methods:
            self.__dict__[method_name] = lambda *args, **kwargs: [getattr(self.alist[i], method_name)(*args, **kwargs) for i in self.ilist]
            #self.__dict__[method_name] = lambda *args, **kwargs: [self.alist[i].__dict__[method_name](*args, **kwargs) for i in self.ilist]
        return
    """

    def load_list(self,ilist,path=None,dtype=None,info=False,**kwargs):
        for i in ilist:
            if(info): print("load:",i)
            if self.alist[i] is None:
                self.alist[i]=AthenaData(num=i,version=self.version)
            self.alist[i].load(path+f".{i:05d}."+dtype,**kwargs)
            self.ilist=sorted(list(set(self.ilist + list([i]))))
        return
