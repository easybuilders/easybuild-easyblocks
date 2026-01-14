"""
EasyBuild support for building and installing AOCL-LAPACK, implemented as an easyblock

@author: Bart Oldeman (McGill University, Calcul Quebec, Digital Research Alliance Canada)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Jasper Grimm (University of York)
@author: Kenneth Hoste (Ghent University)
"""
import os
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.openblas import EB_OpenBLAS
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions, read_file
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_AOCL_minus_LAPACK(CMakeMake):
    """Support for building/installing AOCL-LAPACK."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for OpenBLAS easyblock."""
        extra_vars = {
            'max_failing_lapack_tests_num_errors': [0, "Maximum number of LAPACK tests failing "
                                                    "due to numerical errors", CUSTOM],
            'max_failing_lapack_tests_other_errors': [0, "Maximum number of LAPACK tests failing "
                                                      "due to non-numerical errors", CUSTOM],
            'run_lapack_tests': [False, "Run LAPACK tests during test step, "
                                        "and check whether failing tests exceeds threshold", CUSTOM],
            'run_long_tests': [False, "Run medium and long (> 1 hour total) tests during test step", CUSTOM],
        }

        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration for AOCL-LAPACK"""

        # For simplicity, always build the tests
        # -DENABLE_AMD_FLAGS=ON recommended in documentation
        # -DENABLE_AOCL_BLAS=ON tightly couples with AOCL-BLAS for optimizations
        # -DLF_ISA_CONFIG=NONE and patching out let EasyBuild CFLAGS override AOCL-LAPACK's
        # default of -mtune=native -O3 -mavx<depending on arch>*
        configopts = {
            'BUILD_TEST': 'ON',
            'BUILD_LEGACY_TEST': 'ON',
            'BUILD_NETLIB_TEST': 'ON',
            'ENABLE_AMD_FLAGS': 'ON',
            'ENABLE_AOCL_BLAS': 'ON',
            'LF_ISA_CONFIG': 'NONE',
        }
        apply_regex_substitutions('CMakeLists.txt', [('-mtune=native -O3', '')])

        # only add configure options to configopts easyconfig parameter if they're not defined yet,
        # to allow easyconfig to override specifies settings
        for key, value in sorted(configopts.items()):
            opt = '-D%s=' % key
            if opt not in self.cfg['configopts']:
                self.cfg.update('configopts', opt + "'%s'" % value)

        super().configure_step()

    def test_step(self):
        """Adapt ctest parameters depending on run_lapack_tests/run_long_tests"""
        if self.cfg.get('runtest') is True and not self.cfg.get('test_cmd'):
            self.cfg.update('pretestopts', ' LD_LIBRARY_PATH=%(installdir)s/lib:$LD_LIBRARY_PATH ')
            if not (self.cfg['run_lapack_tests'] and self.cfg['run_long_tests']) and '-E' not in self.cfg['testopts']:
                skip = []
                if not self.cfg['run_lapack_tests']:
                    skip += ['netlib']
                if not self.cfg['run_long_tests']:
                    skip += ['medium', 'long']
                skip = '|'.join(skip)
                self.cfg.update('testopts', f'-E "({skip})"')

        super().test_step()

        # check number of failing LAPACK tests more closely
        if self.cfg['run_lapack_tests']:
            logfile = os.path.join(self.separate_build_dir, 'Testing/Temporary/LastTest.log')
            EB_OpenBLAS.check_lapack_test_results(self, read_file(logfile))

    def sanity_check_step(self):
        """ Custom sanity check for AOCL-LAPACK """
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['include/lapack.h', 'include/FLAME.h',
                      'include/lapacke.h', 'include/lapacke_mangling.h',
                      f'lib/libflame.{shlib_ext}'],
            'dirs': [],
        }
        super().sanity_check_step(custom_paths=custom_paths)
