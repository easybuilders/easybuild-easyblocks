##
# Copyright 2019-2019 Ghent University
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
EasyBuild support for building and installing numexpr, implemented as an easyblock
"""
import os

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.filetools import write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_cpu_features


class EB_numexpr(PythonPackage):
    """Support for building/installing numexpr."""

    @staticmethod
    def extra_options():
        """Override some custom easyconfig parameters specifically for numexpr."""
        extra_vars = PythonPackage.extra_options()

        extra_vars['download_dep_fail'][0] = True
        extra_vars['use_pip'][0] = True

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for numexpr."""
        super(EB_numexpr, self).__init__(*args, **kwargs)

        self.imkl_root = None

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for building and installing numexpr."""
        super(EB_numexpr, self).prepare_step(*args, **kwargs)

        self.imkl_root = get_software_root('imkl')

    def configure_step(self):
        """Custom configuration procedure for numexpr."""
        super(EB_numexpr, self).configure_step()

        # if Intel MKL is available, set up site.cfg such that the right VML library is used;
        # this makes a *big* difference in terms of performance;
        # see also https://github.com/pydata/numexpr/blob/master/site.cfg.example
        if self.imkl_root:

            # figure out which VML library to link to
            cpu_features = get_cpu_features()
            if 'avx512f' in cpu_features:
                mkl_vml_lib = 'mkl_vml_avx512'
            elif 'avx2' in cpu_features:
                mkl_vml_lib = 'mkl_vml_avx2'
            elif 'avx' in cpu_features:
                mkl_vml_lib = 'mkl_vml_avx'
            else:
                # use default kernels as fallback for non-AVX systems
                mkl_vml_lib = 'mkl_vml_def'

            mkl_libs = ['mkl_intel_lp64', 'mkl_intel_thread', 'mkl_core', 'mkl_def', mkl_vml_lib, 'mkl_rt', 'iomp5']

            mkl_lib_dirs = [
                os.path.join(self.imkl_root, 'mkl', 'lib', 'intel64'),
                os.path.join(self.imkl_root, 'lib', 'intel64'),
            ]

            site_cfg_txt = '\n'.join([
                "[mkl]",
                "include_dirs = %s" % os.path.join(self.imkl_root, 'mkl', 'include'),
                "library_dirs = %s" % ':'.join(mkl_lib_dirs),
                "mkl_libs = %s" % ', '.join(mkl_libs),
            ])
            write_file('site.cfg', site_cfg_txt)

    def sanity_check_step(self):
        """Custom sanity check for numexpr."""

        custom_commands = []

        # if Intel MKL is available, make sure VML is used
        if self.imkl_root:
            custom_commands.append("python -c 'import numexpr; assert(numexpr.use_vml)'")

        super(EB_numexpr, self).sanity_check_step(custom_commands=custom_commands)
