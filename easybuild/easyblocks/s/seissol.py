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
##
"""
EasyBuild support for building and installing SeisSol, implemented as an easyblock

SeisSol's HOST_ARCH is an input to its matrix-kernel code generators (PSpaMM,
libxsmm): it fixes the alignment and the vector width of the generated kernels,
so it has to match the CPU the installation targets rather than be left at the
portable default. A set --optarch decides it first, then the EESSI CPU target,
and only then the CPU of the machine running eb. The same value names the installed
binary, which is why the sanity check is derived here rather than written into
the easyconfig.

@author: Rohit Goswami (SURF)
"""
import os
import re

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import AARCH64, AMD, INTEL, X86_64
from easybuild.tools.systemtools import get_cpu_arch_name, get_cpu_architecture, get_cpu_family
from easybuild.tools.systemtools import get_cpu_features
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

# archspec microarchitecture name -> SeisSol HOST_ARCH (cmake/process_users_input.cmake)
ARCHSPEC_TO_HOST_ARCH = {
    'haswell': 'hsw',
    'broadwell': 'hsw',
    'skylake': 'hsw',
    'skylake_avx512': 'skx',
    'cascadelake': 'skx',
    'icelake': 'skx',
    'sapphirerapids': 'skx',
    'zen': 'naples',
    'zen2': 'rome',
    'zen3': 'milan',
    'zen4': 'bergamo',
    'zen5': 'bergamo',
    'neoverse_n1': 'neon',
    'neoverse_v1': 'sve256',
    'neoverse_v2': 'sve128',
    'a64fx': 'a64fx',
    'thunderx2': 'thunderx2t99',
    'm1': 'apple-m1',
    'm2': 'apple-m2',
}

# compiler -march/-mcpu names that differ from the archspec name
COMPILER_TO_ARCHSPEC = {
    'icelake_client': 'icelake',
    'icelake_server': 'icelake',
    'znver1': 'zen',
    'znver2': 'zen2',
    'znver3': 'zen3',
    'znver4': 'zen4',
    'znver5': 'zen5',
    'thunderx2t99': 'thunderx2',
}

# x86-64 micro-architecture levels -> SeisSol HOST_ARCH
X86_64_LEVEL_TO_HOST_ARCH = {
    'x86_64': 'noarch',
    'x86_64_v2': 'noarch',
    'x86_64_v3': 'hsw',
    'x86_64_v4': 'skx',
}

# Graph partitioning libraries SeisSol can compile in, keyed by EasyBuild name.
# SeisSol's runtime parameter partitioninglib selects one; Default takes the
# first compiled in, in the order parmetis, ptscotch, parhip.
PARTITIONERS = [
    ('ParMETIS', 'parmetis'),
    ('SCOTCH', 'ptscotch'),
    ('KaHIP', 'parhip'),
]


def det_target_host_arch(arch, optarch=None, cpu_target=None):
    """
    Determine SeisSol's HOST_ARCH from what the installation targets, not from the build host.

    :param arch: CPU architecture constant (X86_64 or AARCH64)
    :param optarch: --optarch value for the compiler in use, if set
    :param cpu_target: EESSI CPU target such as 'x86_64/amd/zen4', if set
    :return: HOST_ARCH value, or None when neither input decides it (or optarch asks for the native CPU)
    """
    portable = 'noarch' if arch == X86_64 else 'neon'

    if optarch:
        if optarch == OPTARCH_GENERIC:
            return portable
        match = re.search(r'(?:^|\s)-?m(?:arch|cpu)=([^\s+]+)', optarch)
        if match is None:
            raise EasyBuildError("SeisSol: cannot derive HOST_ARCH from optarch '%s'; set host_arch", optarch)
        name = match.group(1).lower().replace('-', '_')
        if name == 'native':
            return None
        if name in X86_64_LEVEL_TO_HOST_ARCH:
            return X86_64_LEVEL_TO_HOST_ARCH[name]
        name = COMPILER_TO_ARCHSPEC.get(name, name)
        if name in ARCHSPEC_TO_HOST_ARCH:
            return ARCHSPEC_TO_HOST_ARCH[name]
        raise EasyBuildError("SeisSol: no HOST_ARCH known for optarch '%s'; set host_arch", optarch)

    if cpu_target:
        name = cpu_target.rstrip('/').split('/')[-1]
        if name == 'generic':
            return portable
        if name in ARCHSPEC_TO_HOST_ARCH:
            return ARCHSPEC_TO_HOST_ARCH[name]
        raise EasyBuildError("SeisSol: no HOST_ARCH known for CPU target '%s'; set host_arch", cpu_target)

    return None


