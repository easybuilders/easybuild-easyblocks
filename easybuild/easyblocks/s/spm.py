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
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.filetools import run_cmd,which

class EB_SPM(ConfigureMake):
    """Support for building and installing SPM."""
    
    all_mex_suffixes = [ 'mexa64', 'mexglx', 'mexw32', 'mexw64', 'mexmaci64', 'mexmaci' ]
    compiled_mex_suffix = 'mexa64'

    def __init__(self,*args,**kwargs):
        """Specify building in install dir, initialize custom variables."""
        super(EB_SPM, self).__init__(*args, **kwargs)
        self.build_in_installdir = True

    @staticmethod
    def extra_options():
        extra_vars = [
                      ('mexfiles', [None, "Specify the mex files that get compiled in the install step (without file extension)." \
                                          "This is used for cleaning out obsolete files and sanity checking.", MANDATORY])
                     ]
        return ConfigureMake.extra_options(extra_vars)

    def extract_step(self):
        """Extract SPM and move it one level up"""
        super(EB_SPM, self).extract_step()
        
        # there is no --strip-components for unzip...
        for files in os.listdir(self.src[0]['finalpath']):
            shutil.move(files, self.builddir)
        shutil.rmtree(self.src[0]['finalpath'])
        self.src[0]['finalpath'] = self.builddir    
        self.cfg['start_dir'] = os.path.join(self.builddir, "src")

    def prepare_step(self):
        """Clean out the shipped mex files."""
        super(EB_SPM, self).prepare_step()
        source_files = self.cfg['mexfiles'] 
        for source_file in source_files:
            for suffix in self.all_mex_suffixes:
                os.remove(os.path.join(self.builddir, source_file + '.' + suffix))

    def configure_step(self):
        """Check for loaded dependencies"""
        # MATLAB (mcc) warns if GCC version is not 4.4.x, but it still works
        deps = [ 'GCC', 'MATLAB' ]
        for dep in deps:
            if not get_software_root(dep):
                self.log.error("%s module not loaded" % dep)

        matlab_compilers = [ 'mcc', 'mex' ]
        for compiler in matlab_compilers:
            if which(compiler) is None:
                self.log.error('%s not found' % compiler)

    def build_step(self):
        """Build is done in install step"""
        pass

    def install_step(self):
        """The actual build is done here"""
        super(EB_SPM, self).install_step()

    def cleanup_step(self):
        """Remove (now obsolete) src dir"""
        super(EB_SPM, self).cleanup_step()
        shutil.rmtree(os.path.join(self.builddir, 'src'))

    def sanity_check_step(self):
        """Custom sanity check for SPM."""
        
        source_files = self.cfg['mexfiles']
        custom_paths = {
            'files': [ source_file + '.' + self.compiled_mex_suffix for source_file in source_files ],
            'dirs': [],
        }
        super(EB_SPM, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for SPM."""
        txt = super(EB_SPM, self).make_module_extra()
        txt += self.moduleGenerator.prepend_paths("MATLABPATH", "")
        return txt
    
