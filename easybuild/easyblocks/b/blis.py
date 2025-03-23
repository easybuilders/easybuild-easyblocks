"""
Easybuild support for building and installing BLIS, implemented as an easyblock

@author: Pua Cheng Xuan Frederick (National University of Singapore)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.systemtools import get_cpu_arch_name


class EB_BLIS(ConfigureMake):
    """Custom easyblock for BLIS"""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for BLIS easyblock."""
        extra_vars = {
            'enable_cblas': [True, "Enable CBLAS", CUSTOM],
            'enable_shared': [True, "Enable builing shared library", CUSTOM],
            'multi_threading_type': ["openmp", "Type of multithreading to use", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configure step for BLIS."""
        if self.cfg['cblas_enable']:
            self.cfg.update('configopts', '--enable-cblas')

        if self.cfg['shared_enable']:
            self.cfg.update('configopts', '--enable-shared')

        # arch_name will only be available when archspec is available to easybuild, else arch_name will be unknown
        arch_name = get_cpu_arch_name()
        if arch_name == "a64fx":
            self.cfg.update('configopts', 'CFLAGS="$CFLAGS -DCACHE_SECTOR_SIZE_READONLY"')

        self.cfg.update('configopts', '--enable-threading=%s CC="$CC" auto' % self.cfg['multi_threading_type'])

        super(EB_BLIS, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for BLIS"""
        shlib_ext = get_shared_lib_ext()

        custom_paths = {
            'files': ['include/blis/cblas.h', 'include/blis/blis.h',
                      'lib/libblis.a', 'lib/libblis.%s' % shlib_ext],
            'dirs': [],
        }
        return super(EB_BLIS, self).sanity_check_step(custom_paths=custom_paths)
