##
# Copyright 2009-2020 Ghent University
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
from easybuild.tools.systemtools import get_cpu_features


class EB_RAxML(MakeCp):
    """Support for building and installing RAxML."""
    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def __init__(self, *args, **kwargs):
        """RAxML easyblock constructor, define class variables."""
        super(EB_RAxML, self).__init__(*args, **kwargs)

        # Set optmization of RAxML build for host micro-architecture
        cpuopt_label = {
            'sse3': 'SSE3',
            'sse4_1': 'SSE3',
            'sse4_2': 'SSE3',
            'avx': 'AVX',
            'avx1.0': 'AVX',  # on macOS, AVX is indicated with 'avx1.0' rather than 'avx'
            'avx2': 'AVX2',
        }
        cpu_features = set([label for feat, label in cpuopt_label.items() if feat in get_cpu_features()])
        self.log.debug("Enabling the following CPU optimizations for RAxML: %s", ', '.join(cpu_features))
        cpu_features.update([None])  # add generic build

        # Build features supported by RAxML, grouped in non-MPI and MPI
        build_labels = {
            'nompi': [None, 'PTHREADS'],
            'mpi': ['MPI', 'HYBRID'],
        }

        # List of Makefiles in the build
        makefile = ('Makefile', 'gcc', '.')
        # Always build non-MPI variants
        self.target_makefiles = {
            'nompi': self.make_filename_variants(cpu_features, build_labels['nompi'], *makefile),
        }
        if self.toolchain.options.get('usempi', None):
            # Add MPI variants in their own group
            self.target_makefiles.update({
                'mpi': self.make_filename_variants(cpu_features, build_labels['mpi'], *makefile),
            })

        # List of binaries in the installation
        binary = ('raxmlHPC', None, '-')
        self.target_bin = self.make_filename_variants(build_labels['nompi'], cpu_features,  *binary)
        if 'mpi' in self.target_makefiles:
            self.target_bin.extend(self.make_filename_variants(build_labels['mpi'], cpu_features, *binary))

    def make_filename_variants(self, main_feature, extra_feature, prefix, suffix, divider):
        """Returns list of RAxML filenames for the combination of all given features"""

        # Features are expected as lists
        if not isinstance(main_feature, list):
            main_feature = list(main_feature)
        if not isinstance(extra_feature, list):
            extra_feature = list(extra_feature)

        # Permutations of features
        if extra_feature:
            raxml_variants = [(mf, xf) for mf in main_feature for xf in extra_feature]
        else:
            raxml_variants = main_feature

        # Prepend/Append prefix/suffix
        for n, variant in enumerate(raxml_variants):
            full_filename = (prefix,) + variant + (suffix,)
            full_filename = tuple(filter(None, full_filename))  # avoid doubling the divider
            raxml_variants[n] = divider.join(full_filename)

        return raxml_variants

    def configure_step(self):
        """No custom configuration step for RAxML"""
        pass

    def build_step(self):
        """Build all binaries of RAxML compatible with host CPU architecture"""

        # Compiler is manually set through 'buildopts'
        cc = os.getenv('CC')
        # Always use non-MPI compiler for non-MPI Makefiles
        if 'mpi' in self.target_makefiles:
            cc_seq = os.getenv('CC_SEQ')
        else:
            cc_seq = os.getenv('CC')

        # Build selected RAxML makefiles
        user_buildopts = self.cfg['buildopts']

        self.log.debug("Building makefiles of RAxML with %s: %s", cc_seq, ', '.join(self.target_makefiles['nompi']))
        for mf in self.target_makefiles['nompi']:
            self.cfg['buildopts'] = '-f %s CC="%s" %s' % (mf, cc_seq, user_buildopts)
            super(EB_RAxML, self).build_step()

        if 'mpi' in self.target_makefiles:
            self.log.debug("Building makefiles of RAxML with %s: %s", cc, ', '.join(self.target_makefiles['mpi']))
            for mf in self.target_makefiles['mpi']:
                self.cfg['buildopts'] = '-f %s CC="%s" %s' % (mf, cc, user_buildopts)
                super(EB_RAxML, self).build_step()

    def install_step(self):
        """Copy files into installation directory"""

        self.cfg['files_to_copy'] = [
            (self.target_bin, 'bin'),
            (['README', 'manual', 'usefulScripts'], 'share'),
        ]
        super(EB_RAxML, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for RAxML."""

        custom_paths = {
            'files': [os.path.join('bin', x) for x in self.target_bin],
            'dirs': ['share/manual', 'share/usefulScripts']
        }
        super(EB_RAxML, self).sanity_check_step(custom_paths=custom_paths)