class EB_SeisSol(CMakeMake):
    """Support for building and installing SeisSol."""

    @staticmethod
    def extra_options():
        """Extra easyconfig parameters specific to SeisSol."""
        extra_vars = {
            'host_arch': ['auto', "SeisSol HOST_ARCH, or 'auto' to derive it from --optarch, "
                          "the EESSI CPU target, or else the local CPU", CUSTOM],
            'order': [6, "Convergence order (ORDER)", CUSTOM],
            'equations': ['elastic', "Equation set (EQUATIONS)", CUSTOM],
            'precision': ['double', "Floating-point precision: 'double' or 'single' (PRECISION)", CUSTOM],
            'gemm_tools': [None, "GEMM_TOOLS_LIST; default: LIBXSMM,PSpaMM when libxsmm is a dependency, "
                           "PSpaMM when only PSpaMM is, else 'auto'", CUSTOM],
            'partitioners': ['auto', "GRAPH_PARTITIONING_LIBS as a list, or 'auto' for every one "
                             "present among the dependencies", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.host_arch = None

    def _host_arch(self):
        """Resolve HOST_ARCH for this build."""
        if self.cfg['host_arch'] != 'auto':
            return self.cfg['host_arch']

        arch = get_cpu_architecture()
        optarch = build_option('optarch')
        if isinstance(optarch, dict):
            optarch = optarch.get(self.toolchain.COMPILER_FAMILY)
        target_host_arch = det_target_host_arch(arch, optarch=optarch,
                                                cpu_target=os.getenv('EESSI_SOFTWARE_SUBDIR'))
        if target_host_arch:
            return target_host_arch

        name = get_cpu_arch_name()
        if name in ARCHSPEC_TO_HOST_ARCH:
            return ARCHSPEC_TO_HOST_ARCH[name]

        # Without archspec, decide from CPU features: the only thing HOST_ARCH
        # varies is the vector width, and the features say what is available.
        features = get_cpu_features()
        if arch == X86_64:
            family = get_cpu_family()
            avx512, avx2 = 'avx512f' in features, 'avx2' in features
            if family == INTEL:
                return 'skx' if avx512 else ('hsw' if avx2 else 'noarch')
            if family == AMD:
                return 'bergamo' if avx512 else ('rome' if avx2 else 'noarch')
        elif arch == AARCH64:
            return 'neon'

        print_warning("SeisSol: CPU '%s' not recognised, building with HOST_ARCH=noarch" % name)
        return 'noarch'

    def _partitioners(self):
        """Resolve GRAPH_PARTITIONING_LIBS."""
        value = self.cfg['partitioners']
        if value != 'auto':
            return list(value)
        found = [lib for (dep, lib) in PARTITIONERS if get_software_root(dep)]
        if not found:
            print_warning("SeisSol: no graph partitioning library among the dependencies; "
                          "multi-rank runs will partition poorly")
        return found

    def _gemm_tools(self):
        """Resolve GEMM_TOOLS_LIST.

        SeisSol's own 'auto' adds LIBXSMM_JIT whenever libxsmm and a BLAS are found,
        so name the generators explicitly when the dependencies say which ones exist.
        The offline libxsmm generator only supports x86_64.
        """
        if self.cfg['gemm_tools']:
            return self.cfg['gemm_tools']
        has_libxsmm = get_software_root('libxsmm') and get_cpu_architecture() == X86_64
        has_pspamm = get_software_root('PSpaMM')
        if has_libxsmm and has_pspamm:
            return 'LIBXSMM,PSpaMM'
        if has_pspamm:
            return 'PSpaMM'
        return 'auto'

    def configure_step(self, *args, **kwargs):
        """Pass the resolved build options to CMake."""
        for opt in ('HOST_ARCH', 'ORDER', 'EQUATIONS', 'PRECISION', 'GEMM_TOOLS_LIST',
                    'GRAPH_PARTITIONING_LIBS'):
            if '-D%s=' % opt in self.cfg['configopts']:
                raise EasyBuildError("Set %s through its easyconfig parameter, not configopts", opt)

        if self.cfg['precision'] not in ('double', 'single'):
            raise EasyBuildError("precision must be 'double' or 'single', got '%s'", self.cfg['precision'])

        self.host_arch = self._host_arch()
        partitioners = self._partitioners()
        self.log.info("SeisSol: HOST_ARCH=%s, partitioners=%s", self.host_arch, partitioners)

        opts = [
            '-DHOST_ARCH=%s' % self.host_arch,
            '-DORDER=%s' % self.cfg['order'],
            '-DEQUATIONS=%s' % self.cfg['equations'],
            '-DPRECISION=%s' % self.cfg['precision'],
            '-DGEMM_TOOLS_LIST=%s' % self._gemm_tools(),
            '-DGRAPH_PARTITIONING_LIBS="%s"' % ';'.join(partitioners),
        ]
        self.cfg.update('configopts', ' '.join(opts))
        return super().configure_step(*args, **kwargs)

    def _binary(self):
        """Installed binary: SeisSol_<build type>_<precision letter><host arch>_<order>_<equations>."""
        host_arch = self.host_arch or self._host_arch()
        letter = 'd' if self.cfg['precision'] == 'double' else 's'
        return 'SeisSol_%s_%s%s_%s_%s' % (self.build_type, letter, host_arch, self.cfg['order'], self.cfg['equations'])

    def sanity_check_step(self, *args, **kwargs):
        """Check the solver and proxy binaries the resolved options name."""
        binary = self._binary()
        proxy = binary.replace('SeisSol_', 'SeisSol_proxy_', 1)
        custom_paths = {
            'files': ['bin/%s' % binary, 'bin/%s' % proxy],
            'dirs': [],
        }
        custom_commands = ['%s --help | grep "Show this help message"' % binary]
        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands, *args, **kwargs)
