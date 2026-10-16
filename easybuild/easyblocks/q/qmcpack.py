##
# Copyright 2026 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
"""
EasyBuild support for building and installing QMCPACK, implemented as an easyblock

The build variant (real or complex, double or mixed precision, CPU or GPU) is a set of CMake options
that also decides which binary gets installed, so the options and the sanity check derive from the same
easyconfig parameters. Options follow the QMCPACK v4.3.0 top-level CMakeLists.txt and docs/installation.rst:

- QMC_COMPLEX: parameter 'complex'; unset means on when the versionsuffix contains '-complex'
- QMC_MIXED_PRECISION: parameter 'mixed_precision'
- QMC_MPI: toolchain option usempi
- QMC_OMP: toolchain option openmp
- BUILD_AFQMC: parameter 'afqmc'; unset means on when MPI is on, the only hard requirement in the
  CMake sources (a FATAL_ERROR when BUILD_AFQMC is on and QMC_MPI is off); MKL is advisory only
- QMC_GPU: parameter 'gpu'; 'cuda', 'hip' or 'sycl' gives "openmp;<gpu>" (OpenMP offload plus the
  vendor model, see CMake/DetermineGPUFeatures.cmake); unset means 'cuda' when CUDA is a dependency.
  Since v4.3.0 CMake aborts when ENABLE_CUDA, ENABLE_OFFLOAD, ENABLE_SYCL, ENABLE_ROCM or QMC_CUDA2HIP
  are passed, so those are derived from QMC_GPU and never set here
- QMC_GPU_ARCHS: parameter 'gpu_archs'; for CUDA taken from the cuda_compute_capabilities build option or
  easyconfig parameter as sm_XX, which matches the CMAKE_CUDA_ARCHITECTURES that CMakeMake sets
- BUILD_UNIT_TESTS: on when runtest is set, since only the test step uses the unit tests

Nexus installs to <prefix>/lib/nexus (install(DIRECTORY nexus/nexus DESTINATION lib) guarded by
QMC_INSTALL_NEXUS in the top-level CMakeLists.txt), so PYTHONPATH gets <prefix>/lib.

@author: Rohit Goswami (SURF)
"""
from easybuild.easyblocks.generic.cmakeninja import CMakeNinja
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd

GPU_MODELS = ('cuda', 'hip', 'sycl')

# These two ctest tests need 12 and 16 MPI slots, more than a build node offers even oversubscribed.
TEST_EXCLUDES = ('unit_test_message-r12', 'unit_test_new_drivers_mpi-r16')

# Open MPI 5 (PRRTE) refuses to oversubscribe by default; ctest -j launches several multi-rank mpiexec at once.
TEST_ENV = 'export PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe'


def cmake_bool(value):
    """CMake spelling of a boolean."""
    return 'ON' if value else 'OFF'


