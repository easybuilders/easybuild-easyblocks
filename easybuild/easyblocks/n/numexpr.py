##
# Copyright 2019-2025 Ghent University
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
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.filetools import write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.systemtools import get_cpu_features


class EB_numexpr(PythonPackage):
    """Support for building/installing numexpr."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for numexpr."""
        super(EB_numexpr, self).__init__(*args, **kwargs)

        self.imkl_root = None

    def configure_step(self):
        """Custom configuration procedure for numexpr."""
        super(EB_numexpr, self).configure_step()

        self.imkl_root = get_software_root('imkl')

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

            mkl_ver = get_software_version('imkl')

            if LooseVersion(mkl_ver) >= LooseVersion('2021'):
                mkl_lib_dirs = [
                    os.path.join(self.imkl_root, 'mkl', 'latest', 'lib', 'intel64'),
                ]
                mkl_include_dirs = os.path.join(self.imkl_root, 'mkl', 'latest', 'include')
                mkl_libs = ['mkl_rt']
            else:
                mkl_lib_dirs = [
                    os.path.join(self.imkl_root, 'mkl', 'lib', 'intel64'),
                    os.path.join(self.imkl_root, 'lib', 'intel64'),
                ]
                mkl_include_dirs = os.path.join(self.imkl_root, 'mkl', 'include')
                mkl_libs = ['mkl_intel_lp64', 'mkl_intel_thread', 'mkl_core', 'mkl_def', mkl_vml_lib, 'iomp5']

            site_cfg_lines = [
                "[mkl]",
                "include_dirs = %s" % mkl_include_dirs,
                "library_dirs = %s" % os.pathsep.join(mkl_lib_dirs + self.toolchain.get_variable('LDFLAGS', typ=list)),
            ]

            if LooseVersion(self.version) >= LooseVersion("2.8.0"):
                site_cfg_lines.append("libraries = %s" % os.pathsep.join(mkl_libs))
            else:
                site_cfg_lines.append("mkl_libs = %s" % ', '.join(mkl_libs))

            site_cfg_txt = '\n'.join(site_cfg_lines)
            write_file('site.cfg', site_cfg_txt)
            self.log.info("site.cfg used for numexpr:\n" + site_cfg_txt)

    def sanity_check_step(self):
        """Custom sanity check for numexpr."""

        custom_commands = []

        # imkl_root may still be None, for example when running with --sanity-check-only
        if self.imkl_root is None:
            self.imkl_root = get_software_root('imkl')

        # if Intel MKL is available, make sure VML is used
        if self.imkl_root:
            custom_commands.append("python -s -c 'import numexpr; assert(numexpr.use_vml)'")

            # for sufficiently recent versions of numexpr, also do a more extensive check for VML support
            if LooseVersion(self.version) >= LooseVersion('2.7.3'):
                custom_commands.append("""python -s -c "import numexpr; numexpr.set_vml_accuracy_mode('low')" """)

        return super(EB_numexpr, self).sanity_check_step(custom_commands=custom_commands)
