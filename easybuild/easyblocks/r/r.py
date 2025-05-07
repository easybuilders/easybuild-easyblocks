##
# Copyright 2012-2025 Ghent University
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
EasyBuild support for building and installing R, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import os
import re
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import print_warning
from easybuild.tools.config import SEARCH_PATH_LIB_DIRS
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext


EXTS_FILTER_R_PACKAGES = ("R -q --no-save", "library(%(ext_name)s)")


class EB_R(ConfigureMake):
    """
    Build and install R, including list of libraries specified as extensions.
    Install specified version of libraries, install hard-coded library version
    or latest library version (in that order of preference)
    """

    def __init__(self, *args, **kwargs):
        """Constructor for R easyblock."""
        super(EB_R, self).__init__(*args, **kwargs)

        r_lib_subdirs = [os.path.join(libdir, 'R', 'lib') for libdir in SEARCH_PATH_LIB_DIRS]
        self.module_load_environment.LD_LIBRARY_PATH.extend(r_lib_subdirs)
        self.module_load_environment.LIBRARY_PATH.extend(r_lib_subdirs)

    def prepare_for_extensions(self):
        """
        We set some default configs here for R packages
        """
        # insert new packages by building them with RPackage
        self.cfg['exts_defaultclass'] = "RPackage"
        self.cfg['exts_filter'] = EXTS_FILTER_R_PACKAGES

    def configure_step(self):
        """Custom configuration for R."""

        # define $BLAS_LIBS to build R correctly against BLAS/LAPACK library
        # $LAPACK_LIBS should *not* be specified since that may lead to using generic LAPACK
        # see https://github.com/easybuilders/easybuild-easyconfigs/issues/1435
        env.setvar('BLAS_LIBS', os.getenv('LIBBLAS'))
        self.cfg.update('configopts', "--with-blas --with-lapack")

        # make sure correct config script is used for Tcl/Tk
        for dep in ['Tcl', 'Tk']:
            root = get_software_root(dep)
            if root:
                for libdir in ['lib', 'lib64']:
                    dep_config = os.path.join(root, libdir, '%sConfig.sh' % dep.lower())
                    if os.path.exists(dep_config):
                        self.cfg.update('configopts', '--with-%s-config=%s' % (dep.lower(), dep_config))
                        break

        if "--with-x=" not in self.cfg['configopts'].lower():
            if get_software_root('X11'):
                self.cfg.update('configopts', '--with-x=yes')
            else:
                self.cfg.update('configopts', '--with-x=no')

        # enable graphic capabilities for plotting, based on available dependencies
        for dep in ['Cairo', 'libjpeg-turbo', 'libpng', 'libtiff']:
            if get_software_root(dep):
                if dep == 'libjpeg-turbo':
                    conf_opt = 'jpeglib'
                else:
                    conf_opt = dep.lower()
                self.cfg.update('configopts', '--with-%s' % conf_opt)

        out = ConfigureMake.configure_step(self)

        # check output of configure command to verify BLAS/LAPACK settings
        ext_libs_regex = re.compile(r"External libraries:.*BLAS\((?P<BLAS>.*)\).*LAPACK\((?P<LAPACK>.*)\)")
        res = ext_libs_regex.search(out)
        if res:
            for lib in ['BLAS', 'LAPACK']:
                if res.group(lib) == 'generic':
                    warn_msg = "R will be built with generic %s, which will result in poor performance." % lib
                    self.log.warning(warn_msg)
                    print_warning(warn_msg)
                else:
                    self.log.info("R is configured to use non-generic %s: %s", lib, res.group(lib))
        else:
            warn_msg = "R is configured to be built without BLAS/LAPACK, which will result in (very) poor performance"
            self.log.warning(warn_msg)
            print_warning(warn_msg)

    def sanity_check_step(self):
        """Custom sanity check for R."""
        shlib_ext = get_shared_lib_ext()

        libfiles = [os.path.join('include', x) for x in ['Rconfig.h', 'Rdefines.h', 'Rembedded.h',
                                                         'R.h', 'Rinterface.h', 'Rinternals.h',
                                                         'Rmath.h', 'Rversion.h']]
        modfiles = ['internet.%s' % shlib_ext, 'lapack.%s' % shlib_ext]
        if LooseVersion(self.version) < LooseVersion('3.2'):
            modfiles.append('vfonts.%s' % shlib_ext)
        if LooseVersion(self.version) < LooseVersion('4.2'):
            libfiles += [os.path.join('include', 'S.h')]
        libfiles += [os.path.join('modules', x) for x in modfiles]
        libfiles += ['lib/libR.%s' % shlib_ext]

        custom_paths = {
            'files': ['bin/%s' % x for x in ['R', 'Rscript']] +
            [(os.path.join('lib64', 'R', f), os.path.join('lib', 'R', f)) for f in libfiles],
            'dirs': [],
        }
        super(EB_R, self).sanity_check_step(custom_paths=custom_paths)
