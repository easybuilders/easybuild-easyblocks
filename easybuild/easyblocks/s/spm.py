# EasyBlock for SPM:
# ----------------------------------------------------------------------------
#   Copyright: 2014 - Medical University of Vienna
#   License: MIT
#   Authors: Georg Rath <georg.rath@meduniwien.ac.at>
# ----------------------------------------------------------------------------
"""
EasyBuild support for SPM, implemented as an easyblock

@authors: Georg Rath (Medical University of Vienna)
"""

import os
import shutil
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.filetools import run_cmd,which

class EB_SPM(ConfigureMake):
    """Support for building and installing SPM."""
    
    source_files = [
        'spm_add', 'spm_bias_mex', 'spm_brainwarp', 'spm_bsplinc', 'spm_bsplins',
        'spm_bwlabel', 'spm_conv_vol', 'spm_dilate_erode', 'spm_existfile', 'spm_gamrnd',
        'spm_get_lm', 'spm_global', 'spm_hist2', 'spm_hist', 'spm_invdef', 'spm_krutil',
        'spm_project', 'spm_render_vol', 'spm_resels_vol', 'spm_sample_vol', 'spm_slice_vol',
        'spm_unlink', 'spm_voronoi', '@file_array/private/file2mat', '@file_array/private/mat2file',
    ]  # these should be moved to the easyconfig, because they probably change between versions
    all_mex_suffixes = [ 'mexa64', 'mexglx', 'mexw32', 'mexw64', 'mexmaci64', 'mexmaci' ]
    compiled_mex_suffix = 'mexa64'

    def __init__(self,*args,**kwargs):
        """Specify building in install dir, initialize custom variables."""
        super(EB_SPM, self).__init__(*args, **kwargs)
        self.build_in_installdir = True
    
        # MATLAB (mcc) warns if GCC version is not 4.4.x, but it still seems to work
        deps = ['GCC', 'MATLAB']
        for dep in deps:
            if not get_software_root(dep):
                self.log.error("%s module not loaded" % dep)
        
        if which('mcc') is None:
            self.log.error('mcc not found')

    def extract_step(self):
        super(EB_SPM, self).extract_step()
        
        # there is no --strip-components for unzip...
        for files in os.listdir(self.src[0]['finalpath']):
            shutil.move(files, self.builddir)
        shutil.rmtree(self.src[0]['finalpath'])
        self.src[0]['finalpath'] = self.builddir    
        self.cfg['start_dir'] = os.path.join(self.builddir, "src")

    def prepare_step(self):
        super(EB_SPM, self).prepare_step() 
        for source_file in self.source_files:
            for suffix in self.all_mex_suffixes:
                os.remove(os.path.join(self.builddir, source_file + '.' + suffix))

    def configure_step(self):
        """No configure step for SPM."""
        pass

    def build_step(self):
        """Build is done in install step"""
        pass

    def install_step(self):
        """The actual build is done here"""
        super(EB_SPM, self).install_step()

    def cleanup_step(self):
        super(EB_SPM, self).cleanup_step()
        shutil.rmtree(os.path.join(self.builddir, 'src'))

    def sanity_check_step(self):
        """Custom sanity check for SPM."""

        custom_paths = {
            'files': [ source_file + '.' + self.compiled_mex_suffix for source_file in self.source_files ],
            'dirs': [],
        }
        super(EB_SPM, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for SPM."""
        txt = super(EB_SPM, self).make_module_extra()
        txt += self.moduleGenerator.prepend_paths("MATLABPATH", "")
        return txt
    
