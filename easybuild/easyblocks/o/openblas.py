"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""
import os
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import POWER, get_cpu_architecture, get_shared_lib_ext


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    def build_step(self):
        """Custom build procedure for OpenBLAS."""

        self.cfg['buildopts'] += 'BINARY=64 USE_THREAD=1 USE_OPENMP=1 CC="%s" FC="%s"' % (
            os.environ['CC'], os.environ['FC'])

        if get_cpu_architecture() == POWER:
            # There doesn't seem to be a POWER9 option yet, but POWER8 should work.
            self.cfg['buildopts'] += ' TARGET=POWER8'

        super(EB_OpenBLAS, self).build_step()

    def install_step(self):
        """Custom install procedure for OpenBLAS."""
        self.cfg['installopts'] += 'USE_THREAD=1 USE_OPENMP=1 PREFIX=%s' % self.installdir
        super(EB_OpenBLAS, self).install_step()

    def configure_step(self):
        """ nothing to do for OpenBLAS """
        pass

    def sanity_check_step(self):
        """ Custom sanity check for OpenBLAS """
        custom_paths = {
            'files': ['include/cblas.h', 'include/f77blas.h', 'include/lapacke_config.h', 'include/lapacke.h',
                      'include/lapacke_mangling.h', 'include/lapacke_utils.h', 'include/openblas_config.h',
                      'lib/libopenblas.a', 'lib/libopenblas.%s' % get_shared_lib_ext()],

            'dirs': [],
        }
        super(EB_OpenBLAS, self).sanity_check_step(custom_paths=custom_paths)