class EB_QMCPACK(CMakeNinja):
    """Support for building and installing QMCPACK."""

    def __init__(self, *args, **kwargs):
        """Put the installed Nexus package on PYTHONPATH."""
        super().__init__(*args, **kwargs)
        if self._installs_nexus() and 'PYTHONPATH' not in self.cfg['modextrapaths']:
            self.module_load_environment.PYTHONPATH = ['lib']

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to QMCPACK."""
        extra_vars = CMakeNinja.extra_options(extra_vars)
        extra_vars.update({
            'complex': [None, "Build the complex (QMC_COMPLEX) version; default: True when the versionsuffix "
                        "contains '-complex', else False", CUSTOM],
            'mixed_precision': [False, "Build the mixed precision version (QMC_MIXED_PRECISION)", CUSTOM],
            'afqmc': [None, "Build AFQMC (BUILD_AFQMC); default: True when MPI is enabled, since AFQMC "
                      "requires MPI", CUSTOM],
            'gpu': [None, "GPU programming model, one of 'cuda', 'hip', 'sycl' (QMC_GPU, combined with OpenMP "
                    "offload); default: 'cuda' when CUDA is a dependency, else no GPU support", CUSTOM],
            'gpu_archs': [None, "List of GPU architectures (QMC_GPU_ARCHS), e.g. ['gfx90a']; default for "
                          "'cuda': sm_XX from cuda_compute_capabilities; required for 'hip' and 'sycl'", CUSTOM],
            'gpu_openmp_offload': [True, "Add OpenMP offload to the GPU model in QMC_GPU", CUSTOM],
        })
        return extra_vars

    def _is_complex(self):
        """Whether this is the complex build."""
        if self.cfg['complex'] is not None:
            return bool(self.cfg['complex'])
        return '-complex' in (self.cfg['versionsuffix'] or '')

    def _use_mpi(self):
        """Whether MPI is enabled through the toolchain."""
        return bool(self.toolchain.options.get('usempi', False))

    def _gpu_model(self):
        """Resolve the GPU programming model, None for a CPU-only build."""
        gpu = self.cfg['gpu']
        if gpu is None:
            return 'cuda' if get_software_root('CUDA') else None
        if gpu not in GPU_MODELS:
            raise EasyBuildError("gpu must be None or one of %s, got '%s'", ', '.join(GPU_MODELS), gpu)
        if gpu == 'cuda' and not get_software_root('CUDA'):
            raise EasyBuildError("gpu = 'cuda' requires CUDA as a dependency")
        return gpu

    def _gpu_archs(self, gpu):
        """Resolve QMC_GPU_ARCHS for the GPU model."""
        if self.cfg['gpu_archs']:
            return list(self.cfg['gpu_archs'])
        if gpu == 'cuda':
            cuda_cc = build_option('cuda_compute_capabilities') or self.cfg['cuda_compute_capabilities']
            if not cuda_cc:
                raise EasyBuildError("List of CUDA compute capabilities must be specified, either via "
                                     "cuda_compute_capabilities easyconfig parameter or via "
                                     "--cuda-compute-capabilities")
            return ['sm_%s' % cc.replace('.', '') for cc in cuda_cc]
        raise EasyBuildError("gpu = '%s' requires the gpu_archs easyconfig parameter", gpu)

    def _feature_options(self):
        """CMake options this easyblock sets, as an ordered list of (name, value)."""
        use_mpi = self._use_mpi()
        afqmc = self.cfg['afqmc']
        if afqmc is None:
            afqmc = use_mpi
        if afqmc and not use_mpi:
            raise EasyBuildError("afqmc requires MPI, enable the usempi toolchain option")

        opts = [
            ('QMC_MPI', cmake_bool(use_mpi)),
            ('QMC_OMP', cmake_bool(self.toolchain.options.get('openmp', False))),
            ('QMC_COMPLEX', cmake_bool(self._is_complex())),
            ('QMC_MIXED_PRECISION', cmake_bool(self.cfg['mixed_precision'])),
            ('BUILD_AFQMC', cmake_bool(afqmc)),
            ('BUILD_UNIT_TESTS', cmake_bool(self.cfg['runtest'])),
        ]

        gpu = self._gpu_model()
        if gpu:
            features = (['openmp'] if self.cfg['gpu_openmp_offload'] else []) + [gpu]
            opts.append(('QMC_GPU', '"%s"' % ';'.join(features)))
            opts.append(('QMC_GPU_ARCHS', self.list_to_cmake_arg(self._gpu_archs(gpu))))
        return opts

    def configure_step(self, *args, **kwargs):
        """Pass the variant options to CMake, leaving any option the easyconfig sets in configopts."""
        # the option values are needed without templating, as configopts is matched as written
        with self.cfg.disable_templating():
            configopts = self.cfg['configopts']

        enabled = []
        for opt, value in self._feature_options():
            if '-D%s=' % opt in configopts:
                self.log.info("QMCPACK: %s is set in configopts, leaving it", opt)
            else:
                self.cfg.update('configopts', '-D%s=%s' % (opt, value))
                enabled.append('%s=%s' % (opt, value))
        self.log.info("QMCPACK: CMake options set: %s", ' '.join(enabled) or 'none')
        return super().configure_step(*args, **kwargs)

    def test_step(self, *args, **kwargs):
        """Run the deterministic ctest label, with Open MPI oversubscription enabled."""
        if self.cfg['runtest'] is True:
            cmd = ' '.join([
                TEST_ENV,
                '&&',
                self.cfg['pretestopts'],
                'ctest -L deterministic -j %s --output-on-failure' % self.cfg.parallel,
                "-E '%s'" % '|'.join(TEST_EXCLUDES),
                self.cfg['testopts'],
            ])
            return run_shell_cmd(cmd).output
        return super().test_step(*args, **kwargs)

    def _installs_nexus(self):
        """Whether Nexus gets installed (QMC_INSTALL_NEXUS defaults to ON)."""
        with self.cfg.disable_templating():
            return '-DQMC_INSTALL_NEXUS=OFF' not in self.cfg['configopts']

    def sanity_check_step(self, *args, **kwargs):
        """Check the binary the variant installs, the converters, and Nexus."""
        binary = 'qmcpack_complex' if self._is_complex() else 'qmcpack'
        custom_paths = {
            'files': ['bin/%s' % binary, 'bin/convert4qmc', 'bin/ppconvert', 'bin/qmcpack.settings'],
            'dirs': ['lib/nexus'] if self._installs_nexus() else [],
        }
        custom_commands = ["%s --version 2>&1 | grep -q 'QMCPACK version'" % binary]
        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands, *args, **kwargs)
