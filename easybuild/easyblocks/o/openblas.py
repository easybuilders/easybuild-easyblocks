"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""
import os
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import POWER, get_cpu_architecture, get_shared_lib_ext


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    def configure_step(self):
        """ set up some options - but no configure command to run"""

        default_opts = {
            'BINARY': '64',
            'CC': os.getenv('CC'),
            'FC': os.getenv('FC'),
            'USE_OPENMP': '1',
            'USE_THREAD': '1',
        }
        if get_cpu_architecture() == POWER:
            # There doesn't seem to be a POWER9 option yet, but POWER8 should work.
            default_opts['TARGET'] = 'POWER8'

        for key in sorted(default_opts.keys()):
            for opts_key in ['buildopts', 'installopts']:
                if '%s=' % key not in self.cfg[opts_key]:
                    self.cfg.update(opts_key, "%s='%s'" % (key, default_opts[key]))

        self.cfg.update('installopts', 'PREFIX=%s' % self.installdir)

    def sanity_check_step(self):
        """ Custom sanity check for OpenBLAS """
        custom_paths = {
            'files': ['include/cblas.h', 'include/f77blas.h', 'include/lapacke_config.h', 'include/lapacke.h',
                      'include/lapacke_mangling.h', 'include/lapacke_utils.h', 'include/openblas_config.h',
                      'lib/libopenblas.a', 'lib/libopenblas.%s' % get_shared_lib_ext()],
            'dirs': [],
        }
        super(EB_OpenBLAS, self).sanity_check_step(custom_paths=custom_paths)
