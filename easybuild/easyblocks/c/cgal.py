##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for CGAL, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
"""
import os

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_CGAL(CMakeMake):
    """Support for building CGAL."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def configure_step(self):
        """Set some extra environment variables before configuring."""

        deps = ['Boost', 'GMP', 'MPFR']
        for dep in deps:
            if not get_software_root(dep):
                raise EasyBuildError('Dependency module %s not loaded?', dep)

        for lib in ['GMP', 'MPFR']:
            os.environ['%s_INC_DIR' % lib] = os.path.join(get_software_root(lib), 'include')
            os.environ['%s_LIB_DIR' % lib] = os.path.join(get_software_root(lib), 'lib')

        os.environ['BOOST_ROOT'] = get_software_root('Boost')

        super(EB_CGAL, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for CGAL."""

        shlib_ext = get_shared_lib_ext()
        libs = [os.path.join('lib64', 'libCGAL%s.%s' % (suffix, shlib_ext)) for suffix in ['', '_Core']]
        dirs = [os.path.join('include', 'CGAL')]
        if LooseVersion(self.version) >= LooseVersion('4.12'):
            dirs.append(os.path.join('lib64', 'cmake', 'CGAL'))
        else:
            dirs.append(os.path.join('lib64', 'CGAL'))
        custom_paths = {
            'files': [os.path.join('bin', 'cgal_%s') % x for x in ['create_cmake_script', 'make_macosx_app']] + libs,
            'dirs': dirs,
        }
        super(EB_CGAL, self).sanity_check_step(custom_paths=custom_paths)
