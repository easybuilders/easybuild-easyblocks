##
# Copyright 2014-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for Moses, implemented as an easyblock

@author: Ewan Higgs (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.filetools import write_file
from easybuild.tools.run import run_cmd


class EB_Moses(EasyBlock):
    """Support for building and installing Moses."""

    def configure_step(self):
        """No configure step for Moses."""
        pass

    def build_step(self):
        """No build step for Moses."""
        pass

    def install_step(self):
        """Install Moses using bjam script."""
        # put user-config.jam configuration file in place to point to location of MPI C++ compiler wrapper
        write_file('user-config.jam', "using mpi : %s ;\nusing intel-linux : : %s " % (os.getenv('MPICXX'), os.getenv('CXX')))

        cmd_opts = [
            '--user-config=%s' % os.path.join(os.getcwd(), 'user-config.jam'),
            '--prefix=%s' % self.installdir,
            '--includedir',
            '--install-scripts',
            '--debug-configuration',
        ]

        if self.toolchain.comp_family() == toolchain.INTELCOMP:
            toolset = 'intel-linux'
        elif self.toolchain.comp_family() == toolchain.GCC:
            toolset = 'gcc'
        else:
            raise EasyBuildError("Unknown compiler used, don't know what to specify to --with-toolset, aborting.")

        boost = get_software_root('Boost')
        if boost:
            cmd_opts.append('--with-boost=%s' % boost)
        else:
            raise EasyBuildError("Required dependency Boost is missing")

        #if self.toolchain.mpi_family() is not None:
        #    cmd_opts.append('--enable-mpi')

        cmd_opts = ' '.join(cmd_opts + [self.cfg['installopts']])
        cmd = "export BOOST_JAM_TOOLSET=%s; ./bjam %s" % (toolset, cmd_opts)
        run_cmd(cmd, log_all=True, simple=True)
