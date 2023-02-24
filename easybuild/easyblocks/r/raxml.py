##
# Copyright 2020-2023 Vrije Universiteit Brussel
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
EasyBuild support for building and installing RAxML, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.systemtools import get_cpu_features, HAVE_ARCHSPEC

RAXML_BINARY_NAME = "raxmlHPC"
# Supported CPU features grouped by each instruction label
RAXML_CPU_FEATURES = {
    'SSE3': ['sse3', 'see4_1', 'sse4_2'],
    'AVX': ['avx', 'avx1.0'],
    'AVX2': ['avx2'],
}
# Supported parallelization features grouped in non-MPI and MPI
RAXML_PARALLEL_FEATURES = {
    'nompi': [None, 'PTHREADS'],
    'mpi': ['MPI', 'HYBRID'],
}

class EB_RAxML(MakeCp):
    """Support for building and installing RAxML."""
    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def __init__(self, *args, **kwargs):
        """RAxML easyblock constructor, define class variables."""
        super(EB_RAxML, self).__init__(*args, **kwargs)

        def has_cpu_feature(feature):
            """
            Check if host CPU architecture has given feature
            """
            if HAVE_ARCHSPEC:
                import archspec.cpu
                host = archspec.cpu.host()
                return feature.lower() in host
            else:
                try:
                    return any(f in get_cpu_features() for f in RAXML_CPU_FEATURES[feature])
                except KeyError:
                    raise EasyBuildError("Unknown CPU feature level for RAxML: %s", feature)

        def list_filename_variants(main_features, extra_features, prefix, suffix, divider):
            """Returns list of RAxML filenames for the combination of all given features"""

            # Features are expected as lists
            if not isinstance(main_features, list):
                main_features = list(main_features)
            if not isinstance(extra_features, list):
                extra_features = list(extra_features)

            # Permutations of features
            all_features = [(mf, xf) for mf in main_features for xf in extra_features]

            # Prepend/Append prefix/suffix
            print(all_features)
            file_variants = [(prefix,) + variant + (suffix,) for variant in all_features]
            file_variants = [divider.join([segment for segment in variant if segment]) for variant in file_variants]
            print(file_variants)

            return file_variants

        # Set optimization level of RAxML for host micro-architecture
        host_cpu_features = [feat for feat in RAXML_CPU_FEATURES if has_cpu_feature(feat)]
        self.log.debug("Enabling the following CPU optimizations for RAxML: %s", ', '.join(host_cpu_features))
        # Add generic build
        host_cpu_features.append(None)

        # Set parallelization level of RAxML for current toolchain
        parallel_features = RAXML_PARALLEL_FEATURES['nompi']
        if self.toolchain.options.get('usempi', None):
            parallel_features.extend(RAXML_PARALLEL_FEATURES['mpi'])

        # List of builds to carry out
        self.target_makefiles = list_filename_variants(host_cpu_features, parallel_features, 'Makefile', 'gcc', '.')
        self.target_bins = list_filename_variants(parallel_features, host_cpu_features, RAXML_BINARY_NAME, None, '-')

    def build_step(self):
        """Build all binaries of RAxML compatible with host CPU architecture"""

        # Compiler is manually set through 'buildopts'
        compiler = os.getenv('CC')
        compiler_nompi = compiler
        if self.toolchain.options.get('usempi', None):
            compiler_nompi = os.getenv('CC_SEQ')

        # Build selected RAxML makefiles
        user_buildopts = self.cfg['buildopts']

        for mf in self.target_makefiles:
            cc_opt = compiler
            if not any(feature in mf for feature in RAXML_PARALLEL_FEATURES['mpi']):
                cc_opt = compiler_nompi
            self.cfg['buildopts'] = '-f %s CC="%s" %s' % (mf, cc_opt, user_buildopts)
            self.log.debug("Building RAxML makefile with %s: %s", cc_opt, mf)
            super(EB_RAxML, self).build_step()


    def install_step(self):
        """Copy files into installation directory"""

        self.cfg['files_to_copy'] = [
            (self.target_bins, 'bin'),
            (['README', 'manual', 'usefulScripts'], 'share'),
        ]
        super(EB_RAxML, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for RAxML."""

        custom_paths = {
            'files': [os.path.join('bin', x) for x in self.target_bins],
            'dirs': ['share/manual', 'share/usefulScripts']
        }
        super(EB_RAxML, self).sanity_check_step(custom_paths=custom_paths)
